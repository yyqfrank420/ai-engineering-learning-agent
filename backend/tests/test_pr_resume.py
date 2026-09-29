import argparse
import copy
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from eval import pr_resume as resume
from eval.live_runner import _restricted_judge_limit


def evidence():
    corpus = resume.load_corpus()
    ids = list(resume.canonical_pr_case_ids())
    identity = {"corpus_sha256": resume.corpus_sha256(), "corpus_version": corpus.corpus_version,
                "release_identity": corpus.release_identity}
    browser = {"format_version": 1, "kind": "browser_capture", "suite": "pr", "status": "complete",
               **identity, "target": "http://browser", "backend_target": "https://old", "started_at": "today",
               "dashboard_smoke": {"passed": True}, "case_states": [], "results": [], "application_telemetry": []}
    semantic = {"format_version": 1, "execution_mode": "staging_gate", "kind": "live_gate", "suite": "pr", "status": "fail", "target": "https://old",
                **identity, "evaluations": []}
    calibration = corpus.approval.calibration
    for index, case_id in enumerate(ids):
        thread = f"thread-{index}"
        failed = index == 3
        failures = ["missing graph"] if failed else []
        browser["case_states"].append({"id": case_id, "state": "completed"})
        browser["results"].append({"id": case_id, "passed": not failed, "execution_state": "completed",
            "deterministic_failures": failures, "failure_details": [{"kind": "quality"}] if failed else [],
            "thread_id": thread, "attempts": [{"thread_id": thread}], "turns": [{"answer": "source"}], "graph": {"nodes": []}})
        browser["application_telemetry"].append({"thread_id": thread, "provider_attempts": 1,
                                               "operation": "staged_graph_components"})
        judgments = []
        if index < 2:
            judgments = [{"provider": calibration.judge_provider, "model": calibration.judge_model,
                "prompt_release": resume.JUDGE_PROMPT_RELEASE, "input_tokens": 1, "output_tokens": 1,
                "dimensions": [{"dimension": name, "grade": "pass", "critical": corpus.rubrics[name].critical,
                                "evidence": ["[turn-1-answer-1] source"], "rationale": "supported"}
                               for name in corpus.by_id[case_id].rubric_dimensions]}]
        semantic["evaluations"].append({"id": case_id, "decision": "fail" if failed else "pass" if judgments else "infrastructure",
            "reason": "judge infrastructure failure: InternalServerError: 503 overloaded", "judgments": judgments,
            "deterministic_failures": failures})
    return browser, semantic, corpus, ids


def zip_bytes(reports, extra=()):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in reports.items():
            archive.writestr(name, json.dumps(value))
        for name, value in extra:
            archive.writestr(name, value)
    return output.getvalue()


def test_partition_keeps_full_provenance_and_does_not_regenerate_passes():
    browser, semantic, corpus, ids = evidence()
    before = copy.deepcopy(browser)
    groups = resume.partition(browser, semantic, corpus, ids)
    assert groups == {"fresh": [ids[3]], "replay": [ids[2], *ids[4:]], "carried": ids[:2]}
    subset = resume.subset_browser_capture(browser, selected_case_ids=groups["replay"],
                 expected_source_case_ids=ids, forbidden_operation_prefixes=())
    assert subset["results"] == [row for row in browser["results"] if row["id"] in groups["replay"]]
    assert browser == before


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "partial", "dashboard", "manual", "generic_infra",
                                     "carry_failure", "judge_identity", "corpus", "deterministic", "case_state", "format", "replay", "citation"])
def test_partition_fails_closed(mutation):
    browser, semantic, corpus, ids = evidence()
    if mutation == "duplicate":
        browser["results"][1]["id"] = ids[0]
    elif mutation == "missing":
        semantic["evaluations"].pop()
    elif mutation == "partial":
        browser["results"][0]["execution_state"] = "running"
    elif mutation == "dashboard":
        browser["dashboard_smoke"]["passed"] = False
    elif mutation == "manual":
        semantic["evaluations"][0]["decision"] = "manual_review"
    elif mutation == "generic_infra":
        semantic["evaluations"][2]["reason"] = "telemetry missing"
    elif mutation == "carry_failure":
        semantic["evaluations"][0]["judgments"][0]["dimensions"][0].update(grade="fail", critical=True)
    elif mutation == "judge_identity":
        semantic["evaluations"][0]["judgments"][0]["model"] = "different"
    elif mutation == "corpus":
        browser["corpus_sha256"] = "0" * 64
    elif mutation == "case_state":
        browser["case_states"].reverse()
    elif mutation == "format":
        semantic["format_version"] = 99
    elif mutation == "replay":
        semantic["execution_mode"] = "semantic_replay"
    elif mutation == "citation":
        semantic["evaluations"][0]["judgments"][0]["dimensions"][0]["evidence"] = ["[turn-1-answer-1] invented"]
    else:
        semantic["evaluations"][0]["deterministic_failures"] = ["failure"]
    with pytest.raises(ValueError):
        resume.partition(browser, semantic, corpus, ids)


