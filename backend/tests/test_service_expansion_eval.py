"""Protected service expansion requires graph ownership and same-turn specialist calls."""

import copy
from types import SimpleNamespace

import pytest

from eval import live_runner
from eval.browser_runner import _service_expansion_failure
from eval.quality_corpus import ServiceExpansionExpectation, load_corpus


@pytest.fixture
def evidence():
    expectation = ServiceExpansionExpectation(
        target_service_labels=["Serving API", "Model release service"]
    )
    prior = {
        "title": "Serving",
        "assumptions": [],
        "sequence": [],
        "nodes": [
            {"id": "serving", "label": "Serving API", "type": "service"},
            {"id": "release", "label": "Model release service", "type": "service"},
        ],
        "edges": [],
        "groups": [],
    }
    expanded = copy.deepcopy(prior)
    expanded["nodes"] += [
        {
            "id": "request",
            "label": "Request handler",
            "type": "component",
            "technology": "Component",
            "parent_service_id": "serving",
        },
        {
            "id": "publish",
            "label": "Release publisher",
            "type": "component",
            "technology": "Component",
            "parent_service_id": "release",
        },
    ]
    result = {
        "id": "expansion",
        "thread_id": "thread",
        "events": [],
        "turns": [
            {
                "turn": 1,
                "request_id": "initial",
                "client_request_id": "client-initial",
                "graph": prior,
            },
            {
                "turn": 2,
                "request_id": "expand",
                "client_request_id": "client-expand",
                "graph": expanded,
            },
        ],
    }
    telemetry = [
        {
            "thread_id": "thread",
            "operation": operation,
            "model": "claude-opus-5-5",
            "status": "success",
            "fallback": False,
            "request_id": "expand",
            "client_request_id": "client-expand",
            "effort": "medium",
            "specialist_tool_version": "service_expansion_v1",
            "service_expansion_complexity": "high",
            "target_service_ids": ["serving", "release"],
        }
        for operation in ("staged_graph_components", "staged_graph_connections")
    ]
    original_case = load_corpus().by_id["graph-expansion"]
    case = original_case.model_copy(
        update={
            "steps": [
                original_case.steps[0],
                original_case.steps[-1].model_copy(
                    update={"service_expansion": expectation}
                ),
            ]
        }
    )
    return result, case, telemetry


def test_same_turn_specialist_and_owned_components_pass(evidence):
    result, case, telemetry = evidence
    assert live_runner._service_expansion_failures(result, case, telemetry) == []
    assert (
        _service_expansion_failure(
            result["turns"][0]["graph"],
            result["turns"][1]["graph"],
            case.steps[1].service_expansion,
        )
        is None
    )


@pytest.mark.parametrize("stage", [0, 1])
def test_missing_either_successful_specialist_stage_fails(evidence, stage):
    result, case, telemetry = evidence
    del telemetry[stage]
    assert any(
        "no successful same-turn" in failure
        for failure in live_runner._service_expansion_failures(result, case, telemetry)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "kimi-k3"),
        ("model", "claude-opus-5"),
        ("fallback", True),
        ("fallback", None),
    ],
)
def test_wrong_model_or_fallback_fails(evidence, field, value):
    result, case, telemetry = evidence
    telemetry[0][field] = value
    assert any(
        "mismatched" in failure
        for failure in live_runner._service_expansion_failures(result, case, telemetry)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("effort", "xhigh"),
        ("effort", None),
        ("specialist_tool_version", ""),
        ("service_expansion_complexity", "low"),
        ("target_service_ids", ["serving"]),
        ("target_service_ids", ["serving", "wrong"]),
        ("target_service_ids", ["serving", "release", "release"]),
    ],
)
def test_specialist_metadata_must_match_requested_scope(evidence, field, value):
    result, case, telemetry = evidence
    telemetry[0][field] = value
    assert any(
        "mismatched" in failure
        for failure in live_runner._service_expansion_failures(result, case, telemetry)
    )


