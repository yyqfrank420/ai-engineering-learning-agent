"""Authenticate and combine a failed-only PR evaluation without rewriting history."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess  # nosec B404
import zipfile

from eval.evidence_replay import canonical_pr_case_ids, subset_browser_capture
from eval import live_runner
from eval.judge_adapter import JUDGE_PROMPT_RELEASE, SemanticJudge, _artifact_sources
from eval.quality_corpus import corpus_sha256, load_corpus
from eval.semantic_gate import DimensionJudgment, JudgeResult, decide_semantic_gate


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ".github/workflows/live-eval.yml"
ARTIFACT = "live-eval-artifacts"
REPORT_FILES = ("browser-results.json", "live-results.json", "deployment.json")

def judge_limit() -> int:
    limit = json.loads((ROOT / "ci/quality.json").read_text())["live"]["budgets"]["judge_calls"]
    require(type(limit) is int and 1 <= limit <= 16, "invalid resume judge budget")
    return limit


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def command(*argv: str) -> bytes:
    # Fixed executables and argument vectors; no shell interpolation.
    return subprocess.check_output(argv, cwd=ROOT)  # nosec B603


def git(*args: str) -> str:
    return command("git", *args).decode().strip()


def api(path: str) -> dict:
    return json.loads(command("gh", "api", path))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def extract_reports(archive: bytes, expected_digest: str) -> dict[str, bytes]:
    require(expected_digest == "sha256:" + sha256(archive), "artifact ZIP digest mismatch")
    reports: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        require(sum(item.file_size for item in zipped.infolist()) <= 512 * 1024 * 1024,
                "artifact exceeds extraction limit")
        paths: set[str] = set()
        for item in zipped.infolist():
            path = PurePosixPath(item.filename)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in item.filename,
                    "unsafe artifact path")
            require(not stat.S_ISLNK(item.external_attr >> 16), "artifact symlink")
            require(item.filename not in paths, "duplicate artifact path")
            paths.add(item.filename)
            if path.name in REPORT_FILES and not item.is_dir():
                require(path.name not in reports, "duplicate evidence report")
                reports[path.name] = zipped.read(item)
    require(set(reports) == set(REPORT_FILES), "missing evidence report")
    return reports


def ordered_items(document: dict, key: str, ids: list[str]) -> list[dict]:
    rows = document.get(key)
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), f"invalid {key}")
    require([row.get("id") for row in rows] == ids, f"missing, duplicate, or reordered {key}")
    return rows


def validate_judgments(evaluation: dict, case, corpus, result: dict) -> None:
    judgments = evaluation.get("judgments")
    require(isinstance(judgments, list) and 1 <= len(judgments) <= 2, "invalid judgments")
    calibration = corpus.approval.calibration
    citations = {f"[{key}] {value}" for key, value in _artifact_sources(live_runner._judge_payload(result)).items()}
    parsed = []
    for judgment in judgments:
        require(judgment.get("provider") == calibration.judge_provider
                and judgment.get("model") == calibration.judge_model
                and judgment.get("prompt_release") == JUDGE_PROMPT_RELEASE == calibration.judge_release,
                "judge identity mismatch")
        dimensions = judgment.get("dimensions")
        require(isinstance(dimensions, list) and [d.get("dimension") for d in dimensions] == list(case.rubric_dimensions),
                "judge dimensions mismatch")
        for dimension in dimensions:
            rubric = corpus.rubrics[dimension["dimension"]]
            require(dimension.get("grade") in {"pass", "borderline", "fail"}
                    and dimension.get("critical") is rubric.critical
                    and isinstance(dimension.get("evidence"), list)
                    and 1 <= len(dimension["evidence"]) <= 3, "invalid judgment dimension")
            require(all(isinstance(item, str) and item in citations for item in dimension["evidence"]),
                    "judgment evidence does not match captured source")
        parsed.append(JudgeResult(
            dimensions=tuple(DimensionJudgment(**{**d, "evidence": tuple(d["evidence"])}) for d in dimensions),
            provider=judgment["provider"], model=judgment["model"], input_tokens=0, output_tokens=0,
        ))
    decision = decide_semantic_gate(parsed[0], parsed[1] if len(parsed) == 2 else None)
    require(decision.status == evaluation["decision"], "semantic decision disagrees with judgments")


def partition(browser: dict, semantic: dict, corpus, ids: list[str]) -> dict[str, list[str]]:
    require(browser.get("kind") == "browser_capture" and browser.get("suite") == "pr"
            and browser.get("status") == "complete" and browser.get("format_version") == 1,
            "incomplete PR browser capture")
    require(semantic.get("kind") == "live_gate" and semantic.get("suite") == "pr"
            and semantic.get("status") in {"fail", "infrastructure"}
            and semantic.get("format_version") == 1 and semantic.get("execution_mode") == "staging_gate",
            "source gate is not failed")
    require(browser.get("dashboard_smoke", {}).get("passed") is True, "source dashboard failed")
    require(browser.get("backend_target") == semantic.get("target"), "source targets disagree")
    for report in (browser, semantic):
        require(report.get("corpus_sha256") == corpus_sha256()
                and report.get("corpus_version") == corpus.corpus_version
                and report.get("release_identity") == corpus.release_identity, "corpus identity mismatch")
    results = ordered_items(browser, "results", ids)
    states = ordered_items(browser, "case_states", ids)
    evaluations = ordered_items(semantic, "evaluations", ids)
    groups: dict[str, list[str]] = {"fresh": [], "replay": [], "carried": []}
    for result, state, evaluation in zip(results, states, evaluations, strict=True):
        case_id = result["id"]
        require(result.get("execution_state") == state.get("state") == "completed", "partial case")
        failures = result.get("deterministic_failures")
        require(type(result.get("passed")) is bool and isinstance(failures, list)
                and result["passed"] == (not failures), "invalid browser pass state")
        require(evaluation.get("deterministic_failures") == failures, "deterministic evidence mismatch")
        decision = evaluation.get("decision")
        judgments = evaluation.get("judgments")
        require(isinstance(judgments, list), "missing judgments")
        if not result["passed"]:
            details = result.get("failure_details")
            require(decision == "fail" and not judgments and isinstance(details, list)
                    and bool(details) and all(d.get("kind") == "quality" for d in details),
                    "unrecognized browser failure")
            groups["fresh"].append(case_id)
        elif decision == "infrastructure" and not judgments:
            require(bool(re.match(
                r"judge infrastructure failure: (?:InternalServerError|APIConnectionError|APITimeoutError|RateLimitError|ServiceUnavailableError):",
                evaluation.get("reason", ""),
            )), "infrastructure failure is not an identified judge-provider failure")
            groups["replay"].append(case_id)
        elif decision in {"pass", "fail"} and judgments:
            validate_judgments(evaluation, corpus.by_id[case_id], corpus, result)
            groups["carried" if decision == "pass" else "fresh"].append(case_id)
        else:
            raise ValueError("manual or partial semantic result cannot resume")
    require(bool(groups["fresh"]), "resume requires a fresh quality-failed case")
    reusable = [case_id for case_id in ids if case_id not in groups["fresh"]]
    if reusable:
        subset_browser_capture(browser, selected_case_ids=reusable,
                               expected_source_case_ids=ids, forbidden_operation_prefixes=())
    return groups


def validate_run_identity(run: dict, pr: dict, deployment: dict, *, repo: str, head: str,
                          source_parents: list[str], source_tree: str, merge_tree: str,
                          current_tree: str) -> dict:
    require(run.get("event") == "pull_request" and run.get("status") == "completed"
            and run.get("conclusion") == "failure" and run.get("path") == WORKFLOW
            and run.get("repository", {}).get("full_name") == repo
            and run.get("head_repository", {}).get("full_name") == repo, "source run provenance mismatch")
    pulls = run.get("pull_requests", [])
    require(len(pulls) == 1, "source run must identify one PR")
    source_pr = pulls[0]
    # GitHub refreshes nested PR refs after pushes; the run SHA is immutable.
    source_head = run["head_sha"]
    source_base = source_pr["base"]["sha"]
    require(pr.get("number") == source_pr.get("number") and pr.get("state") == "open"
            and pr.get("head", {}).get("sha") == head
            and pr["head"].get("repo", {}).get("full_name") == repo
            and pr.get("base", {}).get("repo", {}).get("full_name") == repo
            and pr.get("base", {}).get("sha") == source_base, "current PR head/base mismatch")
    require(source_parents == [source_base, source_head], "source checkout is not authenticated PR merge")
    require(deployment.get("tree_sha") == source_tree
            and str(deployment.get("run_id")) == str(run.get("id")), "deployment identity mismatch")
    digest = deployment.get("digest")
    image = deployment.get("image")
    require(isinstance(digest, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", digest)),
            "invalid source image digest")
    require(isinstance(image, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", image))
            and "/" in image, "invalid source image identity")
    require(merge_tree == current_tree, "dispatch tree differs from current PR merge tree")
    return {"run_id": str(run["id"]), "head": source_head, "base": source_base,
            "commit": deployment["commit_sha"], "tree": source_tree, "pr": pr["number"],
            "image": image, "image_digest": digest}


def validate_diff(actual: bytes, expected: str) -> None:
    require(bool(re.fullmatch(r"[0-9a-f]{64}", expected)) and sha256(actual) == expected,
            "reviewed diff SHA256 mismatch")


def validate_eval_code(source: str) -> None:
    before_manifest = json.loads(command("git", "show", f"{source}:ci/quality.json"))
    current_manifest = json.loads((ROOT / "ci/quality.json").read_text())
    require(before_manifest["live"] == current_manifest["live"], "live evaluation policy changed")
    judge_limit()
    paths = set(git("ls-tree", "-r", "--name-only", source, "backend/eval").splitlines())
    paths.update(git("ls-tree", "-r", "--name-only", "HEAD", "backend/eval").splitlines())
    for path in paths - {"backend/eval/pr_resume.py", "backend/eval/live_runner.py"}:
        require(git("rev-parse", f"{source}:{path}") == git("rev-parse", f"HEAD:{path}"),
                f"evaluation definition changed: {path}")
    before = command("git", "show", f"{source}:backend/eval/live_runner.py").decode()
    after = (ROOT / "backend/eval/live_runner.py").read_text()
    parser_line = '    parser.add_argument("--judge-call-limit", type=int, help="Restrict the suite judge-call budget")\n'
    helper = after[after.index("def _restricted_judge_limit("):after.index("async def evaluate(")]
    # Authenticate the one allowed runner addition, not arbitrary code in that span.
    require(sha256(helper.encode()) == "821fd0902c11944e5cc1a215d6e0abfece39df154d21771e425dc525ff0492db",
            "restrictive budget helper changed")
    normalized = after.replace(parser_line, "").replace(helper, "").replace(
        'judge_calls=_restricted_judge_limit(args, limits["judge_calls"] if is_pr_budget else 40),',
        'judge_calls=limits["judge_calls"] if is_pr_budget else 40,',
    )
    require(before in (after, normalized), "live runner changed beyond restrictive budget support")


def authenticated_inputs(source_run_id: str, repo: str) -> tuple[dict, dict, dict]:
    require(bool(re.fullmatch(r"[0-9]+", source_run_id)), "invalid source run ID")
    run = api(f"repos/{repo}/actions/runs/{source_run_id}")
    require(str(run.get("id")) == source_run_id, "source run ID mismatch")
    pulls = run.get("pull_requests", [])
    require(len(pulls) == 1, "source PR metadata missing")
    pr = api(f"repos/{repo}/pulls/{int(pulls[0]['number'])}")
    artifacts = api(f"repos/{repo}/actions/runs/{source_run_id}/artifacts?per_page=100")
    require(artifacts.get("total_count", 101) <= 100, "artifact listing truncated")
    selected = [a for a in artifacts.get("artifacts", []) if a.get("name") == ARTIFACT]
    require(len(selected) == 1 and selected[0].get("expired") is False, "source artifact unavailable")
    return run, pr, selected[0]


def verify_checkout(run: dict, pr: dict, deployment: dict, repo: str, reviewed_diff: str) -> dict:
    require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "resume requires dispatch")
    require(repo == os.environ.get("GITHUB_REPOSITORY")
            and bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)), "repository mismatch")
    head = git("rev-parse", "HEAD")
    require(head == os.environ.get("GITHUB_SHA"), "dispatch checkout SHA mismatch")
    require(not git("status", "--porcelain", "--untracked-files=no"), "tracked checkout is dirty")
    source_head = run["head_sha"]
    source_commit = deployment["commit_sha"]
    shas = (source_head, source_commit, pr["base"]["sha"], pr["merge_commit_sha"], head)
    require(all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) for sha in shas),
            "invalid commit SHA")
    # PR merge objects may be absent even in a full branch checkout.
    for sha in dict.fromkeys(shas):
        command("git", "fetch", "--no-tags", f"https://github.com/{repo}.git", sha)
    command("git", "merge-base", "--is-ancestor", source_head, head)
    command("git", "merge-base", "--is-ancestor", pr["base"]["sha"], head)
    identity = validate_run_identity(
        run, pr, deployment, repo=repo, head=head,
        source_parents=git("show", "-s", "--format=%P", source_commit).split(),
        source_tree=git("rev-parse", f"{source_commit}^{{tree}}"),
        merge_tree=git("rev-parse", f"{pr['merge_commit_sha']}^{{tree}}"),
        current_tree=git("rev-parse", "HEAD^{tree}"),
    )
    validate_diff(command("git", "diff", "--binary", source_head, head), reviewed_diff)
    validate_eval_code(source_commit)
    return identity


def prepare(args: argparse.Namespace) -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)), "invalid repository")
    require(len(args.reason.strip()) >= 20, "review reason must have at least 20 characters")
    run, pr, artifact = authenticated_inputs(args.source_run_id, repo)
    archive = command("gh", "api", f"repos/{repo}/actions/artifacts/{int(artifact['id'])}/zip")
    raw = extract_reports(archive, artifact.get("digest", ""))
    browser, semantic, deployment = (json.loads(raw[name]) for name in REPORT_FILES)
    source = verify_checkout(run, pr, deployment, repo, args.reviewed_diff_sha256)
    ids = list(canonical_pr_case_ids())
    require(len(ids) == 8, "resume expects canonical eight-case PR suite")
    groups = partition(browser, semantic, load_corpus(), ids)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    (out / "source.zip").write_bytes(archive)
    for name, content in raw.items():
        (out / ("source-" + name)).write_bytes(content)
    plan = {
        "format_version": 1, "kind": "failed_only_pr_resume", "repository": repo,
        "source": source, "artifact": {"id": artifact["id"], "digest": artifact["digest"]},
        "current": {"run_id": os.environ["GITHUB_RUN_ID"], "head": git("rev-parse", "HEAD"),
                    "tree": git("rev-parse", "HEAD^{tree}")},
        "reviewed_diff_sha256": args.reviewed_diff_sha256, "reason": args.reason,
        "actor": os.environ["GITHUB_ACTOR"], "case_ids": ids, "partition": groups,
        "source_file_sha256": {name: sha256(value) for name, value in raw.items()},
        "old_backend_target": browser["backend_target"], "judge_call_limit": judge_limit(),
    }
    if groups["replay"]:
        write_json(out / "replay-browser-results.json", subset_browser_capture(
            browser, selected_case_ids=groups["replay"], expected_source_case_ids=ids,
            forbidden_operation_prefixes=(),
        ))
    write_json(out / "plan.json", plan)
    for mode, case_ids in groups.items():
        (out / f"{mode}-case-ids.txt").write_text(" ".join(case_ids) + "\n")


def validate_fresh_capture(fresh: dict, source: dict, proof: dict, plan: dict, target: str) -> None:
    current = plan["current"]
    require(proof.get("run_id") == current["run_id"] == os.environ.get("GITHUB_RUN_ID")
            and str(proof.get("run_attempt")) == os.environ.get("GITHUB_RUN_ATTEMPT")
            and proof.get("head") == current["head"] == git("rev-parse", "HEAD")
            and proof.get("tree") == current["tree"] == git("rev-parse", "HEAD^{tree}"),
            "fresh deployment identity mismatch")
    require(proof.get("candidate_url") == target == os.environ.get("CANDIDATE_URL")
            and target != source.get("backend_target") and fresh.get("backend_target") == target,
            "fresh deployment target mismatch")
    digest = proof.get("image_digest", "")
    require(isinstance(digest, str) and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", digest))
            and digest == os.environ.get("IMAGE_DIGEST"), "fresh deployment digest mismatch")
    started = proof.get("recorded_at_epoch")
    require(type(started) in (int, float) and started > 0, "invalid deployment timestamp")
    require(datetime.fromisoformat(fresh["started_at"].replace("Z", "+00:00")).timestamp() >= started,
            "capture predates current deployment")
    telemetry = fresh.get("application_telemetry")
    require(isinstance(telemetry, list) and bool(telemetry), "fresh telemetry missing")
    require(all(type(row.get("created_at_epoch")) in (int, float)
                and row["created_at_epoch"] >= started for row in telemetry), "stale fresh telemetry")
    for key in ("thread_id", "request_id"):
        old = {row[key] for row in source.get("application_telemetry", []) if row.get(key)}
        old.update(row[key] for row in source["results"] if row.get(key))
        new = {row[key] for row in telemetry if row.get(key)}
        new.update(row[key] for row in fresh["results"] if row.get(key))
        require(bool(new) and not old.intersection(new), f"fresh {key} reused or missing")


async def judge(args: argparse.Namespace) -> int:
    out = Path(args.output_dir)
    plan = json.loads((out / "plan.json").read_text())
    run, pr, artifact = authenticated_inputs(plan["source"]["run_id"], plan["repository"])
    require(artifact["id"] == plan["artifact"]["id"], "source artifact changed")
    raw = extract_reports((out / "source.zip").read_bytes(), artifact["digest"])
    browser, semantic, deployment = (json.loads(raw[name]) for name in REPORT_FILES)
    identity = verify_checkout(run, pr, deployment, plan["repository"], plan["reviewed_diff_sha256"])
    require(identity == plan["source"] and plan["current"]["head"] == git("rev-parse", "HEAD")
            and plan["current"]["run_id"] == os.environ["GITHUB_RUN_ID"], "plan identity mismatch")
    ids = list(canonical_pr_case_ids())
    groups = partition(browser, semantic, load_corpus(), ids)
    require(groups == plan["partition"] and ids == plan["case_ids"], "plan partition mismatch")
    require(plan["old_backend_target"] == browser["backend_target"]
            and plan["source_file_sha256"] == {name: sha256(value) for name, value in raw.items()},
            "source file lineage mismatch")
    fresh_path = Path(args.input).resolve()
    fresh = json.loads(fresh_path.read_text())
    proof_path = Path(args.deployment)
    proof = json.loads(proof_path.read_text())
    validate_fresh_capture(fresh, browser, proof, plan, args.target)
    require(fresh.get("format_version") == 1 and fresh.get("kind") == "browser_capture"
            and fresh.get("suite") == "diagnostic" and fresh.get("status") == "complete"
            and fresh.get("backend_target") == args.target
            and fresh.get("dashboard_smoke", {}).get("passed") is True, "fresh capture incomplete")
    corpus = load_corpus()
    require(fresh.get("corpus_sha256") == corpus_sha256()
            and fresh.get("corpus_version") == corpus.corpus_version
            and fresh.get("release_identity") == corpus.release_identity, "fresh corpus identity mismatch")
    fresh_results = ordered_items(fresh, "results", groups["fresh"])
    require(all(r.get("execution_state") == "completed" for r in fresh_results), "fresh result incomplete")
    states = ordered_items(fresh, "case_states", groups["fresh"])
    require(all(s.get("state") == "completed" for s in states), "fresh case incomplete")
    selected_judge = SemanticJudge()
    calibration = corpus.approval.calibration
    require(selected_judge.provider == calibration.judge_provider
            and selected_judge.model == calibration.judge_model
            and JUDGE_PROMPT_RELEASE == calibration.judge_release, "current judge identity mismatch")
    require(not (out / "judge-reservation.json").exists(), "judging already attempted")
    with (out / "judge-reservation.json").open("x") as reservation:
        json.dump({"run_id": os.environ["GITHUB_RUN_ID"], "judge_call_limit": judge_limit()}, reservation)
    remaining = judge_limit()
    reports = {}
    for mode in ("fresh", "replay"):
        if not groups[mode]:
            continue
        require(remaining > 0, "new judge-call budget exhausted")
        path = fresh_path
        if mode == "replay":
            path = (out / "replay-browser-results.json").resolve()
            write_json(path, subset_browser_capture(browser, selected_case_ids=groups[mode],
                       expected_source_case_ids=ids, forbidden_operation_prefixes=()))
        argv = ["--suite", "diagnostic", "--input", str(path), "--target",
                args.target if mode == "fresh" else plan["old_backend_target"],
                "--manual-review-policy", "blocking", "--judge-call-limit", str(remaining)]
        if mode == "replay":
            argv.append("--capture-replay")
        for case_id in groups[mode]:
            argv.extend(("--case", case_id))
        report, _ = await live_runner.evaluate(live_runner.build_parser().parse_args(argv))
        live_runner._write_outputs(out / f"{mode}-live-results.json", report)
        remaining -= report["budget"]["judge_calls"]
        reports[mode] = report
    # Recheck mutable PR state before reporting a combined approval.
    final_pr = api(f"repos/{plan['repository']}/pulls/{identity['pr']}")
    require(final_pr["head"]["sha"] == plan["current"]["head"]
            and final_pr["base"]["sha"] == identity["base"] and final_pr["state"] == "open",
            "PR changed while judging")
    evaluations = {row["id"]: row for row in semantic["evaluations"] if row["id"] in groups["carried"]}
    for mode, report in reports.items():
        ordered_items(report, "evaluations", groups[mode])
        for evaluation in report["evaluations"]:
            if evaluation["decision"] == "pass":
                capture_results = fresh["results"] if mode == "fresh" else browser["results"]
                result = next(row for row in capture_results if row["id"] == evaluation["id"])
                validate_judgments(evaluation, corpus.by_id[evaluation["id"]], corpus, result)
        evaluations.update({row["id"]: row for row in report["evaluations"]})
    require(set(evaluations) == set(ids), "combined coverage incomplete")
    passed = remaining >= 0 and all(row["decision"] == "pass" for row in evaluations.values())
    passed = passed and all(report["status"] == "pass" for report in reports.values())
    passed = passed and all(row.get("passed") is True for row in fresh["results"])
    combined = {
        "format_version": 1, "kind": "combined_pr_evidence", "status": "pass" if passed else "fail",
        "plan": plan, "new_judge_calls": judge_limit() - remaining,
        "fresh_capture_sha256": sha256(fresh_path.read_bytes()),
        "candidate_deployment": proof, "candidate_deployment_sha256": sha256(proof_path.read_bytes()),
        "new_cost_accounting": {mode: report["estimated_cost"] for mode, report in reports.items()},
        "new_phase_cost_details": {mode: report["cost_accounting"] for mode, report in reports.items()},
        "cases": [{"id": case_id, "mode": mode,
                   "application_source": plan["current"] if mode == "fresh" else identity,
                   "judgment_source": identity if mode == "carried" else plan["current"],
                   "judgments_sha256": sha256(json.dumps(evaluations[case_id]["judgments"], sort_keys=True).encode()),
                   "evaluation": evaluations[case_id]}
                  for case_id in ids for mode in groups if case_id in groups[mode]],
    }
    write_json(out / "combined-evidence.json", combined)
    return 0 if passed else 1


async def bounded_judge(args: argparse.Namespace) -> int:
    seconds = json.loads((ROOT / "ci/quality.json").read_text())["live"]["budgets"]["semantic_suite_timeout_seconds"]
    try:
        return await asyncio.wait_for(judge(args), timeout=seconds)
    except TimeoutError:
        write_json(Path(args.output_dir) / "resume-failure.json", {
            "status": "infrastructure", "reason": "semantic suite timeout",
            "timeout_seconds": seconds,
        })
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    prep = subs.add_parser("prepare")
    prep.add_argument("--source-run-id", required=True)
    prep.add_argument("--reviewed-diff-sha256", required=True)
    prep.add_argument("--reason", required=True)
    check = subs.add_parser("judge")
    check.add_argument("--input", required=True)
    check.add_argument("--target", required=True)
    check.add_argument("--deployment", required=True)
    for sub in (prep, check):
        sub.add_argument("--output-dir", default="artifacts/live-eval/resume")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    else:
        raise SystemExit(asyncio.run(bounded_judge(args)))


if __name__ == "__main__":
    main()
