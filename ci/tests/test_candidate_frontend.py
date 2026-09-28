from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "workflow,step",
    [
        ("live-eval.yml", "Start candidate-wired frontend"),
        ("deploy-production.yml", "Start production-candidate frontend"),
        ("scheduled-eval.yml", "Start frontend and capture journeys"),
    ],
)
def test_candidate_frontend_build_and_preview_share_evaluation_environment(
    tmp_path, workflow, step
):
    text = (ROOT / ".github/workflows" / workflow).read_text()
    block = text.split(f"name: {step}\n", 1)[1].split("\n      - ", 1)[0]
    script = block.split("        run: |\n", 1)[1].split("          case_args=()", 1)[0]
    script = "\n".join(line.removeprefix("          ") for line in script.splitlines())
    commands = tmp_path / "commands.jsonl"
    for name in ("npm", "curl", "sleep"):
        executable = tmp_path / name
        executable.write_text(f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
if {name!r} == 'npm':
    with Path({str(commands)!r}).open('a') as output:
        output.write(json.dumps({{'argv': sys.argv[1:], 'env': {{key: os.environ.get(key) for key in ('NODE_ENV', 'VITE_EVAL_AUTH_BOOTSTRAP', 'VITE_API_PROXY_TARGET')}}}}) + '\\n')
elif {name!r} == 'curl':
    content = Path({str(commands)!r}).read_text() if Path({str(commands)!r}).exists() else ''
    sys.exit(0 if '"preview"' in content else 1)
""")
        executable.chmod(0o755)
    (tmp_path / "artifacts/live-eval").mkdir(parents=True)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CANDIDATE_URL": "https://candidate.example.test",
        "GITHUB_ENV": str(tmp_path / "github-env"),
    }
    subprocess.run(
        ["bash", "-e", "-c", script], cwd=tmp_path, env=environment, check=True
    )
    invocations = [json.loads(line) for line in commands.read_text().splitlines()]
    assert [call["argv"][3] for call in invocations] == ["build", "preview"]
    for call in invocations:
        assert call["env"] == {
            "NODE_ENV": "development",
            "VITE_EVAL_AUTH_BOOTSTRAP": "true",
            "VITE_API_PROXY_TARGET": "https://candidate.example.test",
        }
    assert invocations[1]["argv"][4:] == [
        "--",
        "--host",
        "localhost",
        "--port",
        "5173",
        "--strictPort",
    ]
