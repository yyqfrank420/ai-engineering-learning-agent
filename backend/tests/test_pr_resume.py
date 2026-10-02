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
    semantic["application_telemetry"] = copy.deepcopy(browser["application_telemetry"])
    for result, evaluation in zip(browser["results"], semantic["evaluations"], strict=True):
        derived = resume.live_runner._service_expansion_failures(
            result, corpus.by_id[result["id"]], semantic["application_telemetry"],
        )
        if derived:
            evaluation.update(decision="fail", judgments=[],
                              deterministic_failures=[*result["deterministic_failures"], *derived])
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
    assert groups == {"fresh": [ids[3], ids[5]], "replay": [ids[2], ids[4], *ids[6:]], "carried": ids[:2]}
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
    run = {"id": 1, "run_attempt": 1, "event": "pull_request", "status": "completed", "conclusion": "failure",
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


def test_source_run_head_survives_mutable_nested_pr_head():
    run, pr, deployment, kwargs = provenance()
    run["pull_requests"][0]["head"]["sha"] = pr["head"]["sha"]
    identity = resume.validate_run_identity(run, pr, deployment, **kwargs)
    assert identity["head"] == run["head_sha"]
    run["head_sha"] = pr["head"]["sha"]
    with pytest.raises(ValueError, match="authenticated PR merge"):
        resume.validate_run_identity(run, pr, deployment, **kwargs)


def test_mutable_source_base_cannot_override_original_merge_parent():
    run, pr, deployment, kwargs = provenance()
    run["pull_requests"][0]["base"]["sha"] = "9" * 40
    pr["base"]["sha"] = "9" * 40
    with pytest.raises(ValueError, match="authenticated PR merge"):
        resume.validate_run_identity(run, pr, deployment, **kwargs)


@pytest.mark.parametrize("limit", [0, -1, 17, True, "1"])
def test_judge_budget_cannot_expand_or_disable(limit):
    with pytest.raises(ValueError):
        _restricted_judge_limit(argparse.Namespace(judge_call_limit=limit), 16)


def test_restrictive_judge_budget_defaults_and_remainder():
    assert _restricted_judge_limit(argparse.Namespace(), 16) == 16
    assert _restricted_judge_limit(argparse.Namespace(judge_call_limit=5), 16) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["infrastructure", "manual_review"])