@pytest.mark.parametrize(
    "change", ["other_thread", "other_turn", "conflicting_ids", "error"]
)
def test_other_thread_turn_or_failed_calls_cannot_supply_evidence(evidence, change):
    result, case, telemetry = evidence
    if change == "other_thread":
        telemetry[0]["thread_id"] = "other-thread"
    elif change == "other_turn":
        telemetry[0].update(request_id="initial", client_request_id="client-initial")
    elif change == "conflicting_ids":
        telemetry[0]["client_request_id"] = "other-client-request"
    else:
        telemetry[0]["status"] = "error"
    assert live_runner._service_expansion_failures(result, case, telemetry)


@pytest.mark.parametrize(
    "change",
    [
        "missing_ids",
        "missing_thread",
        "duplicate_turn",
        "duplicate_request",
        "missing_prior_graph",
        "ambiguous_parent",
    ],
)
def test_missing_or_ambiguous_turn_correlation_fails(evidence, change):
    result, case, telemetry = evidence
    if change == "missing_ids":
        result["turns"][1].pop("request_id")
        result["turns"][1].pop("client_request_id")
    elif change == "missing_thread":
        result.pop("thread_id")
    elif change == "duplicate_turn":
        result["turns"].append(copy.deepcopy(result["turns"][1]))
    elif change == "duplicate_request":
        result["turns"][0]["request_id"] = "expand"
    elif change == "missing_prior_graph":
        result["turns"][0].pop("graph")
    else:
        result["turns"][0]["graph"]["nodes"].append(
            {"id": "duplicate", "label": "Serving API", "type": "service"}
        )
    assert live_runner._service_expansion_failures(result, case, telemetry)


@pytest.mark.parametrize("id_field", ["request_id", "client_request_id"])
def test_either_unique_correlation_identifier_is_sufficient(evidence, id_field):
    result, case, telemetry = evidence
    other = "client_request_id" if id_field == "request_id" else "request_id"
    result["turns"][1].pop(other)
    for call in telemetry:
        call.pop(other)
    assert live_runner._service_expansion_failures(result, case, telemetry) == []


def test_cases_without_expansion_keep_existing_capture_behavior():
    assert (
        live_runner._service_expansion_failures({}, load_corpus().by_id["memory"], [])
        == []
    )


@pytest.mark.parametrize(
    "change",
    [
        "type",
        "wrong_parent",
        "missing_parent",
        "missing_selected_expansion",
        "too_many",
        "old_mutated",
    ],
)
def test_browser_expansion_rejects_invalid_component_ownership(evidence, change):
    result, case, _ = evidence
    prior, expanded = result["turns"][0]["graph"], result["turns"][1]["graph"]
    if change == "type":
        expanded["nodes"][2]["type"] = "service"
    elif change == "wrong_parent":
        expanded["nodes"][2]["parent_service_id"] = "wrong"
    elif change == "missing_parent":
        expanded["nodes"][2].pop("parent_service_id")
    elif change == "missing_selected_expansion":
        expanded["nodes"].pop()
    elif change == "too_many":
        expanded["nodes"] += [
            {**expanded["nodes"][2], "id": f"extra-{index}"} for index in range(3)
        ]
    else:
        expanded["nodes"][0]["label"] = "Changed prior service"
    assert (
        _service_expansion_failure(prior, expanded, case.steps[1].service_expansion)
        is not None
    )


def test_distinct_service_labels_cannot_share_prior_node_id(evidence):
    result, case, telemetry = evidence
    result["turns"][0]["graph"]["nodes"][1]["id"] = "serving"
    failures = live_runner._service_expansion_failures(result, case, telemetry)
    assert any("duplicate node IDs" in failure for failure in failures)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["live", "replay", "calibration_replay", "resume"])