@pytest.mark.parametrize("mutation", ["digest", "traversal", "absolute", "duplicate", "missing"])
def test_artifact_authentication(mutation):
    reports = {name: {} for name in resume.REPORT_FILES}
    extra = []
    if mutation == "traversal":
        extra = [("../escape", "bad")]
    elif mutation == "absolute":
        extra = [("/escape", "bad")]
    elif mutation == "duplicate":
        extra = [("other/browser-results.json", "{}")]
    elif mutation == "missing":
        reports.pop("deployment.json")
    data = zip_bytes(reports, extra)
    digest = "sha256:" + ("0" * 64 if mutation == "digest" else resume.sha256(data))
    with pytest.raises(ValueError):
        resume.extract_reports(data, digest)


def provenance():
    repo, old, base, current = "owner/repo", "a" * 40, "b" * 40, "c" * 40
    run = {"id": 1, "event": "pull_request", "status": "completed", "conclusion": "failure",
           "path": resume.WORKFLOW, "repository": {"full_name": repo}, "head_repository": {"full_name": repo}, "head_sha": old,
           "pull_requests": [{"number": 61, "head": {"sha": old}, "base": {"sha": base}}]}
    pr = {"number": 61, "state": "open", "head": {"sha": current, "repo": {"full_name": repo}}, "base": {"sha": base, "repo": {"full_name": repo}}}
    deployment = {"run_id": "1", "commit_sha": "d" * 40, "tree_sha": "e" * 40,
                  "image": "registry.example/repo/backend", "digest": "sha256:" + "1" * 64}
    kwargs = {"repo": repo, "head": current, "source_parents": [base, old],
              "source_tree": "e" * 40, "merge_tree": "f" * 40, "current_tree": "f" * 40}
    return run, pr, deployment, kwargs


@pytest.mark.parametrize("mutation", [None, "base", "head", "fork", "merge", "parents", "path", "status"])
def test_provenance_requires_same_open_pr_and_authenticated_merge(mutation):
    run, pr, deployment, kwargs = provenance()
    if mutation == "base":
        pr["base"]["sha"] = "9" * 40
    elif mutation == "head":
        run["head_sha"] = "9" * 40
    elif mutation == "fork":
        pr["head"]["repo"]["full_name"] = "fork/repo"
    elif mutation == "merge":
        kwargs["merge_tree"] = "9" * 40
    elif mutation == "parents":
        kwargs["source_parents"].reverse()
    elif mutation == "path":
        run["path"] = "different.yml"
    elif mutation == "status":
        run["conclusion"] = "success"
    if mutation:
        with pytest.raises(ValueError):
            resume.validate_run_identity(run, pr, deployment, **kwargs)
    else:
        assert resume.validate_run_identity(run, pr, deployment, **kwargs)["head"] == run["head_sha"]


def test_exact_reviewed_diff_required():
    patch = b"binary diff\n"
    resume.validate_diff(patch, resume.sha256(patch))
    with pytest.raises(ValueError):
        resume.validate_diff(patch + b"changed", resume.sha256(patch))


@pytest.mark.parametrize("field,value", [("digest", None), ("digest", "sha256:bad"),
                                        ("image", None), ("image", ""), ("image", "bad image")])
def test_source_image_identity_is_required(field, value):
    run, pr, deployment, kwargs = provenance()
    if value is None:
        deployment.pop(field)
    else:
        deployment[field] = value
    with pytest.raises(ValueError, match="source image"):
        resume.validate_run_identity(run, pr, deployment, **kwargs)


def test_source_image_identity_is_retained():
    run, pr, deployment, kwargs = provenance()
    identity = resume.validate_run_identity(run, pr, deployment, **kwargs)
    assert identity["image"] == deployment["image"]
    assert identity["image_digest"] == deployment["digest"]


@pytest.mark.parametrize("limit", [0, -1, 17, True, "1"])
def test_judge_budget_cannot_expand_or_disable(limit):
    with pytest.raises(ValueError):
        _restricted_judge_limit(argparse.Namespace(judge_call_limit=limit), 16)