@pytest.mark.parametrize("outcome", ["pass", "exhausted", "manual_review", "attempt_tamper"])
async def test_judge_phases_share_budget_and_replay_has_no_new_application_calls(tmp_path, monkeypatch, source_kind, outcome):
    browser, semantic, corpus, ids = manual_evidence() if source_kind == "manual_review" else evidence()
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
    if outcome == "attempt_tamper":
        plan["source"] = {**identity, "run_attempt": 2}
    resume.write_json(tmp_path / "plan.json", plan)
    (tmp_path / "source.zip").write_bytes(archive)
    fresh = copy.deepcopy(browser)
    fresh.update(suite="diagnostic", backend_target="https://new", started_at="2026-01-01T00:00:01Z")
    fresh["results"] = [
        dict(row, thread_id=f"fresh-{row['id']}", passed=True,
             deterministic_failures=[], failure_details=[])
        for row in browser["results"] if row["id"] in groups["fresh"]
    ]
    fresh["application_telemetry"] = [
        {"thread_id": row["thread_id"], "request_id": f"request-{row['id']}",
         "created_at_epoch": 1767225601} for row in fresh["results"]
    ]
    fresh["case_states"] = [row for row in browser["case_states"] if row["id"] in groups["fresh"]]
    fresh_path = tmp_path / "fresh.json"
    resume.write_json(fresh_path, fresh)
    monkeypatch.setenv("GITHUB_RUN_ID", "2")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CANDIDATE_URL", "https://new")
    monkeypatch.setenv("IMAGE_DIGEST", "sha256:" + "f" * 64)
    proof_path = tmp_path / "deployment.json"
    resume.write_json(proof_path, {**current, "run_attempt": "1", "candidate_url": "https://new",
                                  "image_digest": "sha256:" + "f" * 64, "recorded_at_epoch": 1767225600})
    def authenticate(run_id, repo, attempt):
        assert run_id == "1" and repo == "owner/repo"
        if attempt != run["run_attempt"]:
            raise ValueError("source run attempt mismatch")
        return run, pr, artifact

    monkeypatch.setattr(resume, "authenticated_inputs", authenticate)
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
            judgment["dimensions"] = [{"dimension": name, "grade": "borderline" if args.capture_replay and outcome == "manual_review" else "pass", "critical": corpus.rubrics[name].critical,
                                      "evidence": ["[turn-1-answer-1] source"], "rationale": "supported"}
                                     for name in corpus.by_id[case_id].rubric_dimensions]
            decision = "manual_review" if args.capture_replay and outcome == "manual_review" else "pass"
            evaluations.append({"id": case_id, "decision": decision, "judgments": [judgment], "deterministic_failures": []})
        return {"status": "fail" if args.capture_replay and outcome == "manual_review" else "pass", "budget": {"judge_calls": 16 if outcome == "exhausted" else len(args.case)}, "evaluations": evaluations,
                "estimated_cost": {"application_usd": 0 if args.capture_replay else 0.1},
                "cost_accounting": {}}, 0

    from pathlib import Path
    monkeypatch.setattr(resume.live_runner, "evaluate", evaluate)
    monkeypatch.setattr(resume.live_runner, "_write_outputs", resume.write_json)
    args = argparse.Namespace(input=str(fresh_path), deployment=str(proof_path), target="https://new", output_dir=str(tmp_path))
    if outcome == "attempt_tamper":
        with pytest.raises(ValueError, match="attempt mismatch"):
            await resume.judge(args)
        assert calls == []
        assert not (tmp_path / "judge-reservation.json").exists()
        return
    if outcome == "exhausted":
        with pytest.raises(ValueError, match="budget exhausted"):
            await resume.judge(args)
        assert len(calls) == 1
        assert (tmp_path / "fresh-live-results.json").exists()
        assert not (tmp_path / "combined-evidence.json").exists()
        return
    assert await resume.judge(args) == (1 if outcome == "manual_review" else 0)
    assert [c.judge_call_limit for c in calls] == [16, 16 - len(groups["fresh"])]
    assert [c.capture_replay for c in calls] == [False, True]
    combined = json.loads((tmp_path / "combined-evidence.json").read_text())
    assert combined["new_judge_calls"] == (4 if source_kind == "manual_review" else 6)
    assert combined["status"] == ("fail" if outcome == "manual_review" else "pass")
    assert calls[0].case == groups["fresh"] and calls[1].case == groups["replay"]
    assert all(call.manual_review_policy == "blocking" for call in calls)
    assert combined["new_cost_accounting"]["replay"]["application_usd"] == 0
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


def manual_evidence():
    browser, semantic, corpus, ids = evidence()
    template = copy.deepcopy(semantic["evaluations"][0]["judgments"][0])
    for index, row in enumerate(semantic["evaluations"]):
        if row["deterministic_failures"]:
            continue
        judgment = copy.deepcopy(template)
        judgment["dimensions"] = [
            {"dimension": name, "grade": "borderline" if index in (2, 4) else "pass",
             "critical": corpus.rubrics[name].critical,
             "evidence": ["[turn-1-answer-1] source"], "rationale": "supported"}
            for name in corpus.by_id[row["id"]].rubric_dimensions
        ]
        row.update(decision="manual_review" if index in (2, 4) else "pass", judgments=[judgment])
    return browser, semantic, corpus, ids


def test_validated_manual_review_is_replayed_and_never_carried():
    browser, semantic, corpus, ids = manual_evidence()
    assert resume.partition(browser, semantic, corpus, ids) == {
        "fresh": [ids[3], ids[5]], "replay": [ids[2], ids[4]],
        "carried": [ids[0], ids[1], *ids[6:]],
    }


@pytest.mark.parametrize("mutation", ["citation", "decision", "missing", "partial"])
def test_manual_review_requires_valid_original_judgments(mutation):
    browser, semantic, corpus, ids = manual_evidence()
    row = semantic["evaluations"][2]
    if mutation == "citation":
        row["judgments"][0]["dimensions"][0]["evidence"] = ["invented"]
    elif mutation == "decision":
        for dimension in row["judgments"][0]["dimensions"]:
            dimension["grade"] = "pass"
    elif mutation == "missing":
        row["judgments"] = []
    else:
        browser["results"][2]["execution_state"] = "running"
    with pytest.raises(ValueError):
        resume.partition(browser, semantic, corpus, ids)


