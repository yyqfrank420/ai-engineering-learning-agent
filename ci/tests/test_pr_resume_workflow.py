"""Execute the protected workflow branches with local command recorders."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/live-eval.yml").read_text())


def step(name):
    return next(item for job in workflow()["jobs"].values()
                for item in job["steps"] if item.get("name") == name or item.get("id") == name)


@pytest.fixture
def shell(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "bin").mkdir()
    log = tmp_path / "calls.jsonl"
    recorder = f'''#!{sys.executable}
import json, os, sys
if sys.argv[0].endswith('/python') and sys.argv[1:2] == ['-']:
    os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
with open(os.environ['CALL_LOG'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
sys.exit(int(os.environ.get('COMMAND_EXIT', '0')))
'''
    for relative in ("scripts/ci", "bin/python"):
        path = tmp_path / relative
        path.write_text(recorder)
        path.chmod(0o755)
    git = tmp_path / "bin/git"
    git.write_text("#!/bin/bash\nif [ \"$2\" = 'HEAD^{tree}' ]; then echo " + "b" * 40
                   + "; else echo " + "a" * 40 + "; fi\n")
    git.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
           "CALL_LOG": str(log), "GITHUB_EVENT_NAME": "workflow_dispatch",
           "GITHUB_EVENT_PATH": "event.json", "GITHUB_OUTPUT": str(tmp_path / "output"),
           "GITHUB_RUN_ID": "2", "GITHUB_RUN_ATTEMPT": "1", "CANDIDATE_URL": "https://new",
           "IMAGE_DIGEST": "sha256:" + "c" * 64,
           "SOURCE_RUN_ID": "", "REVIEWED_DIFF_SHA256": "", "RESUME_REASON": ""}

    def run(name, updates=None):
        result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", step(name)["run"]],
                                cwd=tmp_path, env={**env, **(updates or {})},
                                capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run


def test_live_workflow_yaml_and_all_shell_blocks_parse():
    for job in workflow()["jobs"].values():
        for item in job["steps"]:
            if "run" in item:
                result = subprocess.run(["/bin/bash", "-n"], input=item["run"], capture_output=True, text=True)
                assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("source,diff,reason,event,passed", [
    ("", "", "", "pull_request", True),
    ("123", "a" * 64, "Reviewed generation repair only", "workflow_dispatch", True),
    ("", "a" * 64, "Reviewed generation repair only", "workflow_dispatch", False),
    ("123", "", "Reviewed generation repair only", "workflow_dispatch", False),
    ("123", "a" * 64, "short", "workflow_dispatch", False),
    ("123", "a" * 64, "Reviewed generation repair only", "pull_request", False),
])
def test_dispatch_inputs_fail_closed(shell, tmp_path, source, diff, reason, event, passed):
    result, _ = shell("impact", {"SOURCE_RUN_ID": source, "REVIEWED_DIFF_SHA256": diff,
                                 "RESUME_REASON": reason, "GITHUB_EVENT_NAME": event})
    assert (result.returncode == 0) is passed
    output = tmp_path / "output"
    assert (output.exists() and "ai-impact=true" in output.read_text()) is (passed and bool(source))


@pytest.mark.parametrize("cases", [None, "research\n", "research education-diagram\n", "", "missing"])
def test_browser_branch_selects_only_fresh_cases(shell, tmp_path, cases):
    if cases is not None:
        directory = tmp_path / "artifacts/live-eval/resume"
        directory.mkdir(parents=True)
        (directory / "plan.json").write_text("{}")
        if cases != "missing":
            (directory / "fresh-case-ids.txt").write_text(cases)
    result, calls = shell("browser")
    if cases in ("", "missing"):
        assert result.returncode != 0
        assert calls == []
        return
    assert result.returncode == 0, result.stderr
    argv = calls[0]
    assert argv[:3] == ["browser", "--suite", "pr" if cases is None else "diagnostic"]
    assert [argv[i + 1] for i, arg in enumerate(argv) if arg == "--case"] == (cases.split() if cases else [])
    if cases:
        proof = json.loads((directory / "candidate-deployment.json").read_text())
        assert proof["head"] == "a" * 40 and proof["tree"] == "b" * 40
        assert proof["candidate_url"] == "https://new"
        again, subsequent = shell("browser")
        assert again.returncode != 0
        assert subsequent == calls


@pytest.mark.parametrize("selective", [False, True])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_semantic_branch_propagates_validator_failure(shell, tmp_path, selective, exit_code):
    if selective:
        directory = tmp_path / "artifacts/live-eval/resume"
        directory.mkdir(parents=True)
        (directory / "plan.json").write_text("{}")
    result, calls = shell("semantic", {"COMMAND_EXIT": str(exit_code)})
    assert result.returncode == exit_code
    assert calls[0][:3] == (["-m", "eval.pr_resume", "judge"] if selective else ["live", "--suite", "pr"])
    if selective:
        assert "--deployment" in calls[0]
    assert "hashFiles('artifacts/live-eval/browser-results.json') != ''" in step("semantic")["if"]


@pytest.mark.parametrize("browser,semantic", [("failure", "success"), ("success", "failure"),
                                               ("skipped", "success"), ("success", "skipped")])
def test_missing_or_failed_evidence_cannot_publish(shell, browser, semantic):
    result, _ = shell("Enforce evaluation result", {"BROWSER_OUTCOME": browser, "SEMANTIC_OUTCOME": semantic})
    assert result.returncode != 0