def test_restrictive_judge_budget_defaults_and_remainder():
    assert _restricted_judge_limit(argparse.Namespace(), 16) == 16
    assert _restricted_judge_limit(argparse.Namespace(judge_call_limit=5), 16) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted", [False, True])
async def test_judge_phases_share_budget_and_replay_has_no_new_application_calls(tmp_path, monkeypatch, exhausted):
    browser, semantic, corpus, ids = evidence()
    run, pr, deployment, kwargs = provenance()
    identity = resume.validate_run_identity(run, pr, deployment, **kwargs)
    groups = resume.partition(browser, semantic, corpus, ids)
    reports = dict(zip(resume.REPORT_FILES, (browser, semantic, deployment), strict=True))
    archive = zip_bytes(reports)
    artifact = {"id": 9, "digest": "sha256:" + resume.sha256(archive)}
    raw = resume.extract_reports(archive, artifact["digest"])
    current = {"run_id": "2", "head": kwargs["head"], "tree": kwargs["current_tree"]}
    plan = {"source": identity, "repository": "owner/repo", "artifact": artifact,
            "reviewed_diff_sha256": "0" * 64, "current": current, "partition": groups, "case_ids": ids,
            "old_backend_target": "https://old", "source_file_sha256": {k: resume.sha256(v) for k, v in raw.items()}}
    resume.write_json(tmp_path / "plan.json", plan)
    (tmp_path / "source.zip").write_bytes(archive)
    fresh = copy.deepcopy(browser)
    fresh.update(suite="diagnostic", backend_target="https://new", started_at="2026-01-01T00:00:01Z")
    fresh["results"] = [dict(browser["results"][3], thread_id="fresh-thread", passed=True, deterministic_failures=[], failure_details=[])]
    fresh["application_telemetry"] = [{"thread_id": "fresh-thread", "request_id": "fresh-request", "created_at_epoch": 1767225601}]
    fresh["case_states"] = [browser["case_states"][3]]
    fresh_path = tmp_path / "fresh.json"
    resume.write_json(fresh_path, fresh)
    monkeypatch.setenv("GITHUB_RUN_ID", "2")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CANDIDATE_URL", "https://new")
    monkeypatch.setenv("IMAGE_DIGEST", "sha256:" + "f" * 64)
    proof_path = tmp_path / "deployment.json"
    resume.write_json(proof_path, {**current, "run_attempt": "1", "candidate_url": "https://new",
                                  "image_digest": "sha256:" + "f" * 64, "recorded_at_epoch": 1767225600})
    monkeypatch.setattr(resume, "authenticated_inputs", lambda *a: (run, pr, artifact))
    monkeypatch.setattr(resume, "verify_checkout", lambda *a: identity)
    monkeypatch.setattr(resume, "git", lambda *a: kwargs["current_tree"] if a[-1] == "HEAD^{tree}" else kwargs["head"])
    monkeypatch.setattr(resume, "api", lambda *a: pr)
    calibration = corpus.approval.calibration
    monkeypatch.setattr(resume, "SemanticJudge", lambda: SimpleNamespace(provider=calibration.judge_provider, model=calibration.judge_model))
    calls = []

    async def evaluate(args):
        calls.append(args)
        capture = json.loads(Path(args.input).read_text())
        if args.capture_replay:
            assert capture["results"] == [r for r in browser["results"] if r["id"] in groups["replay"]]
        evaluations = []
        for case_id in args.case:
            judgment = copy.deepcopy(semantic["evaluations"][0]["judgments"][0])
            judgment["dimensions"] = [{"dimension": name, "grade": "pass", "critical": corpus.rubrics[name].critical,
                                      "evidence": ["[turn-1-answer-1] source"], "rationale": "supported"}
                                     for name in corpus.by_id[case_id].rubric_dimensions]
            evaluations.append({"id": case_id, "decision": "pass", "judgments": [judgment], "deterministic_failures": []})
        return {"status": "pass", "budget": {"judge_calls": 16 if exhausted else len(args.case)}, "evaluations": evaluations,
                "estimated_cost": {"application_usd": 0 if args.capture_replay else 0.1},
                "cost_accounting": {}}, 0

    from pathlib import Path
    monkeypatch.setattr(resume.live_runner, "evaluate", evaluate)
    monkeypatch.setattr(resume.live_runner, "_write_outputs", resume.write_json)
    args = argparse.Namespace(input=str(fresh_path), deployment=str(proof_path), target="https://new", output_dir=str(tmp_path))
    if exhausted:
        with pytest.raises(ValueError, match="budget exhausted"):
            await resume.judge(args)
        assert len(calls) == 1
        assert (tmp_path / "fresh-live-results.json").exists()
        assert not (tmp_path / "combined-evidence.json").exists()
        return
    assert await resume.judge(args) == 0
    assert [c.judge_call_limit for c in calls] == [16, 15]
    assert [c.capture_replay for c in calls] == [False, True]
    combined = json.loads((tmp_path / "combined-evidence.json").read_text())
    assert combined["new_judge_calls"] == 6
    assert len(combined["cases"]) == 8
    assert next(c for c in combined["cases"] if c["id"] == ids[0])["application_source"] == identity
    with pytest.raises(ValueError, match="already attempted"):
        await resume.judge(args)