def attempt_metadata():
    run, pr, _, _ = provenance()
    artifact = {"id": 9, "name": resume.ARTIFACT, "expired": False,
                "workflow_run": {"id": run["id"], "head_sha": run["head_sha"]},
                "created_at": "2026-09-30T15:28:57Z"}
    job = {"id": 10, "name": "Protected staging browser and LLM evaluation",
           "run_id": run["id"], "run_attempt": 1, "head_sha": run["head_sha"],
           "status": "completed", "conclusion": "failure",
           "started_at": "2026-09-30T15:05:41Z", "completed_at": "2026-09-30T15:29:10Z",
           "steps": [{"name": "Upload evaluation evidence", "status": "completed", "conclusion": "success",
                      "started_at": "2026-09-30T15:28:56Z", "completed_at": "2026-09-30T15:28:57Z"}]}
    return run, pr, artifact, {"total_count": 1, "jobs": [job]}


@pytest.mark.parametrize("explicit", [False, True])
def test_authentication_pins_exact_attempt(monkeypatch, explicit):
    run, pr, artifact, jobs = attempt_metadata()
    paths = []

    def api(path):
        paths.append(path)
        if path.endswith("/attempts/1/jobs?per_page=100"):
            return jobs
        if path.endswith("/artifacts?per_page=100"):
            return {"total_count": 1, "artifacts": [artifact]}
        if path.endswith("/pulls/61"):
            return pr
        if path.endswith("/attempts/1"):
            return run
        assert path.endswith("/runs/1")
        return {**run, "run_attempt": 1}

    monkeypatch.setattr(resume, "api", api)
    assert resume.authenticated_inputs("1", "owner/repo", 1 if explicit else None) == (run, pr, artifact)
    assert ("repos/owner/repo/actions/runs/1" in paths) is (not explicit)
    assert "repos/owner/repo/actions/runs/1/attempts/1" in paths


def test_explicit_failed_attempt_survives_cancelled_latest_snapshot(monkeypatch):
    run, pr, artifact, jobs = attempt_metadata()

    def api(path):
        if path.endswith("/attempts/1/jobs?per_page=100"):
            return jobs
        if path.endswith("/artifacts?per_page=100"):
            return {"total_count": 1, "artifacts": [artifact]}
        if path.endswith("/pulls/61"):
            return pr
        if path.endswith("/attempts/1"):
            return run
        return {**run, "run_attempt": 2, "conclusion": "cancelled"}

    monkeypatch.setattr(resume, "api", api)
    assert resume.authenticated_inputs("1", "owner/repo", 1)[0] == run
    with pytest.raises(ValueError, match="selected source attempt is not failed"):
        resume.authenticated_inputs("1", "owner/repo")


@pytest.mark.parametrize("mutation", ["id", "attempt", "cancelled", "zero", "negative", "bool"])
def test_selected_attempt_rejects_mismatch_or_invalid_number(monkeypatch, mutation):
    run, _, _, _ = attempt_metadata()
    attempt = 1
    if mutation == "id":
        run["id"] = 2
    elif mutation == "attempt":
        run["run_attempt"] = 2
    elif mutation == "cancelled":
        run["conclusion"] = "cancelled"
    else:
        attempt = {"zero": 0, "negative": -1, "bool": True}[mutation]
    monkeypatch.setattr(resume, "api", lambda path: run)
    with pytest.raises(ValueError):
        resume.authenticated_inputs("1", "owner/repo", attempt)


@pytest.mark.parametrize("mutation", [None, "early", "late", "missing_time", "bad_time", "run", "head",
                                     "job_attempt", "job_attempt_bool", "job_head", "duplicate_job", "truncated_jobs",
                                     "missing_job", "duplicate_step", "failed_upload", "missing_steps"])
def test_artifact_must_belong_to_exact_successful_upload(mutation):
    run, _, artifact, jobs = attempt_metadata()
    job = jobs["jobs"][0]
    if mutation in ("early", "late"):
        artifact["created_at"] = "2026-09-30T15:28:" + ("55Z" if mutation == "early" else "58Z")
    elif mutation == "missing_time":
        artifact.pop("created_at")
    elif mutation == "bad_time":
        artifact["created_at"] = "2026-09-30T15:28:99Z"
    elif mutation == "run":
        artifact["workflow_run"]["id"] = 2
    elif mutation == "head":
        artifact["workflow_run"]["head_sha"] = "9" * 40
    elif mutation == "job_attempt":
        job["run_attempt"] = 2
    elif mutation == "job_attempt_bool":
        job["run_attempt"] = True
    elif mutation == "job_head":
        job["head_sha"] = "9" * 40
    elif mutation == "duplicate_job":
        jobs["jobs"].append(copy.deepcopy(job))
        jobs["total_count"] = 2
    elif mutation == "truncated_jobs":
        jobs["total_count"] = 101
    elif mutation == "missing_job":
        jobs.update(total_count=0, jobs=[])
    elif mutation == "duplicate_step":
        job["steps"].append(copy.deepcopy(job["steps"][0]))
    elif mutation == "failed_upload":
        job["steps"][0]["conclusion"] = "failure"
    elif mutation == "missing_steps":
        job.pop("steps")
    if mutation:
        with pytest.raises(ValueError):
            resume.validate_artifact_attempt(artifact, jobs, run)
    else:
        resume.validate_artifact_attempt(artifact, jobs, run)
        artifact["created_at"] = job["steps"][0]["started_at"]
        resume.validate_artifact_attempt(artifact, jobs, run)