async def test_specialist_failures_precede_semantic_judgment_and_resume(
    monkeypatch, evidence, mode
):
    result, case, telemetry = evidence
    result["id"] = case.id
    telemetry.pop()
    corpus = load_corpus().model_copy(update={"cases": [case]})
    monkeypatch.setattr(live_runner, "load_corpus", lambda **_kwargs: corpus)
    monkeypatch.setattr(
        live_runner,
        "_load_capture",
        lambda _args: {"results": [result], "application_telemetry": telemetry},
    )
    if mode == "calibration_replay":
        manifest = live_runner._manifest()
        manifest["live"]["suites"]["full"] = [case.id]
        monkeypatch.setattr(live_runner, "_manifest", lambda: manifest)
        monkeypatch.setattr(
            live_runner, "validate_calibration_capture", lambda *_args: None
        )
    resumed_failures = []

    def resume(*_args, **kwargs):
        resumed_failures.extend(kwargs["deterministic_failures_by_case"][case.id])
        return {
            case.id: {
                "id": case.id,
                "decision": "pass",
                "reason": "old pass",
                "judgments": [],
            }
        }

    if mode == "resume":
        monkeypatch.setattr(
            live_runner,
            "SemanticJudge",
            lambda: SimpleNamespace(model="mock", provider="mock"),
        )
        monkeypatch.setattr(live_runner, "_load_resume_evaluations", resume)
    else:

        def forbidden_judge():
            raise AssertionError(
                "specialist evidence failures must prevent judge calls"
            )

        monkeypatch.setattr(live_runner, "SemanticJudge", forbidden_judge)
    argv = [
        "--suite",
        "full" if mode == "calibration_replay" else "diagnostic",
        "--target",
        "https://candidate.example",
    ]
    if mode != "calibration_replay":
        argv += ["--case", case.id]
    if mode != "live":
        argv += ["--capture-replay"]
    if mode == "resume":
        argv += ["--resume-input", "prior-report.json"]
    report, exit_code = await live_runner.evaluate(
        live_runner.build_parser().parse_args(argv)
    )
    assert exit_code == 1
    assert report["evaluations"][0]["decision"] == "fail"
    assert report["evaluations"][0]["judgments"] == []
    assert report["budget"]["judge_calls"] == 0
    assert any(
        "staged_graph_connections" in failure
        for failure in report["evaluations"][0]["deterministic_failures"]
    )
    if mode == "resume":
        assert resumed_failures == report["evaluations"][0]["deterministic_failures"]


def test_protected_third_turn_uses_its_immediate_prior_graph(evidence):
    result, _, telemetry = evidence
    first_turn = copy.deepcopy(result["turns"][0])
    first_turn["graph"]["nodes"][0]["id"] = "old-serving-id"
    first_turn["request_id"] = "create"
    first_turn["client_request_id"] = "client-create"
    result["turns"][0].update(
        turn=2, request_id="prior-expansion", client_request_id="client-prior-expansion"
    )
    result["turns"][1]["turn"] = 3
    result["turns"].insert(0, first_turn)
    case = load_corpus().by_id["graph-expansion"]
    assert case.steps[2].service_expansion is not None
    assert live_runner._service_expansion_failures(result, case, telemetry) == []


@pytest.mark.asyncio
async def test_valid_replay_specialist_evidence_reaches_semantic_judgment(
    monkeypatch, evidence
):
    result, case, telemetry = evidence
    result["id"] = case.id
    corpus = load_corpus().model_copy(update={"cases": [case]})
    monkeypatch.setattr(live_runner, "load_corpus", lambda **_kwargs: corpus)
    monkeypatch.setattr(
        live_runner,
        "_load_capture",
        lambda _args: {"results": [result], "application_telemetry": telemetry},
    )
    monkeypatch.setattr(
        live_runner,
        "SemanticJudge",
        lambda: SimpleNamespace(provider="mock", model="mock"),
    )
    judged = []

    async def judge(*_args, **kwargs):
        kwargs["on_attempt"]()
        judged.append(True)
        return object()

    monkeypatch.setattr(live_runner, "judge_with_transport_retry", judge)
    monkeypatch.setattr(
        live_runner,
        "decide_semantic_gate",
        lambda *_args, **_kwargs: live_runner.GateDecision(
            "pass", "mock semantic pass"
        ),
    )
    monkeypatch.setattr(live_runner, "_result_to_json", lambda _result: {})
    args = live_runner.build_parser().parse_args(
        [
            "--suite",
            "diagnostic",
            "--case",
            case.id,
            "--target",
            "https://candidate.example",
            "--capture-replay",
        ]
    )
    report, exit_code = await live_runner.evaluate(args)
    assert exit_code == 0
    assert judged == [True]
    assert report["evaluations"][0]["deterministic_failures"] == []
    assert report["evaluations"][0]["decision"] == "pass"