@pytest.mark.parametrize("mutation", [None, "old_target", "old_capture", "old_telemetry", "thread", "request", "digest", "tree", "attempt"])
def test_fresh_capture_bound_to_current_deployment(mutation, monkeypatch):
    current = {"run_id": "2", "head": "a" * 40, "tree": "b" * 40}
    proof = {**current, "run_attempt": "1", "candidate_url": "https://new",
             "image_digest": "sha256:" + "c" * 64, "recorded_at_epoch": 1767225600}
    source = {"backend_target": "https://old", "results": [{"thread_id": "old-thread"}],
              "application_telemetry": [{"request_id": "old-request"}]}
    fresh = {"backend_target": "https://new", "started_at": "2026-01-01T00:00:01Z",
             "results": [{"thread_id": "new-thread"}], "application_telemetry": [
                 {"thread_id": "new-thread", "request_id": "new-request", "created_at_epoch": 1767225601}]}
    for key, value in {"GITHUB_RUN_ID": "2", "GITHUB_RUN_ATTEMPT": "1", "CANDIDATE_URL": "https://new",
                       "IMAGE_DIGEST": proof["image_digest"]}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(resume, "git", lambda *a: current["tree"] if a[-1] == "HEAD^{tree}" else current["head"])
    target = "https://new"
    if mutation == "old_target":
        proof["candidate_url"] = fresh["backend_target"] = target = "https://old"
        monkeypatch.setenv("CANDIDATE_URL", target)
    elif mutation == "old_capture":
        fresh["started_at"] = "2025-12-31T23:59:59Z"
    elif mutation == "old_telemetry":
        fresh["application_telemetry"][0]["created_at_epoch"] -= 2
    elif mutation in ("thread", "request"):
        fresh["application_telemetry"][0][mutation + "_id"] = "old-" + mutation
    elif mutation == "digest":
        proof["image_digest"] = "sha256:" + "d" * 64
    elif mutation == "tree":
        proof["tree"] = "d" * 40
    elif mutation == "attempt":
        proof["run_attempt"] = "2"
    if mutation:
        with pytest.raises(ValueError):
            resume.validate_fresh_capture(fresh, source, proof, {"current": current}, target)
    else:
        resume.validate_fresh_capture(fresh, source, proof, {"current": current}, target)


@pytest.mark.parametrize("field", ["head_repository", "base_repository"])
def test_rejects_cross_repository_source(field):
    run, pr, deployment, kwargs = provenance()
    if field == "head_repository":
        run[field]["full_name"] = "fork/repo"
    else:
        pr["base"]["repo"]["full_name"] = "fork/repo"
    with pytest.raises(ValueError):
        resume.validate_run_identity(run, pr, deployment, **kwargs)


def test_source_api_id_must_match_requested_run(monkeypatch):
    monkeypatch.setattr(resume, "api", lambda *a: {"id": 2})
    with pytest.raises(ValueError, match="run ID"):
        resume.authenticated_inputs("1", "owner/repo")


@pytest.mark.asyncio
async def test_total_timeout_preserves_partial_reports(tmp_path, monkeypatch):
    async def timeout(args):
        resume.write_json(tmp_path / "fresh-live-results.json", {"status": "pass"})
        raise TimeoutError

    monkeypatch.setattr(resume, "judge", timeout)
    assert await resume.bounded_judge(argparse.Namespace(output_dir=str(tmp_path))) == 1
    assert json.loads((tmp_path / "fresh-live-results.json").read_text())["status"] == "pass"
    assert json.loads((tmp_path / "resume-failure.json").read_text())["timeout_seconds"] == 1200