@pytest.mark.parametrize("attempt", [None, 0, -1, True, "1"])
def test_run_identity_rejects_invalid_attempt_metadata(attempt):
    run, pr, deployment, kwargs = provenance()
    if attempt is None:
        run.pop("run_attempt")
    else:
        run["run_attempt"] = attempt
    with pytest.raises(ValueError, match="invalid source run attempt"):
        resume.validate_run_identity(run, pr, deployment, **kwargs)


@pytest.mark.parametrize("browser_passed", [True, False])
@pytest.mark.parametrize("tamper", [None, "omitted", "additional", "decision", "judgments"])
def test_browser_version_reuse_requires_fresh_service_case_with_missing_turn_graph(tamper, browser_passed):
    browser, semantic, corpus, ids = evidence()
    result = browser["results"][5]
    graph = {"version": "approved-1", "nodes": [{"id": "service", "type": "service"}]}
    result["graph"] = graph
    result["turns"] = [
        {"turn": 1, "graph": graph},
        {"turn": 2, "graph": graph},
        {"turn": 3, "request_id": "expand-3", "graph": None},
    ]
    browser_failures = [] if browser_passed else [
        "case graph-expansion turn 3 reused graph version approved-1"
    ]
    result.update(passed=browser_passed, deterministic_failures=browser_failures,
                  failure_details=[] if browser_passed else [{
                      "kind": "quality", "code": "required_graph_version_reused",
                      "message": browser_failures[0], "blocking": True, "retryable": False,
                  }])
    evaluation = semantic["evaluations"][5]
    failures = [*browser_failures, "service expansion turn 3: missing prior or expanded turn graph"]
    evaluation.update(decision="fail", judgments=[], deterministic_failures=failures.copy())
    if tamper == "omitted":
        evaluation["deterministic_failures"] = browser_failures.copy()
    elif tamper == "additional":
        evaluation["deterministic_failures"].append("invented failure")
    elif tamper == "decision":
        evaluation["decision"] = "infrastructure"
    elif tamper == "judgments":
        evaluation["judgments"] = [semantic["evaluations"][0]["judgments"][0]]
    before = copy.deepcopy((browser, semantic))
    if tamper is not None:
        with pytest.raises(ValueError):
            resume.partition(browser, semantic, corpus, ids)
    else:
        assert result["passed"] is browser_passed
        assert result["deterministic_failures"] == browser_failures
        assert evaluation["deterministic_failures"] == failures
        assert ids[5] in resume.partition(browser, semantic, corpus, ids)["fresh"]
    assert (browser, semantic) == before


@pytest.mark.parametrize("telemetry", [None, {}, [None], ["invalid"]])
def test_partition_rejects_invalid_persisted_application_telemetry(telemetry):
    browser, semantic, corpus, ids = evidence()
    semantic["application_telemetry"] = telemetry
    with pytest.raises(ValueError, match="invalid source application telemetry"):
        resume.partition(browser, semantic, corpus, ids)