def test_old_passing_resume_report_cannot_bypass_new_specialist_failure(
    tmp_path, evidence
):
    import json

    result, case, telemetry = evidence
    telemetry.pop()
    corpus = load_corpus().model_copy(update={"cases": [case]})
    report = {
        "kind": "live_gate",
        "execution_mode": "semantic_replay",
        "suite": "diagnostic",
        "target": "https://candidate.example",
        "corpus_version": corpus.corpus_version,
        "corpus_sha256": live_runner.corpus_sha256(),
        "release_identity": corpus.release_identity,
        "evaluations": [
            {
                "id": case.id,
                "decision": "pass",
                "deterministic_failures": [],
                "judgments": [{}],
            }
        ],
    }
    path = tmp_path / "prior-report.json"
    path.write_text(json.dumps(report))
    args = live_runner.build_parser().parse_args(
        [
            "--suite",
            "diagnostic",
            "--case",
            case.id,
            "--target",
            report["target"],
            "--capture-replay",
            "--resume-input",
            str(path),
        ]
    )
    with pytest.raises(
        RuntimeError, match="resume deterministic failures do not match"
    ):
        live_runner._load_resume_evaluations(
            args,
            corpus,
            SimpleNamespace(provider="mock", model="mock"),
            [case.id],
            deterministic_failures_by_case={
                case.id: live_runner._service_expansion_failures(
                    result, case, telemetry
                )
            },
        )


@pytest.mark.asyncio
async def test_actual_sanitized_endpoint_response_supplies_specialist_evidence(
    monkeypatch, evidence
):
    import api.internal_dashboard_route as dashboard

    result, case, flat_calls = evidence
    rows = []
    for call in flat_calls:
        rows.append(
            {
                "thread_id": call["thread_id"],
                "operation": call["operation"],
                "provider": "anthropic",
                "model": call["model"],
                "status": call["status"],
                "duration_ms": 100,
                "created_at_epoch": 1000.0,
                "used_fallback": call["fallback"],
                "metadata": {
                    **{
                        key: call[key]
                        for key in (
                            "request_id",
                            "client_request_id",
                            "effort",
                            "specialist_tool_version",
                            "service_expansion_complexity",
                            "target_service_ids",
                        )
                    },
                    "private_prompt": "private request text",
                    "private_token": "private credential",
                    "input_tokens": 10,
                    "output_tokens": 10,
                },
            }
        )
    monkeypatch.setattr(dashboard, "list_recent_llm_telemetry", lambda **_kwargs: rows)
    payload = await dashboard.dashboard_eval_telemetry(
        since_epoch=900, thread_id=["thread"], _user={}
    )
    assert live_runner._service_expansion_failures(result, case, payload["calls"]) == []
    for call in payload["calls"]:
        assert "metadata" not in call
        assert "private_prompt" not in call
        assert "private_token" not in call
        assert "private request text" not in str(call)
        assert "private credential" not in str(call)
        assert call["fallback"] is False
        assert call["target_service_ids"] == ["serving", "release"]


@pytest.mark.parametrize("graph_location", ["top_level", "turn"])
def test_semantic_judge_payload_retains_component_ownership(evidence, graph_location):
    result, _, _ = evidence
    expanded = result["turns"][1]["graph"]
    if graph_location == "top_level":
        capture = {"graph": expanded, "events": []}
    else:
        capture = {
            "turns": [{"turn": 1, "graph": expanded, "answer": "Expanded services"}],
            "events": [],
        }
    swapped = copy.deepcopy(capture)
    swapped_graph = (
        swapped["graph"]
        if graph_location == "top_level"
        else swapped["turns"][0]["graph"]
    )
    swapped_graph["nodes"][2]["parent_service_id"] = "release"
    swapped_graph["nodes"][3]["parent_service_id"] = "serving"
    original_payload = live_runner._judge_payload(capture)
    swapped_payload = live_runner._judge_payload(swapped)
    assert original_payload != swapped_payload
    judge_graph = (
        original_payload["graph"]
        if graph_location == "top_level"
        else original_payload["turns"][0]["graph"]
    )
    assert [node["parent_service_id"] for node in judge_graph["nodes"][2:]] == [
        "serving",
        "release",
    ]