@pytest.mark.parametrize("mutation", ["missing", "model", "fallback", "correlation"])
def test_partition_recomputes_service_provider_evidence_from_semantic_telemetry(mutation):
    browser, semantic, corpus, ids = evidence()
    case = corpus.by_id[ids[5]]
    expectation = case.steps[2].service_expansion
    parents = [{"id": f"service-{index}", "type": "service", "label": label}
               for index, label in enumerate(expectation.target_service_labels)]
    prior = {"nodes": parents}
    expanded = {"nodes": [*parents, *[
        {"id": f"internal-{index}", "type": "component", "technology": "Component",
         "parent_service_id": node["id"]} for index, node in enumerate(parents)
    ]]}
    result = browser["results"][5]
    result["turns"] = [{"turn": 2, "graph": prior},
                       {"turn": 3, "graph": expanded, "request_id": "expand-3"}]
    calls = [{"thread_id": result["thread_id"], "request_id": "expand-3",
              "operation": operation, "provider_attempts": 1, "status": "success",
              "model": expectation.specialist_model, "effort": expectation.specialist_effort,
              "specialist_tool_version": "service-expansion-v1",
              "service_expansion_complexity": "high",
              "target_service_ids": [node["id"] for node in parents], "fallback": False}
             for operation in ("staged_graph_components", "staged_graph_connections")]
    semantic["application_telemetry"].extend(calls)
    browser["application_telemetry"].extend(copy.deepcopy(calls))
    evaluation = semantic["evaluations"][5]
    evaluation.update(decision="infrastructure", judgments=[], deterministic_failures=[])
    assert ids[5] in resume.partition(browser, semantic, corpus, ids)["replay"]
    if mutation == "missing":
        semantic["application_telemetry"].remove(calls[0])
    elif mutation == "model":
        calls[0]["model"] = "unexpected-model"
    elif mutation == "fallback":
        calls[0]["fallback"] = True
    else:
        calls[0]["request_id"] = "another-request"
    with pytest.raises(ValueError, match="deterministic evidence mismatch"):
        resume.partition(browser, semantic, corpus, ids)


@pytest.mark.parametrize("mutation,expected_error", [
    (None, None),
    ("legacy_source", None),
    ("raised_helper_limit", "restrictive budget helper changed"),
    ("unrelated_runner", "live runner changed beyond restrictive budget support"),
    ("live_policy", "live evaluation policy changed"),
    ("eval_definition", "evaluation definition changed"),
])
def test_eval_code_gate_authenticates_actual_runner_and_manifest(monkeypatch, mutation, expected_error):
    from pathlib import Path

    runner_path = resume.ROOT / "backend/eval/live_runner.py"
    manifest_path = resume.ROOT / "ci/quality.json"
    runner = runner_path.read_text()
    manifest = manifest_path.read_text()
    source_manifest = json.loads(manifest)
    current_runner = runner
    source_runner = runner
    if mutation == "legacy_source":
        helper = runner[runner.index("def _restricted_judge_limit("):runner.index("async def evaluate(")]
        parser_addition = (
            '    parser.add_argument(\n'
            '        "--judge-call-limit", type=int, help="Restrict the suite judge-call budget"\n'
            '    )\n'
        )
        budget_call = (
            'judge_calls=_restricted_judge_limit(\n'
            '            args, limits["judge_calls"] if is_pr_budget else 40\n'
            '        ),'
        )
        assert runner.count(parser_addition) == runner.count(budget_call) == 1
        source_runner = runner.replace(parser_addition, "").replace(helper, "").replace(
            budget_call, 'judge_calls=limits["judge_calls"] if is_pr_budget else 40,'
        )
        assert "_restricted_judge_limit" not in source_runner
        assert "--judge-call-limit" not in source_runner
        compile(source_runner, "legacy-live-runner.py", "exec")
    if mutation == "raised_helper_limit":
        current_runner = runner.replace("1 <= limit <= default", "1 <= limit <= default + 1")
        assert current_runner != runner
    elif mutation == "unrelated_runner":
        current_runner = runner + "\n# Unrelated evaluation change.\n"
    elif mutation == "live_policy":
        source_manifest["live"]["budgets"]["judge_calls"] -= 1
    original_read = Path.read_text
    original_command = resume.command

    def read_text(path, *args, **kwargs):
        if path == runner_path:
            return current_runner
        return original_read(path, *args, **kwargs)

    def source_command(*args):
        if args == ("git", "show", "source:ci/quality.json"):
            return json.dumps(source_manifest).encode()
        if args == ("git", "show", "source:backend/eval/live_runner.py"):
            return source_runner.encode()
        if mutation == "eval_definition" and args == (
            "git", "rev-parse", "source:backend/eval/semantic_gate.py"
        ):
            return b"changed-source-definition"
        return original_command(*(
            "HEAD" + arg[len("source"):] if arg == "source" or arg.startswith("source:") else arg
            for arg in args
        ))

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(resume, "command", source_command)
    if expected_error is None:
        resume.validate_eval_code("source")
    else:
        with pytest.raises(ValueError, match=expected_error):
            resume.validate_eval_code("source")
