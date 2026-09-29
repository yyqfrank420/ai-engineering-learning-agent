import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from agent.nodes import staged_graph_generation as generation
from agent import staged_graph_contract as contract
from agent.stream_utils import StructuredLLMResponse


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.parametrize(
    "change,reason,path",
    [
        ({"source_index": True}, "endpoint_type", "edges.0.source_index"),
        ({"target_index": 9}, "endpoint_missing", "edges.0.target_index"),
        ({"target_index": 0}, "self_loop", "edges.0"),
        ({"label": None}, "label_type", "edges.0.label"),
        ({"label": " "}, "label_length", "edges.0.label"),
        ({"label": "x" * 1000}, "label_length", "edges.0.label"),
        ({"flow": 999}, "flow_enum", "edges.0.flow"),
        ({"sync": False}, "sync_enum", "edges.0.sync"),
    ],
)
def test_connection_rejection_diagnostics_do_not_change_repair_errors(
    change, reason, path
):
    wire = {
        "edges": [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "private label",
                "flow": 400,
                "sync": 500,
            }
            | change
        ]
    }
    with pytest.raises(generation.StagedGenerationError) as caught:
        generation._parse_connection_wire(
            json.dumps(wire),
            accepted_components=[{"index": 0}, {"index": 1}],
            edge_limit=5,
        )
    error = caught.value
    assert str(error) == error.code == "connection_wire_invalid"
    assert error.diagnostic_reason == reason
    assert error.diagnostic_path == path
    assert error.rejected_wire_fingerprint == generation._fingerprint(wire)
    assert "private label" not in json.dumps(
        (
            error.code,
            error.diagnostic_reason,
            error.diagnostic_path,
            error.rejected_wire_fingerprint,
        )
    )


@pytest.mark.parametrize(
    "wire,limit,reason,path,code",
    [
        ({"secret": "private label"}, 5, "wire_keys", "edges", "staged_generation_schema_invalid"),
        ({"edges": {}}, 5, "edges_type", "edges", "connection_wire_invalid"),
        ({"edges": [None]}, 0, "edges_count", "edges", "connection_wire_invalid"),
        ({"edges": [None]}, 5, "edge_type", "edges.0", "staged_generation_schema_invalid"),
        ({"edges": [{"secret": "private label"}]}, 5, "edge_keys", "edges.0", "staged_generation_schema_invalid"),
        ({"edges": [{"source_index": 0, "target_index": 1, "label": label,
                     "flow": 400, "sync": 500} for label in ("private label", "PRIVATE  LABEL")]},
         5, "duplicate_edge", "edges.1", "connection_wire_invalid"),
    ],
)
def test_connection_container_and_duplicate_diagnostics(
    wire, limit, reason, path, code
):
    with pytest.raises(generation.StagedGenerationError) as caught:
        generation._parse_connection_wire(
            json.dumps(wire),
            accepted_components=[{"index": 0}, {"index": 1}],
            edge_limit=limit,
        )
    error = caught.value
    assert str(error) == error.code == code
    assert (error.diagnostic_reason, error.diagnostic_path) == (reason, path)
    assert error.rejected_wire_fingerprint == generation._fingerprint(wire)
    assert "private label" not in json.dumps(
        (
            error.code,
            error.diagnostic_reason,
            error.diagnostic_path,
            error.rejected_wire_fingerprint,
        )
    )


@pytest.mark.parametrize(
    "path,value,reason",
    [
        ("title", None, "title_type"), ("title", " ", "title_length"),
        ("assumptions", None, "assumptions_type"),
        ("assumptions", ["a"] * 17, "assumptions_count"),
        ("assumptions.0", None, "assumption_type"),
        ("assumptions.0", " ", "assumption_length"),
        ("root_index", True, "root_type"), ("root_index", 9, "root_range"),
        ("capabilities", None, "capabilities_type"),
        ("capabilities", {}, "capabilities_keys"),
        ("capabilities.external_effects", 1, "capability_type"),
        ("components", None, "components_type"),
        ("components", [], "components_count"),
        ("components.0", None, "component_type"),
        ("components.0", {}, "component_keys"),
        ("components.0.label", None, "label_type"),
        ("components.0.label", " ", "label_length"),
        ("components.0.responsibility", None, "responsibility_type"),
        ("components.0.responsibility", " ", "responsibility_length"),
        ("components.0.group_label", None, "group_label_type"),
        ("components.0.group_label", " ", "group_label_length"),
        ("components.0.type", True, "component_type_enum"),
        ("components.0.group_kind", 999, "group_kind_enum"),
        ("components.0.primary_flow_member", 1, "primary_flow_type"),
        ("components.0.primary_flow_member", False, "root_not_primary"),
    ],
)
def test_component_rejection_diagnostics(path, value, reason):
    from agent import staged_graph_workflow as workflow

    wire = _component_wire()
    wire["assumptions"] = ["private source detail"]
    target = wire
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[int(part) if part.isdigit() else part]
    target[int(parts[-1]) if parts[-1].isdigit() else parts[-1]] = value
    with pytest.raises(generation.StagedGenerationError) as caught:
        generation._parse_component_wire(json.dumps(wire), component_limit=5)
    error = caught.value
    code = "staged_generation_schema_invalid" if reason in {
        "capabilities_type", "capabilities_keys", "component_type", "component_keys"
    } else "component_wire_invalid"
    expected_path = "root_index" if reason == "root_not_primary" else path
    assert str(error) == error.code == code
    assert error.diagnostic_reason == reason
    assert error.diagnostic_path == expected_path
    diagnostic = workflow._failure_diagnostic(
        error, stage="components", attempt=2, candidate=_component_wire(),
    )
    assert diagnostic["reason"] == reason
    assert diagnostic["path"] == expected_path
    assert diagnostic["candidate_fingerprint"] == generation._fingerprint(wire)
    assert diagnostic["candidate_fingerprint"] != generation._fingerprint(_component_wire())
    assert "private source detail" not in json.dumps(diagnostic)
    assert workflow._safe_finding(error, stage="components") == {
        "code": code, "path": expected_path, "rule": "contract_validation", "reason": reason,
    }


@pytest.mark.parametrize("case,reason", [
    ("keys", "component_wire_keys"), ("duplicate", "duplicate_component"),
    ("capacity", "components_count"),
])
def test_component_diagnostic_identity_and_capacity(case, reason):
    wire = _component_wire()
    if case == "keys":
        wire["private key"] = "private output"
    else:
        wire["components"].append(dict(wire["components"][0]))
    with pytest.raises(generation.StagedGenerationError) as caught:
        generation._parse_component_wire(json.dumps(wire), component_limit=1 if case == "capacity" else 5)
    error = caught.value
    assert error.diagnostic_reason == reason
    assert error.rejected_wire_fingerprint == generation._fingerprint(wire)
    assert error.diagnostic_path == ("components.1" if case == "duplicate" else "components")
    assert "private" not in json.dumps(vars(error))


@pytest.mark.parametrize(
    "connection_key", ["initial_connections", "corrected_connections"]
)
def test_retained_closed_loop_primary_reachability(connection_key):
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "staged_closed_loop_34661446928.json"
        ).read_text()
    )
    candidate = fixture["candidate"]
    wire = fixture[connection_key]
    accepted_components = [
        {
            "index": index,
            "is_root": index == candidate["root_index"],
            "primary_flow_member": component["primary_flow_member"],
        }
        for index, component in enumerate(candidate["components"])
    ]
    build = {
        **candidate,
        "request_id": "closed-loop-retained-transit",
        "maturity": "production",
        "source": "test",
        "stage": "connections",
        "components": [
            {
                **component,
                "model_index": index,
                "type": generation.NODE_TYPE_CODES[component["type"]],
                "group_kind": generation.GROUP_KIND_CODES[component["group_kind"]],
            }
            for index, component in enumerate(candidate["components"])
        ],
        "connections": [
            {
                "source_id": str(edge["source_index"]),
                "target_id": str(edge["target_index"]),
                "label": edge["label"],
                "flow": generation.FLOW_CODES[edge["flow"]],
                "sync": generation.SYNC_CODES[edge["sync"]],
            }
            for edge in wire["edges"]
        ],
    }
    assert (
        generation._parse_connection_wire(
            json.dumps(wire), accepted_components=accepted_components, edge_limit=30
        )
        == wire
    )
    graph = contract.project_graph_data(build)
    assert len(graph["nodes"]) == 11
    assert len(graph["edges"]) == (
        28 if connection_key == "initial_connections" else 25
    )
    assert [step["nodes"] for step in graph["sequence"]] == [
        ["n1"],
        ["n2"],
        ["n3", "n4", "n6", "n7"],
        ["n5", "n8"],
    ]
    assert [step["step"] for step in graph["sequence"]] == [1, 2, 3, 4]
    assert {node for step in graph["sequence"] for node in step["nodes"]} == {
        f"n{index}" for index in range(1, 9)
    }
    assert (
        contract.project_graph_data(contract.reconstruct_staged_graph_build(graph))
        == graph
    )


def test_retained_offline_evaluation_walkthrough_preserves_authored_graph():
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/staged_walkthrough_35640918048.json"
        ).read_text()
    )
    candidate, wire = fixture["candidate"], fixture["connections"]
    accepted_components = [
        {
            "index": index,
            "is_root": index == candidate["root_index"],
            "primary_flow_member": component["primary_flow_member"],
        }
        for index, component in enumerate(candidate["components"])
    ]
    assert (
        generation._parse_connection_wire(
            json.dumps(wire), accepted_components=accepted_components, edge_limit=180
        )
        == wire
    )
    build = contract.assign_server_ids(
        {
            **candidate,
            "request_id": "retained-offline-evaluation",
            "maturity": "production",
            "components": [
                {
                    **component,
                    "model_index": index,
                    "type": generation.NODE_TYPE_CODES[component["type"]],
                    "group_kind": generation.GROUP_KIND_CODES[component["group_kind"]],
                }
                for index, component in enumerate(candidate["components"])
            ],
            "connections": [
                {
                    "source_id": str(edge["source_index"]),
                    "target_id": str(edge["target_index"]),
                    "label": edge["label"],
                    "flow": generation.FLOW_CODES[edge["flow"]],
                    "sync": generation.SYNC_CODES[edge["sync"]],
                }
                for edge in wire["edges"]
            ],
        }
    )
    validated = contract.validate_staged_graph_build(build)
    assert validated["components"] == build["components"]
    assert validated["connections"] == build["connections"]
    assert contract.component_fingerprint(validated) == contract.component_fingerprint(
        build
    )
    assert contract.connection_fingerprint(
        validated
    ) == contract.connection_fingerprint(build)

    graph = contract.project_graph_data(validated)
    assert len(graph["nodes"]) == 18
    assert len(graph["edges"]) == 56
    assert graph["edges"][42]["source"] == "n12"
    assert graph["edges"][42]["target"] == "n13"
    assert graph["edges"][42]["flow"] == "feedback"
    assert graph["edges"][43]["source"] == "n13"
    assert graph["edges"][43]["target"] == "n15"
    assert graph["edges"][43]["flow"] == "feedback"
    assert {node for step in graph["sequence"] for node in step["nodes"]} == {
        component["server_id"]
        for component in build["components"]
        if component["primary_flow_member"]
    }
    reconstructed = contract.reconstruct_staged_graph_build(
        graph, {"capabilities": candidate["capabilities"]}
    )
    assert reconstructed["root_index"] == candidate["root_index"] == 0
    assert reconstructed["components"] == build["components"]
    assert reconstructed["connections"] == build["connections"]
    assert contract.component_fingerprint(
        reconstructed
    ) == contract.component_fingerprint(build)
    assert contract.connection_fingerprint(
        reconstructed
    ) == contract.connection_fingerprint(build)
    assert contract.project_graph_data(reconstructed) == graph


def _write_set() -> dict:
    return generation.create_write_set(component_limit=4, edge_limit=6)


def _component_wire() -> dict:
    return {
        "title": "Request processing",
        "assumptions": ["The caller supplies an authenticated request."],
        "root_index": 0,
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": True,
            "learning_or_release": False,
        },
        "components": [
            {
                "label": "Request gateway",
                "type": 101,
                "responsibility": "Accepts the request.",
                "parent_index": None,
                "group_label": "Runtime",
                "group_kind": 600,
                "primary_flow_member": True,
            }
        ],
    }


def _connection_wire() -> dict:
    return {
        "edges": [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "requests",
                "flow": 400,
                "sync": 500,
            }
        ]
    }


def _connection_exchanges() -> dict:
    return {
        "exchanges": [{**_connection_wire()["edges"][0], "response_label": "response"}]
    }


def _accepted_context() -> dict:
    return {
        "assumptions": ["The caller supplies an authenticated request."],
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": True,
            "learning_or_release": False,
        },
    }


def _architecture_context() -> str:
    return "Stable review frame:\n- goal: Serve authenticated requests."


def _accepted_components() -> list[dict]:
    return [
        {
            "index": 0,
            "id": "n1",
            "label": "Request gateway",
            "type": 104,
            "responsibility": "Accepts authenticated requests.",
        },
        {
            "index": 1,
            "id": "n2",
            "label": "Request service",
            "type": 101,
            "responsibility": "Processes accepted requests.",
        },
    ]


def _response(payload: dict) -> StructuredLLMResponse:
    if "components" in payload:
        payload = {"candidate": payload, "clarification_questions": []}
    return StructuredLLMResponse(
        text=json.dumps(payload),
        finish_reason="end_turn",
        input_tokens=10,
        output_tokens=10,
        provider="kimi",
        model="kimi-k3",
    )


def test_schemas_are_stage_specific_and_id_free():
    component_schema = generation.component_generation_schema(_write_set())
    connection_schema = generation.connection_generation_schema(_write_set())

    assert "edges" not in component_schema["properties"]
    assert (
        "id" not in component_schema["properties"]["components"]["items"]["properties"]
    )
    assert list(connection_schema["properties"]) == ["edges"]
    assert "components" not in connection_schema["properties"]


def test_schemas_require_nonblank_text_and_canonical_integer_codes():
    component = generation.component_generation_schema(_write_set())["properties"]
    component_record = component["components"]["items"]["properties"]
    connection_record = generation.connection_generation_schema(_write_set())[
        "properties"
    ]["edges"]["items"]["properties"]

    for field in ("title",):
        assert component[field]["minLength"] == 1
    for field in ("label", "responsibility", "group_label"):
        assert component_record[field]["minLength"] == 1
    assert component["assumptions"]["items"]["minLength"] == 1
    assert connection_record["label"]["minLength"] == 1
    assert component_record["type"]["enum"] == list(generation.NODE_TYPE_CODES)
    assert component_record["group_kind"]["enum"] == list(generation.GROUP_KIND_CODES)
    assert connection_record["flow"]["enum"] == list(generation.FLOW_CODES)
    assert connection_record["sync"]["enum"] == list(generation.SYNC_CODES)


def test_provider_schema_uses_authoritative_server_contract_limits():
    component = generation.component_generation_schema(_write_set())["properties"]
    component_record = component["components"]["items"]["properties"]
    connection_record = generation.connection_generation_schema(_write_set())[
        "properties"
    ]["edges"]["items"]["properties"]

    assert component["title"]["maxLength"] == contract.TITLE_MAX_CHARS
    assert (
        component["assumptions"]["items"]["maxLength"] == contract.ASSUMPTION_MAX_CHARS
    )
    assert component["components"]["minItems"] == 1
    assert component["root_index"]["maximum"] == 3
    assert component_record["label"]["maxLength"] == contract.COMPONENT_LABEL_MAX_CHARS
    assert (
        component_record["responsibility"]["maxLength"]
        == contract.COMPONENT_RESPONSIBILITY_MAX_CHARS
    )
    assert component_record["responsibility"]["description"] == (
        "Use short, complete clauses for this owner's work and applicable controls. "
        "Plan wording below 160 characters before emitting the string; "
        "never cut a clause to fit."
    )
    assert (
        component_record["group_label"]["maxLength"] == contract.GROUP_LABEL_MAX_CHARS
    )
    assert (
        connection_record["label"]["maxLength"] == contract.CONNECTION_LABEL_MAX_CHARS
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("wire", "error"),
    [
        (
            {
                **_component_wire(),
                "components": [{**_component_wire()["components"][0], "label": "  "}],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [{**_component_wire()["components"][0], "type": 999}],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [
                    {
                        **_component_wire()["components"][0],
                        "label": "x" * (contract.COMPONENT_LABEL_MAX_CHARS + 1),
                    }
                ],
            },
            "component_wire_invalid",
        ),
        ({**_component_wire(), "components": []}, "component_wire_invalid"),
        ({**_component_wire(), "root_index": 1}, "component_wire_invalid"),
        (
            {
                **_component_wire(),
                "components": [
                    _component_wire()["components"][0],
                    {
                        **_component_wire()["components"][0],
                        "label": " request gateway ",
                    },
                ],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "title": "x" * (contract.TITLE_MAX_CHARS + 1),
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "assumptions": ["x" * (contract.ASSUMPTION_MAX_CHARS + 1)],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [
                    {
                        **_component_wire()["components"][0],
                        "responsibility": "x"
                        * (contract.COMPONENT_RESPONSIBILITY_MAX_CHARS + 1),
                    }
                ],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [
                    {
                        **_component_wire()["components"][0],
                        "group_label": "x" * (contract.GROUP_LABEL_MAX_CHARS + 1),
                    }
                ],
            },
            "component_wire_invalid",
        ),
        (
            {
                **_component_wire(),
                "components": [
                    {
                        **_component_wire()["components"][0],
                        "primary_flow_member": False,
                    }
                ],
            },
            "component_wire_invalid",
        ),
    ],
)
async def test_component_generation_rejects_blank_text_and_unknown_codes(
    monkeypatch, wire, error
):
    async def fake_stream(**_kwargs):
        return _response(wire)

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)

    with pytest.raises(generation.StagedGenerationError, match=error):
        await generation.generate_component_candidate(
            request="Draw the request path",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["components", "connections"])
async def test_generation_prompt_uses_selected_prototype_maturity(monkeypatch, stage):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(
            _component_wire() if stage == "components" else _connection_exchanges()
        )

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    state = {"resolved_maturity": "prototype"}
    if stage == "components":
        await generation.generate_component_candidate(
            request="Design a production-grade request path.",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            state=state,
        )
    else:
        await generation.generate_connection_candidate(
            request="Design a production-grade request path.",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            accepted_components=_accepted_components(),
            accepted_context=_accepted_context(),
            state=state,
        )

    prompt = calls[0]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert prompt_input["resolved_maturity"] == "prototype"
    assert "Use prototype criteria only." in prompt
    assert "Do not add production-only controls" in prompt
    if stage == "components":
        assert prompt_input["architecture_context"] == _architecture_context()
        assert "shared evidence and review frame" in prompt
        assert "Avoid vague group labels such as Runtime, Data, or Operations" in prompt
        assert "an internal adapter to an external API remains internal" in prompt
        assert "Name each new group for the requested domain" in prompt
        assert "Never rename retained groups" in prompt
    else:
        assert prompt_input["architecture_context"] is None
        assert "its reverse response edge with the same flow and sync" in prompt
        assert "Pairing is independent of sync" in prompt
        assert "edge_limit counts expanded edges" in prompt
        assert "Each exchange represents an actual directed relationship" in prompt
        assert "For an actual request expecting a reply" in prompt
        assert "Use response_label=null only when no return contract is needed" in prompt
        assert "including one-way causal, adaptation, or lifecycle relationships" in prompt
        assert "manufacture reverse RPC edges between abstract topics" in prompt
        assert "live inference uses them without performing training" in prompt
        assert (
            "Route each supporting branch to a rejoin or observable outcome" in prompt
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.parametrize("attempt", [0, 1, 2])
async def test_connection_prompt_carries_authoritative_accepted_context(
    monkeypatch, maturity, attempt
):
    from agent.architecture_rubric import STAGED_PRODUCTION_REQUIREMENTS

    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_connection_exchanges())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    await generation.generate_connection_candidate(
        request="Connect accepted components",
        resolved_maturity=maturity,
        write_set=_write_set(),
        upstream_fingerprint="b" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
        attempt=attempt,
        prior_prompt_fingerprint="a" * 64 if attempt else None,
        prior_write_set_fingerprint=(
            generation._fingerprint(_write_set()) if attempt else None
        ),
        structural_findings=(
            [{"code": "invalid_contract", "path": "candidate", "rule": "contract_validation"}]
            if attempt else ()
        ),
        rejected_candidate=_connection_wire() if attempt else None,
        timeout_seconds=240,
        max_output_tokens=65536,
    )

    assert len(calls) == 1
    assert calls[0]["effort"] == ("high" if attempt else "low")
    assert calls[0]["timeout_seconds"] == 240
    assert calls[0]["max_output_tokens"] == 65536
    assert calls[0]["provider_attempt_limit"] == 1
    prompt = calls[0]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"] == "staged_connections_v74"
    )
    assert prompt_input["accepted_context"] == _accepted_context()
    assert prompt_input["rejected_candidate"] == (_connection_wire() if attempt else None)
    assert prompt_input["prior_prompt_fingerprint"] == ("a" * 64 if attempt else None)
    if attempt:
        assert prompt_input["findings"]["structural"] == [{
            "code": "invalid_contract", "path": "candidate",
            "rule": "contract_validation",
        }]
        assert "Repair each finding's full criterion throughout the candidate" in prompt
    assert "correction_component_record_indexes" not in prompt_input
    assert prompt_input["acceptance_criteria"]["runtime_completeness"] == (
        generation.staged_review_requirements("connections", maturity)["runtime_completeness"]
    )
    assert "refer to owners by accepted component names or unambiguous endpoint roles" in prompt
    assert "never numeric indexes, server IDs, or correction slots" in prompt
    assert "Labels are displayed verbatim; indexes belong only in structured fields" in prompt
    assert (
        "Preserve legitimate domain numbers and versions, exact user-required contract "
        "labels, and locked existing content" in prompt
    )
    assert "streaming_integrity" not in prompt_input["acceptance_criteria"]
    assert "For both topic or lifecycle maps and applied system designs" in prompt
    assert "primary_flow_member must be reachable outward from is_root" in prompt
    assert "Do not invent edges or change frozen primary membership" in prompt
    assert "including paths through non-primary supporting components" in prompt
    assert "Check each forward contract and actual reply" in prompt
    assert "accepted sender and recipient responsibilities" in prompt
    assert "including supporting and deployment exchanges" in prompt
    assert "Each data-returning alternative in a combined contract" in prompt
    assert "a write verdict is not read data" in prompt
    assert "Do not invent a reply to a one-way event" in prompt
    assert "return a processed artifact to a source without its declared use" in prompt
    if maturity == "production":
        assert prompt_input["authoring_guidance"] == {
            "streaming_integrity": STAGED_PRODUCTION_REQUIREMENTS["streaming_integrity"]
        }
        assert "applicable design guidance, not blocking acceptance criteria" in prompt
        assert "the owning producer of each normal or compensation proposal" in prompt
        assert "through validation and exact-scope approval" in prompt
        assert "Compare each declared producer, trigger and target scope" in prompt
        assert "same operation verb does not establish the same path" in prompt
        assert (
            "For each declared retrieval or recall path that consumes retrieved bytes"
            in prompt
        )
        assert "untrusted-data treatment by the consuming runtime before use" in prompt
        assert "every added or changed read or result-forwarding contract" in prompt
        assert "through retained downstream contracts to every actual consumer" in prompt
        assert "Normalized external status retains its external origin" in prompt
        assert "A compatible incoming contract may declare missing consuming-runtime handling" in prompt
        assert "when the frozen responsibility covers other byte classes" in prompt
        assert "exceptions under the supplied criteria; do not invent consumption" in prompt
        assert "duplicate treatment on pure transport hops" in prompt
        assert "model-consumed retrieval" not in prompt
        assert "treatment before model use" not in prompt
        assert (
            "verify requester identity, allowed scope and artifact validity before recall"
            in prompt
        )
        assert (
            "trace the exact approved action payload and stable operation identity"
            in prompt
        )
        assert "authorization verdict or incidental reachability alone" in prompt
        assert "declared metric pull with reply is a valid normal input" in prompt
        assert "do not add a redundant push or timer" in prompt
        assert "a different producer's compensation proposal" in prompt
        assert "including declared lifecycle transitions" in prompt
        assert "through validation and exact-scope approval" in prompt
        assert "including repair-introduced contracts" in prompt
        assert "A witness for one byte class does not cover other returned classes" in prompt
        assert "use only permitted slots or additions" in prompt
        assert (
            "A broad downstream response does not establish upstream submission"
            in prompt
        )
        assert "Each declared compensation producer needs an initiating" in prompt
        assert "check each behavior's initiation separately" in prompt
        assert "its normal input does not initiate rollback" in prompt
        assert "original or applied operation reference or recovery input" in prompt
        assert "Combined contracts may cover both behaviors" in prompt
        assert "explicit autonomous action needs no synthetic incoming edge" in prompt
        assert "When human review or human approval is requested or declared" in prompt
        assert (
            "the exact compensation proposal reaches that human decision boundary "
            "before approval"
        ) in prompt
        assert (
            "the outcome owner invokes it with stable identity and controls" in prompt
        )
        assert "a reply naming retry alone does not invoke it" in prompt
        assert (
            "Keep same-owner actions internal and autonomous pollers autonomous"
            in prompt
        )
        assert "curated hostile traces and offline evaluation before release" in prompt
        assert "each serving target's canary, distinct promotion and rollback" in prompt
        assert "do not invent extra components or capabilities" in prompt
    else:
        assert "authoring_guidance" not in prompt_input
        assert "check each effect owner separately" not in prompt
        assert "Each declared compensation producer needs an initiating" not in prompt
    assert prompt_input["accepted_components"] == [
        {
            "index": 0,
            "label": "Request gateway",
            "type": 104,
            "responsibility": "Accepts authenticated requests.",
            "primary_flow_member": False,
            "is_root": False,
        },
        {
            "index": 1,
            "label": "Request service",
            "type": 101,
            "responsibility": "Processes accepted requests.",
            "primary_flow_member": False,
            "is_root": False,
        },
    ]
    assert "Accepted component types are authoritative" in prompt
    assert (
        "Accepted responsibilities, assumptions, and capabilities are authoritative"
        in prompt
    )
    assert (
        "A durable telemetry/log sink completes observation-only responsibilities"
        in prompt
    )
    assert "connect its trigger to the execution path" in prompt
    assert "storing a recommendation does not execute that action" in prompt


@pytest.mark.parametrize(
    "accepted_context",
    [
        {},
        {"assumptions": [], "capabilities": {}},
        {
            "assumptions": [],
            "capabilities": {
                "external_effects": False,
                "retrieval_or_reuse": True,
                "learning_or_release": "false",
            },
        },
        {
            "assumptions": ["x" * (contract.ASSUMPTION_MAX_CHARS + 1)],
            "capabilities": _accepted_context()["capabilities"],
        },
    ],
)
def test_accepted_context_rejects_malformed_or_unbounded_values(accepted_context):
    with pytest.raises(
        generation.StagedGenerationError, match="invalid_accepted_context"
    ):
        generation._accepted_context(accepted_context)


def test_accepted_context_is_an_immutable_snapshot():
    context = _accepted_context()
    accepted = generation._accepted_context(context)
    context["assumptions"].append("A later mutation must not reach the prompt.")
    context["capabilities"]["external_effects"] = True

    assert accepted.prompt_value() == _accepted_context()


@pytest.mark.parametrize(
    "value",
    [
        "",
        " " * 20,
        "x" * (generation._MAX_ARCHITECTURE_CONTEXT_CHARS + 1),
    ],
)
def test_architecture_context_rejects_empty_or_unbounded_values(value):
    with pytest.raises(
        generation.StagedGenerationError, match="invalid_architecture_context"
    ):
        generation._accepted_architecture_context(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason_length", [900, 2_500])
async def test_correction_prompt_preserves_bounded_reason_and_record_indexes(
    monkeypatch,
    reason_length,
):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = _write_set()
    await generation.generate_component_candidate(
        request="Repair the request path.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="c" * 64,
        attempt=1,
        prior_prompt_fingerprint="d" * 64,
        prior_write_set_fingerprint=_fingerprint(
            json.dumps(write_set, sort_keys=True, separators=(",", ":"))
        ),
        gate_findings=[
            {
                "code": "domain_specificity",
                "path": "components",
                "rule": "semantic_gate",
                "reason": "x" * reason_length,
                "record_indexes": [0, 2],
            }
        ],
    )

    prompt = calls[0]["messages"][0]["content"]
    assert "Within changed contracts, preserve valid existing payload" in prompt
    assert "Repair the full applicable criterion" in prompt
    findings = json.loads(prompt.split("\nINPUT\n", 1)[1])["findings"]["gate"]
    assert findings == [
        {
            "code": "domain_specificity",
            "path": "components",
            "rule": "semantic_gate",
            "reason": "x" * min(reason_length, generation.MAX_REVIEW_REASON_CHARS),
            "record_indexes": [0, 2],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_seconds", [None, 129.875])
@pytest.mark.parametrize("attempt", [0, 1])
@pytest.mark.parametrize(
    "model", ["kimi-k3", "configured-builder-model", "claude-opus-5-5"]
)
async def test_component_generation_uses_configured_model_high_one_attempt_and_safe_telemetry(
    monkeypatch,
    timeout_seconds,
    model,
    attempt,
):
    monkeypatch.setattr(generation.settings, "graph_builder_model", model)
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    result = await generation.generate_component_candidate(
        request="Draw the request path",
        resolved_maturity="production",
        architecture_context=_architecture_context(),
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        state={"user_id": "user-1", "session_id": "thread-1", "is_production": True},
        timeout_seconds=timeout_seconds,
        max_output_tokens=65536,
        attempt=attempt,
        prior_prompt_fingerprint="b" * 64 if attempt else None,
        prior_write_set_fingerprint=(
            generation._fingerprint(_write_set()) if attempt else None
        ),
        structural_findings=(
            [{"code": "invalid_contract", "path": "candidate", "rule": "contract_validation"}]
            if attempt else ()
        ),
    )

    assert result["wire"] == _component_wire()
    assert len(result["prompt_fingerprint"]) == 64
    assert len(calls) == 1
    assert calls[0]["model"] == model
    assert calls[0]["effort"] == "high"
    assert calls[0]["max_output_tokens"] == 65536
    assert calls[0]["provider_attempt_limit"] == 1
    assert calls[0]["timeout_seconds"] == timeout_seconds
    assert calls[0]["telemetry"]["metadata"]["allocated_timeout_s"] == timeout_seconds
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"] == "staged_components_v72"
    )
    assert "request" not in calls[0]["telemetry"]["metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_code"),
    [
        (TimeoutError("deadline expired"), "staged_generation_timeout"),
        (RuntimeError("provider unavailable"), "staged_generation_unavailable"),
    ],
)
async def test_component_generation_distinguishes_timeout_from_provider_failure(
    monkeypatch,
    failure,
    error_code,
):
    async def fake_stream(**kwargs):
        raise failure

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(generation.StagedGenerationError, match=error_code) as raised:
        await generation.generate_component_candidate(
            request="Draw the request path",
            resolved_maturity="production",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
            timeout_seconds=129.875,
        )
    assert raised.value.__cause__ is failure


@pytest.mark.asyncio
async def test_component_generation_preserves_outer_cancellation(monkeypatch):
    started = asyncio.Event()
    closed = asyncio.Event()

    async def fake_stream(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    task = asyncio.create_task(
        generation.generate_component_candidate(
            request="Draw the request path",
            resolved_maturity="production",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
            timeout_seconds=129.875,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_connection_generation_rejects_unaccepted_endpoint_before_return(
    monkeypatch,
):
    async def fake_stream(**kwargs):
        return _response(
            {
                "exchanges": [
                    {
                        "source_index": 0,
                        "target_index": 9,
                        "label": "bad",
                        "flow": 400,
                        "sync": 500,
                        "response_label": "response",
                    }
                ]
            }
        )

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_invalid"
    ):
        await generation.generate_connection_candidate(
            request="Connect accepted components",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            accepted_components=[
                {**_accepted_components()[0], "id": "server-a"},
                {**_accepted_components()[1], "id": "server-b"},
            ],
            accepted_context=_accepted_context(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "edges",
    [
        [
            {
                "source_index": 0,
                "target_index": 0,
                "label": "loops",
                "flow": 400,
                "sync": 500,
            }
        ],
        [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "requests",
                "flow": 400,
                "sync": 500,
            },
            {
                "source_index": 0,
                "target_index": 1,
                "label": " REQUESTS ",
                "flow": 400,
                "sync": 500,
            },
        ],
        [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "x" * (contract.CONNECTION_LABEL_MAX_CHARS + 1),
                "flow": 400,
                "sync": 500,
            }
        ],
    ],
)
async def test_connection_generation_rejects_server_invalid_edge_identity(
    monkeypatch, edges
):
    async def fake_stream(**_kwargs):
        return _response(
            {"exchanges": [{**edge, "response_label": "response"} for edge in edges]}
        )

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_invalid"
    ):
        await generation.generate_connection_candidate(
            request="Connect accepted components",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            accepted_components=[
                {**_accepted_components()[0], "id": "server-a"},
                {**_accepted_components()[1], "id": "server-b"},
            ],
            accepted_context=_accepted_context(),
        )


@pytest.mark.asyncio
async def test_connection_generation_requires_every_primary_member_from_root(monkeypatch):
    from agent import staged_graph_workflow as workflow

    calls = []
    accepted = [
        {**component, "primary_flow_member": True, "is_root": index == 0}
        for index, component in enumerate(_accepted_components())
    ]
    rejected = {"edges": []}

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        payload = {"exchanges": []} if len(calls) == 1 else _connection_exchanges()
        return _response(payload)

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(generation.StagedGenerationError) as caught:
        await generation.generate_connection_candidate(
            request="Compare the subject mechanisms",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="b" * 64,
            accepted_components=accepted,
            accepted_context=_accepted_context(),
        )
    error = caught.value
    assert str(error) == error.code == "connection_wire_unreachable"
    assert (error.diagnostic_reason, error.diagnostic_path) == (
        "primary_flow_unreachable",
        "edges",
    )
    assert error.rejected_wire_fingerprint == generation._fingerprint(rejected)
    finding = workflow._safe_finding(error, stage="connections")
    assert finding == {
        "code": "connection_wire_unreachable",
        "path": "edges",
        "rule": "contract_validation",
        "reason": "primary_flow_unreachable",
    }
    result = await generation.generate_connection_candidate(
        request="Compare the subject mechanisms",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="b" * 64,
        accepted_components=accepted,
        accepted_context=_accepted_context(),
        attempt=1,
        prior_prompt_fingerprint=error.prompt_fingerprint,
        prior_write_set_fingerprint=generation._fingerprint(_write_set()),
        structural_findings=[finding],
        rejected_candidate=None,
        recovery_mode=True,
    )
    prompt = calls[1]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert prompt_input["recovery_mode"] is True
    assert prompt_input["rejected_candidate"] is None
    assert prompt_input["base"] is None
    assert prompt_input["findings"]["structural"] == [finding]
    assert "Every accepted primary member needs a truthful outward directed path" in prompt
    assert "from the accepted is_root" in prompt
    assert "Preserve accepted responsibilities, root, and primary membership" in prompt
    assert "Use non-primary transit when supported" in prompt
    assert "do not manufacture reverse RPC edges" in prompt
    expected_wire, expected_exchanges = generation._parse_connection_response(
        json.dumps(_connection_exchanges()),
        accepted_components=accepted,
        edge_limit=_write_set()["edge_limit"],
    )
    assert result["wire"] == expected_wire
    assert result["connection_exchanges"] == expected_exchanges


@pytest.mark.asyncio
async def test_corrected_attempt_carries_sanitized_findings_and_same_write_set(
    monkeypatch,
):
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = _write_set()
    rejected_candidate = _component_wire()
    result = await generation.generate_component_candidate(
        request="Draw the request path",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="c" * 64,
        attempt=1,
        prior_prompt_fingerprint="d" * 64,
        prior_write_set_fingerprint=_fingerprint(
            json.dumps(write_set, sort_keys=True, separators=(",", ":"))
        ),
        structural_findings=[
            {"code": "edge_missing", "path": "components.0", "rule": "required"},
            {"code": "ignore", "path": "<instructions>", "rule": "bad text"},
        ],
        gate_findings=[{"code": "gate_failed", "path": "gate.0", "rule": "approved"}],
        rejected_candidate=rejected_candidate,
    )

    prompt = calls[0]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert "edge_missing" in prompt
    assert "<instructions>" not in prompt
    assert prompt_input["rejected_candidate"] == rejected_candidate
    assert "complete candidate that failed review" in prompt
    assert result["prompt_fingerprint"] != "d" * 64


@pytest.mark.asyncio
async def test_correction_rejects_changed_write_set_or_identical_prompt(monkeypatch):
    async def fake_stream(**kwargs):
        return _response(_component_wire())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(
        generation.StagedGenerationError, match="correction_write_set_changed"
    ):
        await generation.generate_component_candidate(
            request="request",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="e" * 64,
            attempt=1,
            prior_prompt_fingerprint="f" * 64,
            prior_write_set_fingerprint="0" * 64,
            structural_findings=[{"code": "failed", "path": "wire", "rule": "shape"}],
        )

    write_set = _write_set()
    monkeypatch.setattr(generation, "_fingerprint", lambda _value: "f" * 64)
    with pytest.raises(
        generation.StagedGenerationError, match="identical_correction_prompt"
    ):
        await generation.generate_component_candidate(
            request="request",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=write_set,
            upstream_fingerprint="e" * 64,
            attempt=1,
            prior_prompt_fingerprint="f" * 64,
            prior_write_set_fingerprint="f" * 64,
            structural_findings=[{"code": "failed", "path": "wire", "rule": "shape"}],
        )


def _edit_base() -> dict:
    wire = _component_wire()
    return {
        **wire,
        "components": [
            {
                **wire["components"][0],
                "server_id": "n1",
                "model_index": 0,
                "type": "service",
                "group_kind": "runtime",
            },
            {
                **wire["components"][0],
                "label": "Trace sink",
                "server_id": "n2",
                "model_index": 1,
                "type": "datastore",
                "group_kind": "runtime",
                "primary_flow_member": False,
            },
        ],
    }


def _permissions(**changes) -> dict:
    return {
        "editable_node_fields": {},
        "removable_node_ids": [],
        "allowed_new_node_count": 0,
        "editable_edges": [],
        "editable_edge_fields": {},
        "removable_edge_ids": [],
        "allowed_new_edge_count": 0,
        "added_edge_anchor_node_ids": [],
        "connection_addition_obligations": [],
        "editable_composition_fields": [],
        **changes,
    }


async def _generate_edit(monkeypatch, delta, permissions, **changes):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(delta)

    monkeypatch.setattr(generation, "_run_generation", generate)
    result = await generation.generate_component_candidate(
        request="Apply the scoped change.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=_write_set(),
        upstream_fingerprint=_fingerprint("edit base"),
        base_components=_edit_base(),
        edit_permissions=permissions,
        **changes,
    )
    return result, calls


@pytest.mark.asyncio
async def test_component_edit_adds_only_delta_and_preserves_locked_base(monkeypatch):
    addition = {**_component_wire()["components"][0], "label": "Audit service"}
    result, calls = await _generate_edit(
        monkeypatch,
        {
            "additions": [addition],
            "updates": {},
            "capabilities": _accepted_context()["capabilities"],
        },
        _permissions(allowed_new_node_count=1),
    )
    assert [row["label"] for row in result["wire"]["components"]] == [
        "Request gateway",
        "Trace sink",
        "Audit service",
    ]
    assert result["wire"]["title"] == _edit_base()["title"]
    properties = calls[0]["schema"]["properties"]
    assert set(properties) == {"additions", "updates", "capabilities"}
    assert (
        properties["additions"]["minItems"] == properties["additions"]["maxItems"] == 1
    )
    assert "acceptance_criteria" in calls[0]["prompt"]
    assert "server_id" not in calls[0]["prompt"]


@pytest.mark.asyncio
async def test_component_edit_updates_exact_fields_and_proposes_capabilities(
    monkeypatch,
):
    capabilities = {**_accepted_context()["capabilities"], "external_effects": True}
    result, calls = await _generate_edit(
        monkeypatch,
        {
            "additions": [],
            "updates": {
                "slot_0": {
                    "label": "Ingress",
                    "responsibility": "Accept approved requests.",
                }
            },
            "capabilities": capabilities,
            "title": "New title",
        },
        _permissions(
            editable_node_fields={"n1": ["label", "description"]},
            editable_composition_fields=["title"],
        ),
    )
    assert result["wire"]["components"][0]["label"] == "Ingress"
    assert result["wire"]["components"][1]["label"] == "Trace sink"
    assert result["wire"]["capabilities"] == capabilities
    assert result["wire"]["title"] == "New title"
    assert set(
        calls[0]["schema"]["properties"]["updates"]["properties"]["slot_0"][
            "properties"
        ]
    ) == {"label", "responsibility"}


@pytest.mark.asyncio
async def test_component_edit_removes_server_selected_records(monkeypatch):
    result, _ = await _generate_edit(
        monkeypatch,
        {
            "additions": [],
            "updates": {},
            "capabilities": _accepted_context()["capabilities"],
        },
        _permissions(removable_node_ids=["n2"]),
    )
    assert len(result["wire"]["components"]) == 1
    assert result["wire"]["root_index"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"updates": {"slot_1": {"label": "Other"}}},
        {"updates": {"slot_0": {"label": "Ingress", "type": 102}}},
        {"updates": {"slot_0": {}}},
        {"additions": [_component_wire()["components"][0]]},
        {"title": "Unauthorized title"},
        {"components": []},
    ],
)
async def test_component_delta_rejects_unknown_slots_fields_missing_updates_and_counts(
    monkeypatch, change
):
    delta = {
        "additions": [],
        "updates": {"slot_0": {"label": "Ingress"}},
        "capabilities": _accepted_context()["capabilities"],
        **change,
    }
    with pytest.raises(generation.StagedGenerationError):
        await _generate_edit(
            monkeypatch, delta, _permissions(editable_node_fields={"n1": ["label"]})
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "permissions",
    [
        _permissions(editable_node_fields={"n1": ["technology"]}),
        _permissions(editable_node_fields={"missing": ["label"]}),
        _permissions(editable_composition_fields=["sequence"]),
        _permissions(removable_node_ids=["n1"]),
    ],
)
async def test_component_delta_rejects_unrepresentable_authority_before_provider(
    monkeypatch, permissions
):
    async def unexpected(**kwargs):
        pytest.fail("Invalid edit authority reached the provider")

    monkeypatch.setattr(generation, "_run_generation", unexpected)
    with pytest.raises(generation.StagedGenerationError):
        await generation.generate_component_candidate(
            request="edit",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint=_fingerprint("base"),
            base_components=_edit_base(),
            edit_permissions=permissions,
        )


@pytest.mark.asyncio
async def test_component_correction_projects_rejected_wire_back_to_delta(monkeypatch):
    permissions = _permissions(editable_node_fields={"n1": ["label"]})
    initial = {
        "additions": [],
        "updates": {"slot_0": {"label": "Ingress"}},
        "capabilities": _accepted_context()["capabilities"],
    }
    first, _ = await _generate_edit(monkeypatch, initial, permissions)
    corrected = {**initial, "updates": {"slot_0": {"label": "Request ingress"}}}
    result, calls = await _generate_edit(
        monkeypatch,
        corrected,
        permissions,
        attempt=1,
        prior_prompt_fingerprint=first["prompt_fingerprint"],
        prior_write_set_fingerprint=generation._fingerprint(_write_set()),
        structural_findings=[
            {"code": "label_unclear", "path": "components.0", "rule": "label_unclear"}
        ],
        rejected_candidate=first["wire"],
    )
    prompt_input = json.loads(calls[0]["prompt"].split("\nINPUT\n")[1])
    assert prompt_input["rejected_candidate"] == initial
    assert result["wire"]["components"][0]["label"] == "Request ingress"
    assert "Trace sink" not in json.dumps(prompt_input["rejected_candidate"])
    prompt = calls[0]["prompt"]
    assert (
        "Compare the original and proposed clauses of each edited responsibility. "
        "Retain valid executable work and control ownership. Consuming an operation's "
        "output does not assign ownership of that operation. Apply changes required "
        "by a finding within permitted fields. Assess meaning without requiring exact verbs or labels."
        in prompt
    )
    assert "Within changed contracts, preserve valid existing payload" in prompt
    assert "provenance, scope, conditions, and alternate outcomes" in prompt
    assert (
        "After adding or updating a component responsibility, reassess capabilities"
        in prompt
    )
    assert "instead of retaining prior flags by default" in prompt
    assert "do not expand the write set or supplied schema permissions" in prompt
    assert set(
        calls[0]["schema"]["properties"]["updates"]["properties"]["slot_0"][
            "properties"
        ]
    ) == {"label"}
    assert result["wire"]["components"][1:] == first["wire"]["components"][1:]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["edit", "extension"])
async def test_connection_delta_matches_original_selector_after_incident_edge_removal(
    monkeypatch, kind,
):
    base = _connection_wire()["edges"]
    permissions = _permissions(
        kind=kind,
        editable_edges=[
            {"edge_id": "edge_1", "source": "removed", "target": "n1", "label": "old"},
            {"edge_id": "edge_2", "source": "n1", "target": "n2", "label": "requests"},
        ],
        removable_edge_ids=["edge_1"],
        editable_edge_fields={"edge_1": [], "edge_2": ["label", "sync"]},
        allowed_new_edge_count=1,
        added_edge_anchor_node_ids=["n1", "n2"],
        connection_addition_obligations=[
            {"source": "n2", "target": "n1", "required_contract": "response"}
        ],
    )
    addition = {**base[0], "source_index": 1, "target_index": 0, "label": "response"}
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "updates": {"slot_0": {"label": "dispatch", "sync": 501}},
                "additions": [addition],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    result = await generation.generate_connection_candidate(
        request="Update the retained request and add a response.",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint=_fingerprint("base"),
        accepted_components=_accepted_components(),
        saved_component_ids=["n1", "n2"],
        accepted_context=_accepted_context(),
        base_connections=base,
        edit_permissions=permissions,
    )
    assert result["wire"]["edges"] == [
        {**base[0], "label": "dispatch", "sync": 501},
        addition,
    ]
    assert "connection_exchanges" not in result
    prompt_input = json.loads(calls[0]["prompt"].split("\nINPUT\n", 1)[1])
    assert prompt_input["acceptance_criteria"]["runtime_completeness"] == (
        generation.staged_review_requirements("connections", "prototype")["runtime_completeness"]
    )
    assert "Propose canonical edges in the delta" in calls[0]["prompt"]
    assert "Propose exchanges only" not in calls[0]["prompt"]
    assert (
        "Do not label a request edge as if it carries the returned payload"
        in calls[0]["prompt"]
    )
    assert "Check each forward contract and actual reply" in calls[0]["prompt"]
    assert set(
        calls[0]["schema"]["properties"]["additions"]["items"]["properties"]
    ) == {"source_index", "target_index", "label", "flow", "sync"}
    assert "edge_2" not in calls[0]["prompt"]
    assert base == _connection_wire()["edges"]


def test_connection_delta_removal_is_server_owned_and_unknown_selectors_fail():
    base = _connection_wire()["edges"]
    permissions = _permissions(
        editable_edges=[
            {"edge_id": "edge_2", "source": "n1", "target": "n2", "label": "requests"}
        ],
        removable_edge_ids=["edge_2"],
    )
    delta = generation._connection_edit_delta(
        base,
        permissions,
        generation.connection_generation_schema(_write_set()),
        _accepted_components(),
    )
    assert delta.assemble('{"updates":{},"additions":[]}') == {"edges": []}
    with pytest.raises(generation.StagedGenerationError, match="selector"):
        generation._connection_edit_delta(
            base,
            {**permissions, "removable_edge_ids": ["missing"]},
            generation.connection_generation_schema(_write_set()),
            _accepted_components(),
        )


def test_delta_rejects_duplicate_json_slots():
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_json('{"updates":{"slot_0":{},"slot_0":{}},"additions":[]}')


def test_component_delta_removal_reindexes_root_without_reordering_retained_records():
    base = _edit_base()
    base["root_index"] = 1
    base["components"][1]["primary_flow_member"] = True
    delta = generation._component_edit_delta(
        base,
        _permissions(removable_node_ids=["n1"]),
        generation.component_generation_schema(_write_set()),
    )
    wire = delta.assemble(
        json.dumps(
            {"additions": [], "updates": {}, "capabilities": base["capabilities"]}
        )
    )
    assert wire["root_index"] == 0
    assert wire["components"][0]["label"] == "Trace sink"
    assert base["root_index"] == 1
    assert len(base["components"]) == 2


def test_scoped_component_edit_rejects_null_update_and_keeps_original_schema_identity():
    delta = generation._component_edit_delta(
        _edit_base(),
        _permissions(editable_node_fields={"n1": ["label"]}),
        generation.component_generation_schema(_write_set()),
    )
    response = delta.extract(delta.base)
    assert response["updates"]["slot_0"] == {"label": "Request gateway"}
    assert generation._generation_schema_version("components", delta.schema) == (
        "staged_components_delta_v7"
    )
    response["updates"]["slot_0"] = None
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps(response))


@pytest.mark.parametrize(
    "change",
    [
        {"updates": {"slot_1": {"label": "unauthorized"}}},
        {"updates": {"slot_0": {"label": "dispatch", "flow": 401}}},
        {"updates": {}},
        {"updates": {"slot_0": None}},
        {"additions": _connection_wire()["edges"]},
    ],
)
def test_connection_delta_rejects_fields_selectors_missing_updates_and_counts(change):
    permissions = _permissions(
        editable_edges=[
            {"edge_id": "edge_1", "source": "n1", "target": "n2", "label": "requests"}
        ],
        editable_edge_fields={"edge_1": ["label"]},
    )
    delta = generation._connection_edit_delta(
        _connection_wire()["edges"],
        permissions,
        generation.connection_generation_schema(_write_set()),
        _accepted_components(),
    )
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(
            json.dumps(
                {
                    "updates": {"slot_0": {"label": "dispatch"}},
                    "additions": [],
                    **change,
                }
            )
        )


@pytest.mark.parametrize("invalid_code", [101.0, [], {}, True])
def test_scalar_parser_rejects_invalid_code_types(invalid_code):
    wire = _component_wire()
    wire["components"][0]["type"] = invalid_code
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ):
        generation._parse_component_wire(json.dumps(wire), component_limit=4)


@pytest.mark.asyncio
async def test_recorded_expansion_preserves_attachment_plan_through_both_stages_and_correction(
    monkeypatch,
):
    from pathlib import Path
    from agent.nodes.graph_worker import _user_edit_scope

    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "staged_expansion_34649724600.json"
        ).read_text()
    )
    base = contract.reconstruct_staged_graph_build(fixture["base_graph"])
    _, permissions = _user_edit_scope(
        fixture["request"], fixture["base_graph"], resolved_complexity="prototype"
    )
    assert permissions["added_edge_anchor_node_ids"] == ["n6"]
    from agent.staged_graph_workflow import _connection_prompt_base

    baseline_connections = _connection_prompt_base(base)
    calls = []
    recorded = fixture["rejected_addition"]
    addition = {
        "label": recorded["label"],
        "type": 101,
        "responsibility": recorded["description"],
        "group_label": "Monitoring",
        "group_kind": 602,
        "primary_flow_member": False,
    }

    async def generate(**kwargs):
        calls.append(kwargs)
        if kwargs["stage"] == "components":
            return json.dumps(
                {
                    "additions": [addition],
                    "updates": {},
                    "capabilities": base["capabilities"],
                }
            )
        return json.dumps(
            {
                "additions": [
                    {
                        "source_index": 5,
                        "target_index": 8,
                        "label": "monitoring event",
                        "flow": 400,
                        "sync": 501,
                    }
                ],
                "updates": {},
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    write_set = generation.exact_edit_write_set(
        component_ids=[f"component_{i}" for i in range(9)],
        edge_ids=[f"edge_{i}" for i in range(15)],
    )
    kwargs = dict(
        request=fixture["request"],
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        base_components=base,
        baseline_connections=baseline_connections,
        edit_permissions=permissions,
    )
    first = await generation.generate_component_candidate(**kwargs)
    await generation.generate_component_candidate(
        **kwargs,
        attempt=1,
        prior_prompt_fingerprint=first["prompt_fingerprint"],
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        rejected_candidate=first["wire"],
        gate_findings=[
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "mece_scope",
                "reason": "Responsibility requires an unauthorized data-source connection.",
                "record_indexes": [8],
            }
        ],
    )
    prompts = [json.loads(call["prompt"].split("\nINPUT\n")[1]) for call in calls]
    expected = {
        "mode": "attachment",
        "minimum_addition_count": 1,
        "maximum_addition_count": 2,
        "anchor_component_indexes": [5],
        "component_addition_count": 1,
        "enforce_added_edge_contract_label": False,
        "obligations": [
            {
                "source": {"component_index": 5},
                "target": {"addition_index": 0},
                "required_contract": permissions["connection_addition_obligations"][0][
                    "required_contract"
                ],
            }
        ],
    }
    assert (
        prompts[0]["connection_addition_plan"]
        == prompts[1]["connection_addition_plan"]
        == expected
    )
    assert prompts[0]["base"]["components"][5]["label"] == "Metrics Monitor"
    assert (
        prompts[0]["baseline_connections"]
        == prompts[1]["baseline_connections"]
        == baseline_connections
    )
    for prompt in prompts:
        for row, edge in zip(prompt["baseline_connections"], base["connections"], strict=True):
            for endpoint in ("source", "target"):
                index = row[f"{endpoint}_index"]
                assert base["components"][index]["server_id"] == edge[f"{endpoint}_id"]
                assert prompt["base"]["components"][index]["label"] == base["components"][index]["label"]
            assert row["label"] == edge["label"]
            assert generation.FLOW_CODES[row["flow"]] == edge["flow"]
            assert generation.SYNC_CODES[row["sync"]] == edge["sync"]
    assert prompts[1]["rejected_candidate"]["additions"] == [addition]
    assert (
        "without requiring another data source, dependency, or extra edge"
        in calls[0]["prompt"]
    )
    for call in calls[:2]:
        assert "required inputs and outcomes must be achievable" in call["prompt"]
        assert "permitted endpoints, counts, and directions" in call["prompt"]
        assert "explicitly delegate an outcome back through its attachment anchor" in call["prompt"]
        assert "anchor's unchanged existing contracts supplied in baseline_connections" in call["prompt"]
        assert "Preserve their exact payload and control meaning" in call["prompt"]
        assert "an evaluation-feedback contract does not by itself establish a rollback invocation" in call["prompt"]
        assert "do not invent connections outside the permitted endpoints" in call["prompt"]
        assert "A truthful one-way attachment or sink is sufficient" in call["prompt"]
    assert "n6" not in json.dumps(expected)
    assert "When false, required_contract describes intent" in calls[0]["prompt"]
    assert (
        "Never copy edit instructions into a runtime connection label"
        in calls[0]["prompt"]
    )

    accepted = [
        {"id": f"n{index + 1}", "index": index, **row}
        for index, row in enumerate(first["wire"]["components"])
    ]
    await generation.generate_connection_candidate(
        request=fixture["request"],
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="b" * 64,
        accepted_components=accepted,
        saved_component_ids=[row["server_id"] for row in base["components"]],
        accepted_context={key: base[key] for key in ("assumptions", "capabilities")},
        base_connections=[],
        edit_permissions=permissions,
    )
    connection_prompt = json.loads(calls[-1]["prompt"].split("\nINPUT\n")[1])
    assert connection_prompt["connection_addition_plan"] == {
        **expected,
        "accepted_addition_indexes": [8],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"added_edge_anchor_node_ids": ["unknown"]},
        {"added_edge_anchor_node_ids": ["n1", "n1"]},
        {"allowed_new_edge_count": 2},
        {"enforce_added_edge_contract_label": "false"},
        {"allowed_new_node_count": 0},
        {"removable_node_ids": ["n1"]},
        {
            "connection_addition_obligations": [
                {"source": "n1", "target": "$new_node_2", "required_contract": "event"}
            ]
        },
        {
            "connection_addition_obligations": [
                {"source": "n2", "target": "$new_node_1", "required_contract": "event"}
            ]
        },
        {
            "connection_addition_obligations": [
                {
                    "source": "n1",
                    "target": "$new_node_1",
                    "required_contract": "event",
                    "extra": True,
                }
            ]
        },
        {
            "connection_addition_obligations": [
                {
                    "source": "n1",
                    "target": "$new_node_1",
                    "required_contract": "x"
                    * (contract.CONNECTION_LABEL_MAX_CHARS + 1),
                }
            ]
        },
    ],
)
@pytest.mark.asyncio
async def test_invalid_connection_planning_authority_is_rejected_before_component_provider(
    monkeypatch, change
):
    permissions = _permissions(
        allowed_new_node_count=1,
        allowed_new_edge_count=1,
        added_edge_anchor_node_ids=["n1"],
        connection_addition_obligations=[
            {"source": "n1", "target": "$new_node_1", "required_contract": "event"}
        ],
    )
    permissions.update(change)

    async def unexpected(**kwargs):
        pytest.fail("Invalid connection authority reached the component provider")

    monkeypatch.setattr(generation, "_run_generation", unexpected)
    with pytest.raises(generation.StagedGenerationError):
        await generation.generate_component_candidate(
            request="Expand monitoring",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
            base_components=_edit_base(),
            edit_permissions=permissions,
        )


@pytest.mark.parametrize("enforce_label", [False, True])
def test_connection_plan_preserves_exact_label_authority_and_contract_owner_limit(
    enforce_label,
):
    from agent.applied_graph_spec import GRAPH_EDGE_LABEL_CHARS

    required_contract = "x" * GRAPH_EDGE_LABEL_CHARS
    permissions = _permissions(
        allowed_new_edge_count=1,
        added_edge_anchor_node_ids=["n1", "n2"],
        enforce_added_edge_contract_label=enforce_label,
        connection_addition_obligations=[
            {"source": "n1", "target": "n2", "required_contract": required_contract}
        ],
    )
    plan = generation._connection_addition_plan(permissions, {"n1": 0, "n2": 1})
    assert plan["enforce_added_edge_contract_label"] is enforce_label
    assert plan["obligations"][0]["required_contract"] == required_contract
    permissions["connection_addition_obligations"][0]["required_contract"] += "x"
    with pytest.raises(
        generation.StagedGenerationError, match="edit_connection_plan_invalid"
    ):
        generation._connection_addition_plan(permissions, {"n1": 0, "n2": 1})


def _cold_chain_root_candidate(root_index=5, independent_primary=False):
    # The six primary roles and central root reproduce run 34656915601's upstream chain.
    roles = [
        ("Shipment Sensor Fleet", 106, "Emits identified temperature readings."),
        (
            "Telemetry Ingestion Gateway",
            104,
            "Authenticates and buffers sensor readings.",
        ),
        (
            "Telemetry Normalization Service",
            101,
            "Validates and normalizes sensor readings.",
        ),
        (
            "Excursion Detection Service",
            101,
            "Detects excursions and opens candidate incidents.",
        ),
        ("Incident Event Queue", 103, "Delivers ordered excursion events to triage."),
        (
            "AI Triage & Root-Cause Service",
            101,
            "Classifies excursions and drafts response actions.",
        ),
    ]
    return {
        **_component_wire(),
        "title": "Cold-chain incident processing",
        "root_index": root_index,
        "components": [
            {
                "label": label,
                "type": node_type,
                "responsibility": responsibility,
                "group_label": "Incident runtime",
                "group_kind": 600,
                "primary_flow_member": True,
            }
            for label, node_type, responsibility in roles
        ]
        + [
            {
                "label": "Independent Incident Reporter",
                "type": 100,
                "responsibility": "Submits separate incident reports to triage.",
                "group_label": "Incident runtime",
                "group_kind": 600,
                "primary_flow_member": independent_primary,
            }
        ],
    }


@pytest.mark.parametrize(("root_index", "independent_primary"), [(5, False), (0, True)])
def test_captured_upstream_chain_requires_initiating_root_and_natural_primary_path(
    root_index, independent_primary
):
    candidate = _cold_chain_root_candidate(root_index, independent_primary)
    connections = {
        "edges": [
            {
                "source_index": index,
                "target_index": index + 1,
                "label": f"Advances incident processing {index}",
                "flow": 400,
                "sync": 501,
            }
            for index in range(5)
        ]
        + [
            {
                "source_index": 6,
                "target_index": 5,
                "label": "Submits an independent incident",
                "flow": 400,
                "sync": 501,
            }
        ]
    }

    def accepted_components(wire):
        return [
            {
                "index": index,
                "is_root": index == wire["root_index"],
                "primary_flow_member": component["primary_flow_member"],
            }
            for index, component in enumerate(wire["components"])
        ]

    def build(wire):
        return contract.assign_server_ids(
            {
                **wire,
                "request_id": "cold-chain-root-replay",
                "maturity": "prototype",
                "source": "test",
                "stage": "connections",
                "components": [
                    {
                        **component,
                        "model_index": index,
                        "type": generation.NODE_TYPE_CODES[component["type"]],
                        "group_kind": generation.GROUP_KIND_CODES[
                            component["group_kind"]
                        ],
                    }
                    for index, component in enumerate(wire["components"])
                ],
                "connections": [
                    {
                        "source_id": str(edge["source_index"]),
                        "target_id": str(edge["target_index"]),
                        "label": edge["label"],
                        "flow": generation.FLOW_CODES[edge["flow"]],
                        "sync": generation.SYNC_CODES[edge["sync"]],
                    }
                    for edge in connections["edges"]
                ],
            }
        )

    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_unreachable"
    ):
        generation._parse_connection_wire(
            json.dumps(connections),
            accepted_components=accepted_components(candidate),
            edge_limit=6,
        )
    with pytest.raises(
        contract.GraphContractError, match="every primary flow member must be reachable"
    ):
        contract.project_graph_data(build(candidate))

    corrected = _cold_chain_root_candidate(root_index=0, independent_primary=False)
    assert (
        generation._parse_connection_wire(
            json.dumps(connections),
            accepted_components=accepted_components(corrected),
            edge_limit=6,
        )
        == connections
    )
    graph = contract.project_graph_data(build(corrected))
    assert len(graph["nodes"]) == 7
    assert len(graph["edges"]) == 6
    assert graph["sequence"][0]["nodes"] == ["n1"]
    assert {edge["source"] + "->" + edge["target"] for edge in graph["edges"]} == {
        "n1->n2",
        "n2->n3",
        "n3->n4",
        "n4->n5",
        "n5->n6",
        "n7->n6",
    }


@pytest.mark.asyncio
async def test_component_generation_receives_root_selection_before_connections(
    monkeypatch,
):
    calls = []
    candidate = _cold_chain_root_candidate(root_index=0)

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps({"candidate": candidate, "clarification_questions": []})

    monkeypatch.setattr(generation, "_run_generation", generate)
    result = await generation.generate_component_candidate(
        request="Design cold-chain excursion detection and AI-assisted incident triage.",
        resolved_maturity="prototype",
        architecture_context="Sensor readings initiate excursion detection before AI incident triage.",
        write_set=generation.create_write_set(component_limit=7, edge_limit=6),
        upstream_fingerprint="a" * 64,
    )

    assert result["wire"]["root_index"] == 0
    assert len(calls) == 1
    prompt = calls[0]["prompt"]
    criteria = json.loads(prompt.split("\nINPUT\n", 1)[1])["acceptance_criteria"]
    root_rule = criteria["objective_fidelity"]
    assert (
        "For applied system designs, select the initiating primary runtime actor as the root"
        in root_rule
    )
    assert "Every primary member must be naturally reachable outward" in root_rule
    pull_rule = "Determine initiation from declared behavior. A component that pulls or requests data may initiate an outward request with a return response; inbound responses and independent inputs do not disqualify that root. Require contracts consistent with the declared responsibilities, without inventing requests for push-only sources."
    assert pull_rule in root_rule
    assert pull_rule in prompt
    assert (
        "Scoped edits preserve the accepted root and primary membership outside the authorized write set"
        in root_rule
    )


@pytest.mark.parametrize(
    ("primary_members", "edge_contracts", "accepted"),
    [
        ([True, True], [(0, 1, 400), (1, 0, 400)], True),
        ([True, True], [(1, 0, 400)], False),
        ([True, True], [(0, 1, 402), (1, 0, 400)], True),
        ([True, False, True], [(0, 1, 400), (1, 2, 400)], True),
        ([True, False, True], [(0, 1, 401), (1, 2, 400)], True),
        ([True, False, True], [(0, 1, 402), (1, 2, 400)], True),
        ([True, False, True], [(0, 1, 400), (1, 2, 403)], True),
        ([True, False, True], [(1, 0, 400), (1, 2, 400)], False),
        ([True, True], [], False),
    ],
    ids=[
        "pull-request-response",
        "response-only",
        "feedback-request",
        "nonprimary-transit",
        "nonprimary-control-transit",
        "nonprimary-feedback-transit",
        "nonprimary-deployment-transit",
        "nonprimary-reversed-transit",
        "disconnected",
    ],
)
def test_walkthrough_requires_outward_directed_contracts(
    primary_members, edge_contracts, accepted
):
    roles = [
        ("Optimizer", "Initiates optimization by requesting evaluated outcomes."),
        ("Evaluator", "Computes and returns evaluated outcomes for the optimizer."),
        ("Outcome consumer", "Processes evaluated outcomes."),
    ]
    components = [
        {
            **_component_wire()["components"][0],
            "label": label,
            "responsibility": responsibility,
            "primary_flow_member": primary,
        }
        for (label, responsibility), primary in zip(roles, primary_members)
    ]
    edges = [
        {
            "source_index": source,
            "target_index": target,
            "label": "Request evaluated outcomes"
            if source == 0
            else "Return evaluated outcomes",
            "flow": flow,
            "sync": 500,
        }
        for source, target, flow in edge_contracts
    ]
    accepted_components = [
        {"index": index, "is_root": index == 0, "primary_flow_member": primary}
        for index, primary in enumerate(primary_members)
    ]
    build = contract.assign_server_ids(
        {
            **_component_wire(),
            "request_id": "pull-root-regression",
            "maturity": "prototype",
            "source": "test",
            "stage": "connections",
            "components": [
                {
                    **component,
                    "model_index": index,
                    "type": "service",
                    "group_kind": "runtime",
                }
                for index, component in enumerate(components)
            ],
            "connections": [
                {
                    "source_id": str(edge["source_index"]),
                    "target_id": str(edge["target_index"]),
                    "label": edge["label"],
                    "flow": generation.FLOW_CODES[edge["flow"]],
                    "sync": generation.SYNC_CODES[edge["sync"]],
                }
                for edge in edges
            ],
        }
    )
    if accepted:
        assert generation._parse_connection_wire(
            json.dumps({"edges": edges}),
            accepted_components=accepted_components,
            edge_limit=2,
        ) == {"edges": edges}
        graph = contract.project_graph_data(build)
        assert graph["sequence"][0]["nodes"] == ["n1"]
        assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == {
            (f"n{source + 1}", f"n{target + 1}") for source, target, _ in edge_contracts
        }
    else:
        with pytest.raises(
            generation.StagedGenerationError, match="connection_wire_unreachable"
        ):
            generation._parse_connection_wire(
                json.dumps({"edges": edges}),
                accepted_components=accepted_components,
                edge_limit=2,
            )
        with pytest.raises(
            contract.GraphContractError,
            match="every primary flow member must be reachable",
        ):
            contract.project_graph_data(build)


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_component_acceptance_is_shared_with_production_only_downstream_guidance(
    maturity,
):
    from agent.architecture_rubric import (
        RUBRIC_CRITERIA,
        STAGED_PRODUCTION_REQUIREMENTS,
        staged_review_requirements,
    )
    from agent.nodes import staged_graph_gate as gate

    request = "Design document automation with feedback-driven prompt releases."
    prompt, _ = generation._attempt_prompt(
        stage="components",
        request=request,
        resolved_maturity=maturity,
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        architecture_context="Document processing owns prompt evaluation and release.",
    )
    review_prompt = gate._prompt(
        gate="components",
        user_request=request,
        evidence_bundle={},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=(),
    )
    generated_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    generated = generated_input["acceptance_criteria"]
    reviewed = json.loads(
        review_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )
    assert generated == reviewed == staged_review_requirements("components", maturity)
    assert generated_input["acceptance_criteria_order"] == list(reviewed) == [
        "capability_classification", "objective_fidelity", "mece_scope", "brief_coverage",
    ]
    assert "Evaluate capability_classification first from declared behavior" in review_prompt
    assert "same pass even when the supplied flags are wrong" in review_prompt
    assert "covered by its own clauses" in review_prompt
    assert "A prior satisfied coverage review that depended on the old flags" in prompt
    assert "Change only fields authorized by the write set and supplied schema" in prompt
    assert "do not introduce capabilities or unrelated controls" in prompt
    assert (
        generated.keys() == staged_review_requirements("components", "prototype").keys()
    )
    feasibility_rule = "At the component stage, assess whether declared responsibilities and assumptions support a feasible directed path; connections are authored in the next stage. Missing edges or absent peer names in responsibilities are not component defects. Identify a specific incompatible responsibility when rejecting root or primary membership; do not demand connection-stage evidence here."
    assert feasibility_rule in generated["objective_fidelity"]
    assert feasibility_rule in reviewed["objective_fidelity"]
    assert "selected_depth" not in generated
    assert RUBRIC_CRITERIA["selected_depth"] == (
        "components",
        "Match component ownership and operational detail to the selected UI depth "
        "without importing deeper criteria.",
    )
    assert {"objective_fidelity", "brief_coverage", "mece_scope"} <= generated.keys()
    trust_ownership = (
        "For each component's declared consumption of retrieved, recalled or relayed "
        "external, model or user content, assign untrusted-data treatment to that "
        "consumer before use."
    )
    assert (trust_ownership in prompt) == (maturity == "production")
    returned_text_handling = (
        "When a caller checks, transforms or uses text returned by a separately "
        "declared model or provider, declare untrusted handling for that returned "
        "text separately from input briefs or facts."
    )
    assert (returned_text_handling in prompt) == (maturity == "production")
    if maturity == "prototype":
        assert "downstream_controls" not in generated_input
        assert "downstream_controls" not in review_prompt
    else:
        controls = generated_input["downstream_controls"]
        assert controls == STAGED_PRODUCTION_REQUIREMENTS
        assert set(controls).isdisjoint(generated)
        assert all(
            control not in " ".join(generated.values()) for control in controls.values()
        )
        guarantees = contract.production_proofs_for_capabilities(
            {
                "external_effects": True,
                "retrieval_or_reuse": True,
                "learning_or_release": True,
            },
            maturity="production",
        )
        final_requirements = staged_review_requirements(
            "connections", "production", guarantees
        )
        assert "streaming_integrity" not in final_requirements
        assert {
            code: final_requirements[code]
            for code in controls
            if code != "streaming_integrity"
        } == {
            code: guidance
            for code, guidance in controls.items()
            if code != "streaming_integrity"
        }
        reviewed_controls = json.loads(
            review_prompt.split("downstream_controls: ", 1)[1].split("\n", 1)[0]
        )
        assert reviewed_controls == controls == STAGED_PRODUCTION_REQUIREMENTS
        lifecycle = controls["artifact_reuse_lifecycle"]
        assert (
            "For cached outcomes of effectful operations, keep response validity separate "
            "from durable operation identity and completion"
        ) in lifecycle
        assert (
            "must preserve applied-operation deduplication and cannot authorize "
            "repeating the same effect"
        ) in lifecycle
        assert (
            "Return revalidated or current operation status, or refuse replay "
            "through the existing controls"
        ) in lifecycle
        assert (
            "Do not add external effects, retrieval, learning, or streaming solely "
            "to satisfy unrelated guidance"
        ) in prompt
        assert (
            "Connection generation supplies the detailed control contracts and failure "
            "outcomes; it cannot change these component responsibilities"
        ) in prompt


def test_declared_human_authorization_supports_primary_recovery_path():
    components = [
        {
            **_component_wire()["components"][0],
            "label": "Human Decision Console",
            "responsibility": "Issues exact-action authorization after a human decision.",
        },
        {
            **_component_wire()["components"][0],
            "label": "Recovery Workflow",
            "responsibility": "Executes authorized recovery actions and records results.",
        },
    ]
    candidate = {
        **_component_wire(),
        "assumptions": ["Recovery runs only after explicit human authorization."],
        "components": components,
    }
    assert (
        "edges"
        not in generation.component_generation_schema(_write_set())["properties"]
    )
    assert (
        generation._parse_component_wire(json.dumps(candidate), component_limit=2)
        == candidate
    )
    wire = {
        "edges": [
            {
                "source_index": 0,
                "target_index": 1,
                "label": "Authorizes exact recovery action",
                "flow": 401,
                "sync": 501,
            }
        ]
    }
    assert (
        generation._parse_connection_wire(
            json.dumps(wire),
            accepted_components=[
                {"index": index, "is_root": index == 0, "primary_flow_member": True}
                for index in range(2)
            ],
            edge_limit=1,
        )
        == wire
    )
    build = contract.assign_server_ids(
        {
            **candidate,
            "request_id": "authorized-recovery-feasibility",
            "maturity": "prototype",
            "source": "test",
            "stage": "connections",
            "components": [
                {
                    **component,
                    "model_index": index,
                    "type": "service",
                    "group_kind": "runtime",
                }
                for index, component in enumerate(components)
            ],
            "connections": [
                {
                    "source_id": "0",
                    "target_id": "1",
                    "label": "Authorizes exact recovery action",
                    "flow": "control",
                    "sync": "async",
                }
            ],
        }
    )
    graph = contract.project_graph_data(build)
    assert [step["nodes"] for step in graph["sequence"]] == [["n1"], ["n2"]]
    assert graph["edges"][0]["flow"] == "control"


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_retained_expansion_delta_schema_admits_request_response_pair_without_baseline_updates(
    count,
):
    from agent.nodes.graph_worker import staged_edit_scope

    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/staged_expansion_34663963035.json"
        ).read_text()
    )
    base = contract.reconstruct_staged_graph_build(fixture["base_graph"])
    _, permissions = staged_edit_scope(
        fixture["request"], fixture["base_graph"], resolved_complexity="prototype"
    )
    accepted = [
        {"id": node["id"], "index": index}
        for index, node in enumerate(fixture["initial_candidate"]["nodes"])
    ]
    indexes = {row["id"]: row["index"] for row in accepted}
    base_edges = [
        {
            "source_index": indexes[row["source_id"]],
            "target_index": indexes[row["target_id"]],
            "label": row["label"],
            "flow": next(
                code
                for code, value in generation.FLOW_CODES.items()
                if value == row["flow"]
            ),
            "sync": next(
                code
                for code, value in generation.SYNC_CODES.items()
                if value == row["sync"]
            ),
        }
        for row in base["connections"]
    ]
    delta = generation._connection_edit_delta(
        base_edges,
        permissions,
        generation.connection_generation_schema(
            generation.create_write_set(component_limit=7, edge_limit=10)
        ),
        accepted,
    )
    assert delta.schema["properties"]["additions"]["minItems"] == 1
    assert delta.schema["properties"]["additions"]["maxItems"] == 2
    assert delta.schema["properties"]["updates"]["properties"] == {}
    pair = (
        fixture["initial_connection_delta"]["additions"]
        + fixture["correction_delta"]["additions"]
    )
    payload = json.dumps({"updates": {}, "additions": (pair + pair)[:count]})
    if count not in {1, 2}:
        with pytest.raises(
            generation.StagedGenerationError, match="edit_delta_addition_count"
        ):
            delta.assemble(payload)
    else:
        assembled = delta.assemble(payload)
        assert assembled["edges"][: len(base_edges)] == base_edges
        assert assembled["edges"][len(base_edges) :] == pair[:count]


def _retained_correction(case):
    return json.loads(
        (
            Path(__file__).parent / "fixtures" / "staged_corrections_34704850592.json"
        ).read_text()
    )[case]


def _semantic_findings(case):
    # Keep historical captures intact while replaying rules still used by staged review.
    return [
        {
            "code": finding["rule_code"],
            "path": case["stage"],
            "rule": "semantic_gate",
            **{key: value for key, value in finding.items() if key != "rule_code"},
        }
        for finding in case["first_review"]["findings"]
        if finding["rule_code"] != "selected_depth"
    ]


def _marketing_delta(case, findings=None, capacity=20):
    write_set = generation.create_write_set(component_limit=capacity, edge_limit=60)
    return generation._semantic_correction_delta(
        stage="components",
        maturity="production",
        write_set=write_set,
        attempt=1,
        rejected_candidate=case["original_candidate"],
        findings=_semantic_findings(case) if findings is None else findings,
        schema=generation.component_generation_schema(write_set),
    )


def _delta_response(delta):
    return delta.extract(delta.base)


@pytest.mark.asyncio
@pytest.mark.parametrize("change_request", [False, True])
async def test_connection_correction_adds_missing_controls_without_rewriting_witnesses(
    monkeypatch, change_request
):
    request = _connection_wire()["edges"][0]
    response = {
        **request,
        "source_index": request["target_index"],
        "target_index": request["source_index"],
        "label": "Return execution outcome",
    }
    original = {"edges": [request, response]}
    original_snapshot = json.loads(json.dumps(original))
    write_set = generation.create_write_set(component_limit=4, edge_limit=4)
    findings = [
        {
            "code": "safe_action_boundary",
            "path": "connections",
            "rule": "semantic_gate",
            "record_indexes": [0, 1],
            "reason": "A compensating action has no contract.",
        }
    ]
    delta = generation._semantic_correction_delta(
        stage="connections",
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=findings,
        schema=generation.connection_generation_schema(write_set),
        accepted_components=_accepted_components(),
        accepted_context=generation._accepted_context(_accepted_context()),
    )
    payload = delta.extract(original)
    assert payload["updates"] == {"slot_0": None, "slot_1": None}
    update_schema = delta.schema["properties"]["updates"]
    assert update_schema["required"] == ["slot_0", "slot_1"]
    for slot in update_schema["properties"].values():
        assert slot["anyOf"][1] == {"type": "null"}
        assert set(slot["anyOf"][0]["required"]) == set(request)
        assert slot["anyOf"][0]["additionalProperties"] is False
    payload["additions"] = [
        {**request, "label": "Apply approved compensation"},
        {**response, "label": "Return compensation outcome"},
    ]
    if change_request:
        payload["updates"]["slot_0"] = {**request, "label": "Apply approved action"}

    async def generate(**kwargs):
        assert kwargs["schema"] == delta.schema
        return json.dumps(payload)

    monkeypatch.setattr(generation, "_run_generation", generate)
    result = await generation.generate_connection_candidate(
        request="Preserve the action and add controlled compensation.",
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        gate_findings=findings,
        rejected_candidate=original,
    )
    assert result["wire"]["edges"] == [
        payload["updates"]["slot_0"] or request,
        response,
        *payload["additions"],
    ]
    assert delta.extract(result["wire"]) == payload
    assert original == original_snapshot
    assert delta.base == original


@pytest.mark.asyncio
async def test_marketing_semantic_correction_preserves_owners_and_rejects_full_replacement(
    monkeypatch,
):
    case = _retained_correction("applied_domain")
    original = json.loads(json.dumps(case))
    delta = _marketing_delta(case)
    response = _delta_response(delta)
    assert set(response) == {"additions", "updates", "capabilities"}
    assert set(response["updates"]) == {"slot_7", "slot_15"}
    targeted_indexes = {7, 15}
    for index in targeted_indexes:
        response["updates"][f"slot_{index}"] = {
            **case["original_candidate"]["components"][index],
            "responsibility": f"Corrected ownership for component {index}.",
        }
    for update in response["updates"].values():
        if update is not None:
            update.setdefault("parent_index", None)
    calls = []
    wire_response = {
        "candidate": case["bad_corrected_candidate"],
        "clarification_questions": [],
    }

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(wire_response)

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = generation.create_write_set(component_limit=20, edge_limit=60)
    kwargs = dict(
        request=case["request"],
        resolved_maturity="production",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=_semantic_findings(case),
        rejected_candidate=case["original_candidate"],
    )
    with pytest.raises(
        generation.StagedGenerationError, match="staged_generation_schema_invalid"
    ):
        await generation.generate_component_candidate(**kwargs)
    wire_response = {"candidate": response, "clarification_questions": []}
    result = await generation.generate_component_candidate(**kwargs)
    assert len(result["wire"]["components"]) == 17
    unchanged = set(range(17)) - targeted_indexes
    assert len(unchanged) == 15
    for index in unchanged:
        assert (
            result["wire"]["components"][index]
            == case["original_candidate"]["components"][index]
        )
    for field in ("title", "assumptions", "root_index", "capabilities"):
        assert result["wire"][field] == case["original_candidate"][field]
    assert case == original
    metadata = calls[-1]["telemetry"]["metadata"]
    assert metadata["schema_version"] == "staged_components_correction_response_v4"
    prompt = calls[-1]["messages"][0]["content"]
    prompt_input = json.loads(prompt.split("\nINPUT\n")[1])
    assert prompt_input["base"] is None
    assert prompt_input["rejected_candidate"] == case["original_candidate"]
    assert "never return a full replacement or remove records" in prompt
    assert "Cited record indexes define repair scope, not mandatory rewrites" in prompt
    assert (
        "witness records may remain null when additions resolve a missing control"
        in prompt
    )


@pytest.mark.asyncio
async def test_memory_semantic_correction_retains_required_targeted_write(monkeypatch):
    case = _retained_correction("node_followup")
    candidate = case["accepted_components"]
    accepted = [
        {
            "index": index,
            "id": f"n{index + 1}",
            **record,
            "is_root": index == candidate["root_index"],
        }
        for index, record in enumerate(candidate["components"])
    ]
    write_set = generation.create_write_set(component_limit=10, edge_limit=20)
    response = case["bad_corrected_candidate"]
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(response)

    monkeypatch.setattr(generation, "_run_generation", generate)
    kwargs = dict(
        request=case["request"],
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        accepted_components=accepted,
        accepted_context={
            key: candidate[key] for key in ("assumptions", "capabilities")
        },
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=_semantic_findings(case),
        rejected_candidate=case["original_candidate"],
    )
    with pytest.raises(
        generation.StagedGenerationError, match="staged_generation_schema_invalid"
    ):
        await generation.generate_connection_candidate(**kwargs)
    response = {
        "additions": [],
        "updates": {"slot_7": case["original_candidate"]["edges"][7]},
    }
    result = await generation.generate_connection_candidate(**kwargs)
    assert result["wire"] == case["original_candidate"]
    assert len(result["wire"]["edges"]) == 16
    assert "Propose canonical edges in the delta" in calls[-1]["prompt"]
    assert "Propose exchanges only" not in calls[-1]["prompt"]
    assert (
        "response_label"
        not in calls[-1]["schema"]["properties"]["additions"]["items"]["properties"]
    )
    prompt_input = json.loads(calls[-1]["prompt"].split("\nINPUT\n", 1)[1])
    assert prompt_input["rejected_candidate"] == case["original_candidate"]
    assert "correction_exchanges" not in prompt_input
    assert "store curated facts" in result["wire"]["edges"][7]["label"]
    assert calls[-1]["schema"]["properties"]["additions"]["maxItems"] == 4
    assert (
        generation._generation_schema_version("connections", calls[-1]["schema"])
        == "staged_connections_delta_v2"
    )


@pytest.mark.parametrize("indexes", [[True], [-1], [17], [1.5], "4", None])
def test_semantic_correction_rejects_invalid_targets(indexes):
    case = _retained_correction("applied_domain")
    findings = _semantic_findings(case)
    findings[0]["record_indexes"] = indexes
    with pytest.raises(
        generation.StagedGenerationError, match="invalid_correction_findings"
    ):
        _marketing_delta(case, findings)


@pytest.mark.parametrize("rule_code", ["invented_rule", "selected_depth"])
def test_semantic_correction_rejects_unknown_or_retired_rule(rule_code):
    case = _retained_correction("applied_domain")
    findings = _semantic_findings(case)
    findings[0]["code"] = rule_code
    with pytest.raises(
        generation.StagedGenerationError, match="invalid_correction_findings"
    ):
        _marketing_delta(case, findings)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_slot",
        "unknown_null_slot",
        "unknown_field",
        "partial_update",
        "missing_slot",
        "removal",
        "metadata",
        "capacity",
    ],
)
def test_semantic_correction_rejects_authority_expansion(mutation):
    case = _retained_correction("applied_domain")
    delta = _marketing_delta(case, capacity=17)
    response = _delta_response(delta)
    if mutation == "unknown_slot":
        response["updates"]["slot_0"] = case["original_candidate"]["components"][0]
    elif mutation == "unknown_null_slot":
        response["updates"]["slot_0"] = None
    elif mutation == "unknown_field":
        response["updates"]["slot_7"] = {
            **case["original_candidate"]["components"][7],
            "invented": True,
        }
    elif mutation == "missing_slot":
        response["updates"].pop("slot_7")
    elif mutation == "partial_update":
        response["updates"]["slot_7"] = {"label": "Incomplete replacement"}
    elif mutation == "removal":
        response["removals"] = [7]
    elif mutation == "metadata":
        response["assumptions"] = []
    else:
        response["additions"] = [case["original_candidate"]["components"][0]]
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps(response))


def _paired_recovery(indexes=(0, 1), *, limit=8, provenance=None, global_finding=False):
    exchanges = {"exchanges": [
        {"source_index": 0, "target_index": 1, "label": "Invoke tool",
         "response_label": "Tool result", "flow": 400, "sync": 500},
        {"source_index": 1, "target_index": 0, "label": "Publish event",
         "response_label": None, "flow": 402, "sync": 501},
    ]}
    wire, pairs = generation._parse_connection_response(
        json.dumps(exchanges), accepted_components=_accepted_components(), edge_limit=limit,
    )
    write_set = generation.create_write_set(component_limit=4, edge_limit=limit)
    findings = [{"code": "edge_semantics", "path": "connections",
                 "rule": "semantic_gate", "record_indexes": list(indexes)}]
    if global_finding:
        findings.append({**findings[0], "record_indexes": []})
    delta = generation._semantic_correction_delta(
        stage="connections", maturity="prototype", write_set=write_set, attempt=1,
        rejected_candidate=wire, findings=findings,
        schema=generation.connection_generation_schema(write_set),
        accepted_components=_accepted_components(),
        accepted_context=generation._accepted_context(_accepted_context()),
        recovery_mode=True, connection_exchanges=pairs if provenance is None else provenance,
    )
    return delta, wire, pairs, write_set, findings


@pytest.mark.asyncio
async def test_paired_recovery_preserves_request_and_uncited_event(monkeypatch):
    delta, original, pairs, write_set, findings = _paired_recovery()
    assert set(delta.schema["properties"]["updates"]["properties"]) == {"slot_0"}
    accepted = _accepted_components() + [
        {**_accepted_components()[1], "index": 7, "id": "unrelated_id", "label": "Isolated owner"}
    ]
    update = {"label": "Invoke tool", "response_label": "Validated tool result",
              "flow": 400, "sync": 500}

    async def fake_stream(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        assert '"original_edge_to_exchange_slot":{"0":"slot_0","1":"slot_0","2":"slot_1"}' in prompt
        assert "Compare expanded forward and reply contracts against unchanged, updated, and added contracts in the complete assembled candidate" in prompt
        assert "Never copy a retained contract into additions" in prompt
        assert "Use authorized update slots to change an existing contract" in prompt
        assert "A label-only edit cannot repair an incorrect sender or recipient" in prompt
        assert "When endpoints conflict with accepted responsibilities" in prompt
        assert "allowlisted removal and a complete replacement" in prompt
        assert "correction delta defined by the supplied response schema" in prompt
        assert "using INPUT.acceptance_criteria for these failed codes" in prompt
        prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
        assert "correction_slots" not in prompt_input
        assert prompt_input["correction_component_record_indexes"] == [
            {"component_index": 0, "incoming_record_indexes": [1, 2], "outgoing_record_indexes": [0]},
            {"component_index": 1, "incoming_record_indexes": [0], "outgoing_record_indexes": [1, 2]},
            {"component_index": 7, "incoming_record_indexes": [], "outgoing_record_indexes": []},
        ]
        assert "rejected_candidate" not in prompt_input
        assert "rejected_candidate" not in prompt.split("\nINPUT\n", 1)[0]
        assert "authoritative complete rejected candidate" in prompt
        prompt_wire, prompt_pairs = generation._parse_connection_response(
            json.dumps({"exchanges": prompt_input["correction_exchanges"]}),
            accepted_components=accepted,
            edge_limit=8,
        )
        assert prompt_wire == original
        assert prompt_pairs == pairs
        assert prompt_input["correction_exchanges"][0]["response_label"] == "Tool result"
        assert prompt_input["correction_exchanges"][1]["label"] == "Publish event"
        assert prompt_input["correction_exchanges"][1]["response_label"] is None
        assert prompt_input["findings"]["gate"] == findings
        assert "edge_semantics" in prompt_input["acceptance_criteria"]
        assert "inspect incoming contracts" in prompt
        assert "before changing outgoing payloads" in prompt
        assert "proves neither completeness nor ordering, and grants no edit authority" in prompt
        assert "inspect retained exchanges, including locked records, and proposed updates" in prompt
        assert "through required controls" in prompt
        assert "each new request and expanded reply against the full assembled candidate" in prompt
        assert "whitespace-normalized, case-folded label" in prompt
        assert "Preserve declared handling for each consumed payload class" in prompt
        assert "do not expand the write set or supplied schema permissions" in prompt
        return _response({"updates": {"slot_0": update}, "additions": [], "removals": []})

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    result = await generation.generate_connection_candidate(
        request="Repair the tool return", resolved_maturity="prototype", write_set=write_set,
        upstream_fingerprint="a" * 64, accepted_components=accepted,
        accepted_context=_accepted_context(), attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        gate_findings=findings, rejected_candidate=original,
        prior_connection_exchanges=pairs, recovery_mode=True,
    )
    assert result["wire"]["edges"][0] == original["edges"][0]
    assert result["wire"]["edges"][1]["label"] == "Validated tool result"
    assert result["wire"]["edges"][2] == original["edges"][2]
    assert result["connection_exchanges"] == pairs
    properties = delta.schema["properties"]["updates"]["properties"]["slot_0"][
        "anyOf"
    ][0]["properties"]
    assert "source_index to target_index" in properties["label"]["description"]
    assert (
        "only from target_index to source_index"
        in properties["response_label"]["description"]
    )
    assert "Use null" not in properties["response_label"]["description"]
    for field in ("label", "response_label"):
        assert properties[field]["type"] == "string"
        assert properties[field]["minLength"] == 1
        assert properties[field]["maxLength"] == contract.CONNECTION_LABEL_MAX_CHARS
    assert generation._generation_schema_version("connections", delta.schema) == (
        "staged_connections_exchange_correction_v2"
    )


@pytest.mark.parametrize("change", [{"response_label": None}, {"response_label": " "},
                                  {"source_index": 1, "target_index": 0}])
def test_paired_recovery_rejects_lost_request_or_reply(change):
    delta, *_ = _paired_recovery()
    update = {"label": "Invoke tool", "response_label": "Tool result", "flow": 400, "sync": 500} | change
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps({"updates": {"slot_0": update}, "additions": [], "removals": []}))


def test_paired_recovery_removal_reindexes_and_allows_explicit_rewire():
    delta, original, *_ = _paired_recovery()
    replacement = {"source_index": 1, "target_index": 0, "label": "Request check",
                   "response_label": "Check outcome", "flow": 400, "sync": 501}
    wire, pairs = generation._parse_connection_response(
        json.dumps(delta.assemble(json.dumps({"updates": {"slot_0": None},
            "additions": [replacement], "removals": [0]}))),
        accepted_components=_accepted_components(), edge_limit=8,
    )
    assert wire["edges"][0] == original["edges"][2]
    assert pairs == [{"request_record_index": 0, "response_record_index": None},
                     {"request_record_index": 1, "response_record_index": 2}]
    assert wire["edges"][1]["sync"] == wire["edges"][2]["sync"] == 501



def test_rag_paired_recovery_rewires_only_cited_exchanges():
    accepted = [
        {**_accepted_components()[1], "index": index, "id": f"n{index + 1}",
         "label": f"RAG owner {index + 1}", "is_root": index == 0}
        for index in range(9)
    ]
    exchanges = [
        {"source_index": source, "target_index": target, "label": label,
         "response_label": reply, "flow": flow, "sync": sync}
        for source, target, label, reply, flow, sync in [
            (0, 1, "Submit question", None, 400, 500),
            (1, 2, "Deliver question embedding", None, 400, 500),
            (2, 3, "Request passages", "Return ranked passages", 400, 500),
            (2, 5, "Deliver retrieved passages", None, 400, 500),
            (5, 6, "Send augmented prompt", "Return grounded answer", 400, 500),
            (6, 7, "Deliver answer with supporting passages", None, 400, 500),
            (7, 0, "Present answer", None, 400, 501),
            (4, 3, "Load chunks before runtime", None, 401, 501),
            (8, 6, "Contrast retrieval and finetuning", None, 402, 501),
        ]
    ]
    original, pairs = generation._parse_connection_response(
        json.dumps({"exchanges": exchanges}), accepted_components=accepted, edge_limit=20,
    )
    snapshot = json.loads(json.dumps(original))
    write_set = generation.create_write_set(component_limit=9, edge_limit=20)
    delta = generation._semantic_correction_delta(
        stage="connections", maturity="prototype", write_set=write_set, attempt=1,
        rejected_candidate=original,
        findings=[{"code": "edge_semantics", "path": "connections",
                   "rule": "semantic_gate", "record_indexes": [7, 10]}],
        schema=generation.connection_generation_schema(write_set),
        accepted_components=accepted,
        accepted_context=generation._accepted_context(_accepted_context()),
        recovery_mode=True, connection_exchanges=pairs,
    )
    assert set(delta.schema["properties"]["updates"]["properties"]) == {"slot_5", "slot_8"}
    replacement = {**exchanges[5], "source_index": 5}
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps({"updates": {"slot_5": replacement, "slot_8": None},
                                   "additions": [], "removals": []}))
    repaired, _ = generation._parse_connection_response(
        json.dumps(delta.assemble(json.dumps({
            "updates": {"slot_5": None, "slot_8": None},
            "additions": [replacement], "removals": [5, 8],
        }))), accepted_components=accepted, edge_limit=20,
    )
    assert repaired["edges"][:-1] == [
        edge for index, edge in enumerate(original["edges"]) if index not in {7, 10}
    ]
    assert repaired["edges"][-1] == {
        key: value for key, value in replacement.items() if key != "response_label"
    }
    assert original == snapshot

def test_paired_recovery_checks_expanded_edge_capacity():
    delta, *_ = _paired_recovery(limit=3)
    addition = {"source_index": 0, "target_index": 1, "label": "Another request",
                "response_label": "Another reply", "flow": 401, "sync": 500}
    assembled = delta.assemble(json.dumps({"updates": {"slot_0": None},
        "additions": [addition], "removals": []}))
    with pytest.raises(generation.StagedGenerationError, match="connection_wire_invalid"):
        generation._parse_connection_response(json.dumps(assembled),
            accepted_components=_accepted_components(), edge_limit=3)


@pytest.mark.parametrize("indexes,global_finding", [((), False), ((0,), True)])
def test_global_full_capacity_recovery_retains_canonical_endpoint_authority(indexes, global_finding):
    delta, *_ = _paired_recovery(indexes=indexes, limit=3, global_finding=global_finding)
    assert delta.record_key == "edges"
    slot = delta.schema["properties"]["updates"]["properties"]["slot_0"]["anyOf"][0]
    assert {"source_index", "target_index"} <= set(slot["properties"])


def test_one_way_exchange_may_add_async_reply_and_new_exchange():
    delta, original, *_ = _paired_recovery(indexes=(2,))
    result, pairs = generation._parse_connection_response(
        json.dumps(delta.assemble(json.dumps({
            "updates": {"slot_1": {"label": "Publish event", "response_label": "Receipt",
                                   "flow": 402, "sync": 501}},
            "removals": [], "additions": [{"source_index": 0, "target_index": 1,
                "label": "Deploy release", "response_label": None, "flow": 403, "sync": 501}],
        }))), accepted_components=_accepted_components(), edge_limit=8,
    )
    assert result["edges"][:2] == original["edges"][:2]
    assert pairs == [{"request_record_index": 0, "response_record_index": 1},
                     {"request_record_index": 2, "response_record_index": 3},
                     {"request_record_index": 4, "response_record_index": None}]


@pytest.mark.parametrize("pairs", [[], [{"request_record_index": True, "response_record_index": 1}],
    [{"request_record_index": 1, "response_record_index": 0}],
    [{"request_record_index": 0, "response_record_index": None},
     {"request_record_index": 2, "response_record_index": None}]])
def test_paired_recovery_rejects_malformed_provenance(pairs):
    with pytest.raises(generation.StagedGenerationError, match="invalid_connection_exchange_provenance"):
        _paired_recovery(provenance=pairs)


def _recovery_components():
    original = _component_wire()
    original["components"] = [
        {**original["components"][0], "label": f"Owner {index}"} for index in range(3)
    ]
    original["root_index"] = 2
    return original


def _recovery_delta(stage, original, indexes, *, component_limit=4, edge_limit=4):
    write_set = generation.create_write_set(
        component_limit=component_limit, edge_limit=edge_limit
    )
    return generation._semantic_correction_delta(
        stage=stage,
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=[
            {
                "code": "mece_scope" if stage == "components" else "edge_semantics",
                "path": stage,
                "rule": "semantic_gate",
                "record_indexes": indexes,
            }
        ],
        schema=(
            generation.component_generation_schema(write_set)
            if stage == "components"
            else generation.connection_generation_schema(write_set)
        ),
        accepted_components=(
            _accepted_components() if stage == "connections" else None
        ),
        accepted_context=(
            generation._accepted_context(_accepted_context())
            if stage == "connections"
            else None
        ),
        recovery_mode=True,
    )


def test_recovery_component_removal_reindexes_root_and_preserves_uncited_records():
    original = _recovery_components()
    delta = _recovery_delta("components", original, [0])
    response = {
        "additions": [],
        "updates": {"slot_0": None},
        "capabilities": original["capabilities"],
        "removals": [0],
    }
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=4
    )
    assert assembled["components"] == original["components"][1:]
    assert assembled["root_index"] == 1
    assert assembled["title"] == original["title"]
    assert assembled["assumptions"] == original["assumptions"]
    assert delta.schema["properties"]["removals"]["items"]["enum"] == [0]


@pytest.mark.asyncio
async def test_component_recovery_uses_one_provider_call_and_keeps_output_limit(
    monkeypatch,
):
    original = _recovery_components()
    write_set = generation.create_write_set(component_limit=3, edge_limit=4)
    calls = []

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(
            {
                "candidate": {
                    "additions": [],
                    "updates": {"slot_0": None},
                    "capabilities": original["capabilities"],
                    "removals": [0],
                },
                "clarification_questions": [],
            }
        )

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    result = await generation.generate_component_candidate(
        request="Draw the accepted request path.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        gate_findings=[
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [0],
            }
        ],
        rejected_candidate=original,
        recovery_mode=True,
        max_output_tokens=777,
    )
    assert result["wire"]["components"] == original["components"][1:]
    assert result["wire"]["root_index"] == 1
    assert len(calls) == 1
    assert calls[0]["provider_attempt_limit"] == 1
    assert calls[0]["max_output_tokens"] == 777
    assert calls[0]["telemetry"]["metadata"]["correction_attempt"] == 1
    assert calls[0]["telemetry"]["metadata"]["schema_version"] == (
        "staged_components_recovery_response_v3"
    )
    prompt = calls[0]["messages"][0]["content"]
    assert "Cited record indexes define repair scope, not mandatory rewrites" in prompt
    assert (
        "witness records may remain null when additions resolve a missing control"
        in prompt
    )
    assert "provide replacement directed paths" not in prompt


def test_recovery_addition_without_removal_cannot_exceed_original_limit():
    original = _recovery_components()
    delta = _recovery_delta("components", original, [0], component_limit=3)
    response = {
        "additions": [{**original["components"][0], "label": "Fourth owner"}],
        "updates": {"slot_0": None},
        "capabilities": original["capabilities"],
        "removals": [],
    }
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ):
        generation._parse_component_wire(
            json.dumps(delta.assemble(json.dumps(response))), component_limit=3
        )


def test_recovery_component_root_selection_uses_original_or_addition_indexes():
    original = _recovery_components()
    delta = _recovery_delta("components", original, [0, 2])
    response = {
        "additions": [],
        "updates": {"slot_0": None, "slot_2": None},
        "capabilities": original["capabilities"],
        "removals": [0, 2],
        "root_index": 1,
        "root_addition_index": None,
    }
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=4
    )
    assert assembled["components"] == [original["components"][1]]
    assert assembled["root_index"] == 0
    response["root_index"] = None
    response["root_addition_index"] = 0
    response["additions"] = [
        {**original["components"][0], "label": "Replacement owner"}
    ]
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=4
    )
    assert assembled["root_index"] == 1
    assert assembled["components"] == [
        original["components"][1],
        response["additions"][0],
    ]


@pytest.mark.parametrize(
    "removals,update,error",
    [
        ([0, 0], None, "recovery_removals_invalid"),
        ([1], None, "recovery_removals_invalid"),
        ([True], None, "recovery_removals_invalid"),
        ([0], "changed", "recovery_removal_update_conflict"),
    ],
)
def test_recovery_rejects_invalid_removals(removals, update, error):
    original = _recovery_components()
    delta = _recovery_delta("components", original, [0])
    response = {
        "additions": [],
        "updates": {
            "slot_0": (
                {**original["components"][0], "label": update}
                if update is not None
                else None
            )
        },
        "capabilities": original["capabilities"],
        "removals": removals,
    }
    with pytest.raises(generation.StagedGenerationError, match=error):
        delta.assemble(json.dumps(response))


@pytest.mark.parametrize(
    "root_index,root_addition_index",
    [(None, None), (2, None), (1, 0), (None, 1), (True, None)],
)
def test_recovery_rejects_invalid_root_selection(root_index, root_addition_index):
    original = _recovery_components()
    delta = _recovery_delta("components", original, [2])
    response = {
        "additions": [{**original["components"][2], "label": "New owner"}],
        "updates": {"slot_2": None},
        "capabilities": original["capabilities"],
        "removals": [2],
        "root_index": root_index,
        "root_addition_index": root_addition_index,
    }
    with pytest.raises(generation.StagedGenerationError, match="recovery_root_invalid"):
        delta.assemble(json.dumps(response))


def test_recovery_global_finding_allows_updates_but_no_deletion():
    original = _recovery_components()
    delta = _recovery_delta("components", original, [])
    assert set(delta.schema["properties"]["updates"]["properties"]) == {
        "slot_0",
        "slot_1",
        "slot_2",
    }
    assert delta.schema["properties"]["removals"]["maxItems"] == 0
    response = {
        "additions": [],
        "updates": {f"slot_{index}": None for index in range(3)},
        "title": original["title"],
        "assumptions": original["assumptions"],
        "capabilities": original["capabilities"],
        "root_index": None,
        "root_addition_index": None,
        "removals": [1],
    }
    with pytest.raises(
        generation.StagedGenerationError, match="recovery_removals_invalid"
    ):
        delta.assemble(json.dumps(response))


def test_recovery_mixed_global_and_local_findings_allow_only_local_deletion():
    original = _recovery_components()
    write_set = _write_set()
    delta = generation._semantic_correction_delta(
        stage="components",
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=[
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [],
            },
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [1],
            },
        ],
        schema=generation.component_generation_schema(write_set),
        recovery_mode=True,
    )
    assert set(delta.schema["properties"]["updates"]["properties"]) == {
        "slot_0",
        "slot_1",
        "slot_2",
    }
    assert delta.schema["properties"]["removals"]["items"]["enum"] == [1]
    assert delta.removal_allowlist == (1,)


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", [1, 2])
async def test_connection_recovery_removes_only_cited_edge_and_keeps_components(
    monkeypatch, attempt,
):
    first = _connection_wire()["edges"][0]
    second = {**first, "source_index": 1, "target_index": 0, "label": "response"}
    original = {"edges": [first, second]}
    write_set = _write_set()
    finding = {
        "code": "edge_semantics",
        "path": "connections",
        "rule": "semantic_gate",
        "record_indexes": [0],
    }
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {"additions": [], "updates": {"slot_0": None}, "removals": [0]}
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    accepted = _accepted_components()
    result = await generation.generate_connection_candidate(
        request="Preserve the response path.",
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        accepted_components=accepted,
        accepted_context=_accepted_context(),
        attempt=attempt,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        gate_findings=[finding],
        rejected_candidate=original,
        recovery_mode=True,
    )
    assert result["wire"] == {"edges": [second]}
    assert "connection_exchanges" not in result
    assert accepted == _accepted_components()
    assert calls[0]["schema"]["properties"]["removals"]["items"]["enum"] == [0]
    assert generation._generation_schema_version("connections", calls[0]["schema"]) == (
        "staged_connections_recovery_delta_v1"
    )
    assert calls[0]["attempt"] == attempt
    prompt = calls[0]["prompt"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert prompt_input["recovery_mode"] is True
    assert "simplest complete overview of the original request" in prompt
    assert "Connections cannot change the accepted components" in prompt
    assert "Across changed contracts and replacement routes, preserve valid existing" in prompt
    assert "provenance, scope, conditions, alternate outcomes, and authority" in prompt
    assert "unless an explicit finding requires their correction" in prompt
    assert "Repair each finding's full criterion throughout the candidate, then recheck" in prompt
    assert "including criteria that passed before correction" in prompt
    assert "the receiving consumer's handling. Preserve already declared clauses." in prompt
    assert "do not expand the write set or supplied schema permissions" in prompt
    assert set(calls[0]["schema"]["properties"]["updates"]["properties"]) == {"slot_0"}
    assert "capabilities" not in calls[0]["schema"]["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    ["initial", "edit_write_set", "base", "edit_permissions"],
)
async def test_recovery_mode_rejects_noncreation_authority(monkeypatch, invalid):
    async def generate(**_kwargs):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(generation, "_run_generation", generate)
    kwargs = dict(
        request="Draw a request path.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        attempt=1,
        recovery_mode=True,
    )
    if invalid == "initial":
        kwargs["attempt"] = 0
    elif invalid == "edit_write_set":
        kwargs["write_set"] = generation.exact_edit_write_set(
            component_ids=["n1"], edge_ids=[]
        )
    elif invalid == "base":
        kwargs["base_components"] = _component_wire()
    else:
        kwargs["edit_permissions"] = {}
    with pytest.raises(generation.StagedGenerationError, match="invalid_recovery_mode"):
        await generation.generate_component_candidate(**kwargs)


@pytest.mark.asyncio
async def test_recovery_structural_correction_keeps_complete_candidate_and_call_limit(
    monkeypatch,
):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {"candidate": _component_wire(), "clarification_questions": []}
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    write_set = _write_set()
    result = await generation.generate_component_candidate(
        request="Draw a request path.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=[
            {"code": "component_wire_invalid", "path": "components", "rule": "shape"}
        ],
        rejected_candidate=_component_wire(),
        recovery_mode=True,
    )
    assert result["wire"] == _component_wire()
    assert len(calls) == 1
    assert calls[0]["attempt"] == 1
    assert (
        calls[0]["schema"]["properties"]["candidate"]["anyOf"][0]["properties"].keys()
        == _component_wire().keys()
    )
    prompt_input = json.loads(calls[0]["prompt"].split("\nINPUT\n", 1)[1])
    assert prompt_input["recovery_mode"] is True
    assert "correction_slots" not in prompt_input


def test_indexless_finding_in_mixed_list_grants_global_updates_without_deletion():
    case = _retained_correction("applied_domain")
    findings = _semantic_findings(case)
    findings.append(
        {"code": "objective_fidelity", "path": "components", "rule": "semantic_gate"}
    )
    delta = _marketing_delta(case, findings, capacity=18)
    response = _delta_response(delta)
    assert len(response["updates"]) == 17
    assert set(response) == {
        "updates",
        "additions",
        "title",
        "assumptions",
        "root_index",
        "capabilities",
    }
    addition = {
        **case["original_candidate"]["components"][0],
        "label": "New initiating actor",
    }
    response["additions"] = [addition]
    response["root_index"] = 17
    response["assumptions"] = ["Explicitly corrected global context."]
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=18
    )
    assert assembled["components"][:17] == case["original_candidate"]["components"]
    assert assembled["components"][17] == addition
    assert assembled["root_index"] == 17
    assert assembled["assumptions"] == response["assumptions"]


@pytest.mark.parametrize(
    "code,metadata",
    [
        ("objective_fidelity", {"title", "assumptions", "root_index"}),
        ("capability_classification", {"capabilities"}),
    ],
)
def test_targeted_global_criterion_has_explicit_metadata_scope(code, metadata):
    case = _retained_correction("applied_domain")
    findings = [
        {
            "code": code,
            "path": "components",
            "rule": "semantic_gate",
            "record_indexes": [4],
        }
    ]
    delta = _marketing_delta(case, findings)
    assert (
        set(delta.schema["properties"])
        == {"updates", "additions", "capabilities"} | metadata
    )
    assert set(delta.schema["properties"]["updates"]["properties"]) == {"slot_4"}
    assert "responsibility" in delta.schema["properties"]["updates"]["properties"]["slot_4"]["anyOf"][0]["properties"]


@pytest.mark.asyncio
async def test_semantic_component_correction_can_still_clarify(monkeypatch):
    case = _retained_correction("applied_domain")

    async def generate(**kwargs):
        return json.dumps(
            {
                "candidate": None,
                "clarification_questions": [
                    "Which business workflow should this automate?"
                ],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    write_set = generation.create_write_set(component_limit=20, edge_limit=60)
    result = await generation.generate_component_candidate(
        request="Build an operations agent",
        resolved_maturity="production",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        rejected_candidate=case["original_candidate"],
        structural_findings=[
            {
                "code": "objective_fidelity",
                "path": "components",
                "rule": "semantic_gate",
            }
        ],
    )
    assert result["clarification_questions"] == [
        "Which business workflow should this automate?"
    ]


def test_component_correction_added_owner_can_change_capabilities():
    original = _component_wire()
    write_set = _write_set()
    delta = generation._semantic_correction_delta(
        stage="components",
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=[
            {
                "code": "brief_coverage",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [0],
            }
        ],
        schema=generation.component_generation_schema(write_set),
    )
    responsibility = generation.component_generation_schema(write_set)["properties"][
        "components"
    ]["items"]["properties"]["responsibility"]
    assert delta.schema["properties"]["additions"]["items"]["properties"][
        "responsibility"
    ] == responsibility
    assert delta.schema["properties"]["updates"]["properties"]["slot_0"]["anyOf"][
        0
    ]["properties"]["responsibility"] == responsibility
    response = _delta_response(delta)
    assert response["updates"] == {"slot_0": None}
    response["additions"] = [
        {
            **original["components"][0],
            "label": "Approved publication service",
            "responsibility": "Publishes approved changes to the external destination.",
        }
    ]
    response["capabilities"]["external_effects"] = True
    assembled = generation._parse_component_wire(
        json.dumps(delta.assemble(json.dumps(response))), component_limit=4
    )
    assert assembled["capabilities"]["external_effects"] is True
    assert assembled["components"][0] == original["components"][0]
    assert original["capabilities"]["external_effects"] is False


def test_create_exchange_schema_keeps_canonical_edges_unchanged():
    canonical = generation.connection_generation_schema(_write_set())
    original = json.loads(json.dumps(canonical))
    schema = generation._connection_create_response_schema(canonical)
    assert canonical == original
    assert schema["required"] == ["exchanges"]
    item = schema["properties"]["exchanges"]["items"]
    assert item["additionalProperties"] is False
    descriptions = {
        field: item["properties"][field]["description"]
        for field in ("source_index", "target_index", "label", "response_label")
    }
    assert "sending the label contract to target_index" in descriptions["source_index"]
    assert "receiving the label contract from source_index" in descriptions["target_index"]
    assert "source_index to target_index" in descriptions["label"]
    assert "originate at their authoritative owner" in descriptions["label"]
    assert "only from target_index to source_index" in descriptions["response_label"]
    assert "originate or relay the authoritative payload or decision" in descriptions["response_label"]
    assert "null for one-way owner-to-consumer delivery" in descriptions["response_label"]
    assert set(item["required"]) == {
        "source_index",
        "target_index",
        "label",
        "flow",
        "sync",
        "response_label",
    }
    assert item["properties"]["response_label"]["anyOf"] == [
        {
            "type": "string",
            "minLength": 1,
            "maxLength": contract.CONNECTION_LABEL_MAX_CHARS,
            "description": (
                generation._CONNECTION_REPLY_DESCRIPTION
                + " At most 160 characters; target 60 or fewer. "
                + "Preserve the branch, action, and outcome in a concise reply label."
            ),
        },
        {"type": "null"},
    ]


@pytest.mark.parametrize("sync", [500, 501])
@pytest.mark.parametrize(
    "response_label", [None, "Objective, budgets, and guardrails payload"]
)
def test_create_exchange_expands_explicit_reply_independently_of_timing(
    sync, response_label
):
    exchange = {
        "source_index": 1,
        "target_index": 0,
        "label": "Load current objective and constraint scope for optimization cycle",
        "flow": 400,
        "sync": sync,
        "response_label": response_label,
    }
    original = dict(exchange)
    wire, connection_exchanges = generation._parse_connection_response(
        json.dumps({"exchanges": [exchange]}),
        accepted_components=_accepted_components(),
        edge_limit=2,
    )
    forward = {key: value for key, value in exchange.items() if key != "response_label"}
    expected = [forward]
    if response_label is not None:
        expected.append(
            {**forward, "source_index": 0, "target_index": 1, "label": response_label}
        )
    assert wire == {"edges": expected}
    assert connection_exchanges == [
        {
            "request_record_index": 0,
            "response_record_index": 1 if response_label is not None else None,
        }
    ]
    assert exchange == original


def test_create_exchange_mixed_expansion_preserves_order_and_counts_edges():
    paired = _connection_exchanges()["exchanges"][0]
    one_way = {**paired, "label": "enqueue audit", "sync": 501, "response_label": None}
    text = json.dumps({"exchanges": [paired, one_way]})
    wire, connection_exchanges = generation._parse_connection_response(
        text, accepted_components=_accepted_components(), edge_limit=3
    )
    assert [edge["label"] for edge in wire["edges"]] == [
        "requests",
        "response",
        "enqueue audit",
    ]
    assert connection_exchanges == [
        {"request_record_index": 0, "response_record_index": 1},
        {"request_record_index": 2, "response_record_index": None},
    ]
    with pytest.raises(
        generation.StagedGenerationError, match="connection_wire_invalid"
    ):
        generation._parse_connection_response(
            text, accepted_components=_accepted_components(), edge_limit=2
        )


@pytest.mark.asyncio
async def test_connection_create_returns_pairing_for_each_expanded_exchange(
    monkeypatch,
):
    first = _connection_exchanges()["exchanges"][0]
    one_way = {
        **first,
        "label": "send audit notice",
        "sync": 501,
        "response_label": None,
    }
    second = {
        **first,
        "source_index": 1,
        "target_index": 0,
        "label": "read status",
        "response_label": "status result",
    }

    async def fake_stream(**_kwargs):
        return _response({"exchanges": [first, one_way, second]})

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    result = await generation.generate_connection_candidate(
        request="Connect accepted components",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="b" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
    )

    assert [edge["label"] for edge in result["wire"]["edges"]] == [
        "requests",
        "response",
        "send audit notice",
        "read status",
        "status result",
    ]
    assert result["connection_exchanges"] == [
        {"request_record_index": 0, "response_record_index": 1},
        {"request_record_index": 2, "response_record_index": None},
        {"request_record_index": 3, "response_record_index": 4},
    ]
    for exchange in result["connection_exchanges"]:
        request_edge = result["wire"]["edges"][exchange["request_record_index"]]
        response_index = exchange["response_record_index"]
        if response_index is not None:
            response_edge = result["wire"]["edges"][response_index]
            assert (response_edge["source_index"], response_edge["target_index"]) == (
                request_edge["target_index"],
                request_edge["source_index"],
            )


@pytest.mark.parametrize(
    "change",
    [
        {"response_label": ""},
        {"response_label": "  "},
        {"response_label": False},
        {"response_label": 42},
        {"response_label": []},
        {"response_label": "x" * (contract.CONNECTION_LABEL_MAX_CHARS + 1)},
        {"sync": True},
        {"sync": 500.0},
        {"sync": "500"},
        {"sync": 999},
        {"source_index": False},
        {"target_index": 9},
        {"flow": True},
        {"flow": 999},
    ],
)
def test_create_exchange_rejects_invalid_fields(change):
    exchange = {**_connection_exchanges()["exchanges"][0], **change}
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_connection_response(
            json.dumps({"exchanges": [exchange]}),
            accepted_components=_accepted_components(),
            edge_limit=2,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"edges": []},
        {"exchanges": [], "edges": []},
        {"exchanges": None},
        {"exchanges": [None]},
        {"exchanges": [{}]},
        {"exchanges": [{**_connection_exchanges()["exchanges"][0], "id": "invented"}]},
        {"exchanges": [_connection_wire()["edges"][0]]},
    ],
)
def test_create_exchange_rejects_old_format_and_inexact_keys(payload):
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_connection_response(
            json.dumps(payload),
            accepted_components=_accepted_components(),
            edge_limit=2,
        )


def test_create_exchange_rejects_duplicate_return_contract_after_expansion():
    paired = _connection_exchanges()["exchanges"][0]
    compensation = {**paired, "label": "Invoke compensation write"}
    with pytest.raises(generation.StagedGenerationError) as caught:
        generation._parse_connection_response(
            json.dumps({"exchanges": [paired, compensation]}),
            accepted_components=_accepted_components(),
            edge_limit=4,
        )
    error = caught.value
    assert error.code == "connection_wire_invalid"
    assert (error.diagnostic_reason, error.diagnostic_path) == (
        "duplicate_edge",
        "edges.3",
    )
    assert len(error.rejected_candidate["edges"]) == 4
    assert error.rejected_candidate["edges"][2]["label"] == "Invoke compensation write"
    original = error.rejected_candidate
    copied = generation.StagedGenerationError(
        "connection_wire_invalid", rejected_candidate=original
    )
    original["edges"][2]["label"] = "Changed caller data"
    assert copied.rejected_candidate["edges"][2]["label"] == "Invoke compensation write"


def test_create_exchange_empty_graph_uses_canonical_connectivity_policy():
    assert generation._parse_connection_response(
        '{"exchanges": []}',
        accepted_components=_accepted_components(),
        edge_limit=0,
    ) == ({"edges": []}, [])


@pytest.mark.asyncio
async def test_structural_connection_retry_uses_exchanges_and_returns_canonical_edges(
    monkeypatch,
):
    calls = []
    rejected = {
        "edges": [
            _connection_wire()["edges"][0],
            {**_connection_wire()["edges"][0], "label": "Invoke compensation write"},
        ]
    }

    async def fake_stream(**kwargs):
        calls.append(kwargs)
        return _response(_connection_exchanges())

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = _write_set()
    result = await generation.generate_connection_candidate(
        request="Connect accepted components",
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="b" * 64,
        accepted_components=_accepted_components(),
        accepted_context=_accepted_context(),
        attempt=1,
        prior_prompt_fingerprint="c" * 64,
        prior_write_set_fingerprint=_fingerprint(
            json.dumps(write_set, sort_keys=True, separators=(",", ":"))
        ),
        rejected_candidate=rejected,
        structural_findings=[
            {
                "code": "connection_wire_invalid",
                "path": "edges.3",
                "reason": "duplicate_edge",
                "rule": "contract_validation",
            }
        ],
    )
    prompt_input = json.loads(
        calls[0]["messages"][0]["content"].split("\nINPUT\n", 1)[1]
    )
    assert prompt_input["rejected_candidate"] == rejected
    assert prompt_input["findings"]["structural"][0]["reason"] == "duplicate_edge"
    assert prompt_input["findings"]["structural"][0]["path"] == "edges.3"
    assert len(calls) == 1
    assert set(calls[0]["response_schema"]["properties"]) == {"exchanges"}
    assert (
        calls[0]["telemetry"]["metadata"]["schema_version"]
        == "staged_connections_exchanges_v2"
    )
    assert result["wire"] == {
        "edges": [
            _connection_wire()["edges"][0],
            {
                **_connection_wire()["edges"][0],
                "source_index": 1,
                "target_index": 0,
                "label": "response",
            },
        ]
    }
    assert result["connection_exchanges"] == [
        {"request_record_index": 0, "response_record_index": 1}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_kind", ["connection", "credentials", "bad_request", "runtime", "malformed"]
)
async def test_generation_classifies_availability_at_original_exception_boundary(
    monkeypatch, failure_kind
):
    import httpx
    import openai

    request = httpx.Request("POST", "https://example.invalid")
    failures = {
        "connection": openai.APIConnectionError(request=request),
        "credentials": openai.AuthenticationError(
            "private credentials failure",
            response=httpx.Response(401, request=request),
            body=None,
        ),
        "bad_request": openai.BadRequestError(
            "private request failure",
            response=httpx.Response(400, request=request),
            body=None,
        ),
        "runtime": RuntimeError("private implementation failure"),
    }

    async def fake_stream(**kwargs):
        if failure_kind == "malformed":
            return _response({"unrecognized": "invalid response"})
        raise failures[failure_kind]

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    with pytest.raises(generation.StagedGenerationError) as raised:
        await generation.generate_component_candidate(
            request="Draw the request path",
            resolved_maturity="production",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
        )
    code = raised.value.code
    if failure_kind == "connection":
        assert code == "staged_generation_provider_unavailable"
    elif failure_kind == "malformed":
        assert code != "staged_generation_provider_unavailable"
    else:
        assert code == "staged_generation_unavailable"
    assert "private" not in str(raised.value)


@pytest.mark.parametrize("has_base", [False, True])
def test_component_prompt_preserves_subject_breadth_and_existing_ownership(has_base):
    base = (
        {
            "components": [
                {"label": "Existing owner", "responsibility": "Owns validation."}
            ]
        }
        if has_base
        else None
    )
    prompt, _ = generation._attempt_prompt(
        stage="components",
        request="Add a complementary capability."
        if has_base
        else "Explain AI engineering in healthcare.",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=base,
        rejected_candidate=None,
        architecture_context="Retrieved example: AI tools assist a neighboring subject and a different audience.",
    )
    instructions, payload = prompt.split("\nINPUT\n", 1)
    criteria = json.loads(payload)["acceptance_criteria"]
    for contract_text in (instructions, criteria["objective_fidelity"]):
        assert "concrete lifecycle responsibilities or domain decisions" in contract_text
        assert "depict the subject's mechanisms or decision process" in contract_text
        assert "do not create a learner session, comparison or tutoring service" in contract_text
        assert "evidence-retrieval architecture unless explicitly requested as product or system features" in contract_text
        assert "service nodes must own real computation" in contract_text
        assert "topic names may organize groups" in contract_text
        assert "actual causal, adaptation, or lifecycle relationships" in contract_text
        assert "network requests or returns" in contract_text
        assert "Distinguish offline fine-tuning that changes model parameters" in contract_text
        assert "For every request, preserve the requested subject, application domain, and learner audience" in contract_text
        assert "even when retrieved examples concern a neighboring topic" in contract_text
        assert contract_text.index("For every request") < contract_text.index("For an applied system design")
    assert (
        "preserve the subject's breadth in a mechanism, lifecycle, or topic map"
        in instructions
    )
    assert (
        "must not replace the requested subject with an unrequested product"
        in instructions
    )
    assert (
        "For a requested applied-system design, show the internal services"
        in instructions
    )
    assert "concrete lifecycle responsibilities, application categories, or relevant human decisions" in instructions
    assert "Distinguish conceptual techniques from runtime services" in instructions
    complement = "choose a complementary responsibility for each addition that is not already owned"
    assert (complement in instructions) == has_base
    if has_base:
        assert (
            "An add-only edit cannot reassign an existing owner's responsibility"
            in instructions
        )
        assert "instead of merely renaming an overlapping function" in instructions
        assert (
            "only when their slots and fields are explicitly editable" in instructions
        )
        assert json.loads(payload)["base"] == base


@pytest.mark.asyncio
async def test_scoped_connection_correction_preserves_contract_without_expanding_authority(
    monkeypatch,
):
    original = _connection_wire()
    original["edges"][0]["label"] = "Versioned records with provenance, or empty result"
    permissions = _permissions(
        editable_edges=[
            {
                "edge_id": "edge_1",
                "source": "n1",
                "target": "n2",
                "label": original["edges"][0]["label"],
            }
        ],
        editable_edge_fields={"edge_1": ["label"]},
    )
    calls = []
    corrected_label = "Versioned records with provenance or empty; consumer invalidates and revalidates stale records"

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {"additions": [], "updates": {"slot_0": {"label": corrected_label}}}
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    write_set = _write_set()
    result = await generation.generate_connection_candidate(
        request="Correct the reuse contract.",
        resolved_maturity="production",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        accepted_components=_accepted_components(),
        saved_component_ids=["n1", "n2"],
        accepted_context=_accepted_context(),
        base_connections=original["edges"],
        edit_permissions=permissions,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        rejected_candidate=original,
        gate_findings=[
            {
                "code": "artifact_reuse_lifecycle",
                "path": "connections",
                "rule": "semantic_gate",
                "reason": "The contract lacks invalidation and revalidation ownership.",
                "record_indexes": [0],
            }
        ],
    )
    prompt = calls[0]["prompt"]
    prompt_input = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert "Across changed contracts and replacement routes, preserve valid existing" in prompt
    assert "provenance, scope, conditions, alternate outcomes, and authority" in prompt
    assert "Repair each finding's full criterion throughout the candidate, then recheck" in prompt
    assert "including criteria that passed before correction" in prompt
    assert "the receiving consumer's handling. Preserve already declared clauses." in prompt
    assert generation.STAGED_PRODUCTION_REQUIREMENTS["artifact_reuse_lifecycle"] in prompt
    assert (
        "must preserve applied-operation deduplication and cannot authorize "
        "repeating the same effect"
    ) in prompt
    assert prompt_input["findings"]["gate"][0]["code"] == "artifact_reuse_lifecycle"
    assert "do not expand the write set or supplied schema permissions" in prompt
    assert (
        prompt_input["rejected_candidate"]["updates"]["slot_0"]["label"]
        == original["edges"][0]["label"]
    )
    properties = calls[0]["schema"]["properties"]
    assert set(properties["updates"]["properties"]["slot_0"]["properties"]) == {"label"}
    assert properties["additions"]["maxItems"] == 0
    assert "capabilities" not in properties
    assert result["wire"]["edges"] == [
        {**original["edges"][0], "label": corrected_label}
    ]


@pytest.mark.asyncio
async def test_extension_delta_can_request_clarification_without_mutating_locked_base(monkeypatch):
    permissions = _permissions(
        kind="extension", connection_addition_mode="extension", allowed_new_node_count=3,
        minimum_new_node_count=1, allowed_new_edge_count=6, minimum_new_edge_count=1,
        added_edge_anchor_node_ids=["n1", "n2"], enforce_added_edge_contract_label=False,
    )
    result, calls = await _generate_edit(monkeypatch,
        {"candidate": None, "clarification_questions": ["Where should this layer attach?"]}, permissions)
    assert result["clarification_questions"] == ["Where should this layer attach?"]
    schema = calls[0]["schema"]
    assert set(schema["properties"]) == {"candidate", "clarification_questions"}
    candidate_schema = schema["properties"]["candidate"]["anyOf"][0]
    assert candidate_schema["properties"]["additions"]["minItems"] == 1
    assert candidate_schema["properties"]["additions"]["maxItems"] == 3
    assert candidate_schema["properties"]["updates"]["properties"] == {}
@pytest.mark.parametrize("remove_entries", [False, True])
async def test_connection_recovery_preserves_cited_tool_paths_and_root_reachability(
    monkeypatch, remove_entries
):
    accepted = [
        {
            **_accepted_components()[1],
            "index": index,
            "id": f"n{index + 1}",
            "label": label,
            "is_root": index == 0,
            "primary_flow_member": index in {0, 3},
        }
        for index, label in enumerate(
            ["Caller", "Planner", "Executor", "Primary tool", "Input validation"]
        )
    ]
    original = {
        "edges": [
            {
                **_connection_wire()["edges"][0],
                "source_index": source,
                "target_index": target,
                "label": label,
            }
            for source, target, label in [
                (0, 1, "Submit planning request"),
                (0, 2, "Submit execution request"),
                (1, 3, "Request tool planning context"),
                (3, 1, "Return tool planning context"),
                (2, 3, "Request tool execution"),
                (3, 2, "Return tool execution outcome"),
                (1, 0, "Return final plan"),
                (2, 0, "Return final execution result"),
            ]
        ]
    }
    original_snapshot = json.loads(json.dumps(original))
    additions = [
        {
            **_connection_wire()["edges"][0],
            "source_index": source,
            "target_index": target,
            "label": label,
        }
        for source, target, label in [
            (2, 4, "Validate tool arguments before execution"),
            (4, 2, "Return validated arguments or rejection"),
        ]
    ]
    write_set = generation.create_write_set(component_limit=5, edge_limit=10)
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "additions": additions,
                "updates": {f"slot_{index}": None for index in range(8)},
                "removals": [0, 1] if remove_entries else [],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    kwargs = dict(
        request="Keep tool request and result paths and add argument validation.",
        resolved_maturity="prototype",
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        accepted_components=accepted,
        accepted_context=_accepted_context(),
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        gate_findings=[
            {
                "code": "safe_action_boundary",
                "path": "connections",
                "rule": "semantic_gate",
                "record_indexes": list(range(8)),
                "reason": "Tool requests and results lack argument validation contracts.",
            }
        ],
        rejected_candidate=original,
        recovery_mode=True,
    )
    if remove_entries:
        with pytest.raises(
            generation.StagedGenerationError, match="connection_wire_unreachable"
        ):
            await generation.generate_connection_candidate(**kwargs)
    else:
        result = await generation.generate_connection_candidate(**kwargs)
        assert result["wire"]["edges"] == [*original["edges"], *additions]
    assert original == original_snapshot
    assert len(calls) == 1
    prompt = calls[0]["prompt"]
    assert "Cited record indexes define repair scope, not mandatory rewrites" in prompt
    assert (
        "witness records may remain null when additions resolve a missing control"
        in prompt
    )
    assert (
        "preserve reachability from the root to every primary-flow component" in prompt
    )
    assert "provide replacement directed paths" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "collision",
    ["retained_addition", "edited_retained", "edited_addition", "edited_edited"],
)
@pytest.mark.parametrize("unicode_label", [False, True])
async def test_component_semantic_correction_rejects_assembled_identity_collisions(
    monkeypatch, collision, unicode_label
):
    case = _retained_correction("applied_domain")
    if unicode_label:
        case["original_candidate"]["components"][0]["label"] = "Straße Planner"
    original = json.loads(json.dumps(case["original_candidate"]))
    delta = _marketing_delta(case)
    response = _delta_response(delta)
    retained = original["components"][0]
    normalized_variant = " \t" + " \n ".join(retained["label"].upper().split()) + "  "
    if collision == "retained_addition":
        response["additions"] = [{**retained, "label": normalized_variant}]
        duplicate_index = 17
    elif collision == "edited_retained":
        response["updates"]["slot_7"] = {**retained, "label": normalized_variant}
        duplicate_index = 7
    else:
        response["updates"]["slot_7"] = {
            **retained,
            "label": "Straße lifecycle owner"
            if unicode_label
            else "New lifecycle owner",
        }
        duplicate = {
            **retained,
            "label": " STRASSE \t LIFECYCLE OWNER "
            if unicode_label
            else " NEW \t lifecycle  OWNER ",
        }
        if collision == "edited_addition":
            response["additions"] = [duplicate]
            duplicate_index = 17
        else:
            response["updates"]["slot_15"] = duplicate
            duplicate_index = 15
    for update in response["updates"].values():
        if update is not None:
            update.setdefault("parent_index", None)
    calls = []

    async def fake_stream(**arguments):
        calls.append(arguments)
        return _response({"candidate": response, "clarification_questions": []})

    monkeypatch.setattr(generation, "stream_structured_llm", fake_stream)
    write_set = generation.create_write_set(component_limit=20, edge_limit=60)
    arguments = dict(
        request=case["request"],
        resolved_maturity="production",
        architecture_context=_architecture_context(),
        write_set=write_set,
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=_semantic_findings(case),
        rejected_candidate=original,
    )
    with pytest.raises(generation.StagedGenerationError) as caught:
        await generation.generate_component_candidate(**arguments)
    assert caught.value.code == "component_wire_invalid"
    assert caught.value.diagnostic_reason == "duplicate_component"
    assert caught.value.diagnostic_path == f"components.{duplicate_index}"
    assert len(calls) == 1
    assert case["original_candidate"] == original
    prompt = calls[0]["messages"][0]["content"]
    assert "unique across retained rows, authorized updates, and additions" in prompt
    assert (
        "splitting whitespace, joining with a single space, and applying Unicode case-folding"
        in prompt
    )
    assert "Do not re-add retained components" in prompt
    assert (
        calls[0]["telemetry"]["metadata"]["prompt_version"] == "staged_components_v72"
    )

    # A fresh bounded response must fix the collision; invalid rows are never dropped.
    if response["additions"]:
        response["additions"][0]["label"] = "Distinct added owner"
    else:
        slot = "slot_15" if collision == "edited_edited" else "slot_7"
        response["updates"][slot]["label"] = "Distinct edited owner"
    result = await generation.generate_component_candidate(**arguments)
    assert len(calls) == 2
    assert len(result["wire"]["components"]) == 17 + len(response["additions"])
    for index, component in enumerate(original["components"]):
        assert result["wire"]["components"][index] == (
            response["updates"].get(f"slot_{index}") or component
        )
    assert result["wire"]["components"][17:] == response["additions"]
    assert case["original_candidate"] == original


@pytest.mark.asyncio
async def test_structural_repair_rejected_candidate_size_bound_fails_before_provider(
    monkeypatch,
):
    async def unexpected(**kwargs):
        pytest.fail("Oversized rejected input must not reach provider")

    monkeypatch.setattr(generation, "_run_generation", unexpected)
    with pytest.raises(
        generation.StagedGenerationError, match="generation_base_too_large"
    ):
        await generation.generate_connection_candidate(
            request="Repair duplicate replies",
            resolved_maturity="prototype",
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
            accepted_components=_accepted_components(),
            accepted_context=_accepted_context(),
            attempt=1,
            prior_prompt_fingerprint="b" * 64,
            prior_write_set_fingerprint=generation._fingerprint(_write_set()),
            structural_findings=[
                {
                    "code": "connection_wire_invalid",
                    "path": "edges.3",
                    "rule": "contract_validation",
                }
            ],
            rejected_candidate={"edges": [{"label": "x" * 48001}]},
        )


@pytest.mark.parametrize("length", [221, 800])
def test_component_responsibility_ceiling_preserves_complete_wire(length):
    text = "Records " + "a" * (length - 9) + "."
    wire = _component_wire()
    wire["components"][0]["responsibility"] = text
    parsed = generation._parse_component_wire(json.dumps(wire), component_limit=4)
    assert parsed["components"][0]["responsibility"] == text


@pytest.mark.asyncio
async def test_large_saved_responsibilities_fail_before_edit_provider_without_mutation(
    monkeypatch,
):
    base = {
        **_edit_base(),
        "request_id": "large-saved",
        "maturity": "prototype",
        "connections": [],
    }
    template = base["components"][0]
    base["components"] = [
        {
            **template,
            "model_index": index,
            "server_id": f"n{index + 1}",
            "label": f"Owner {index}",
            "responsibility": "x" * 800,
            "primary_flow_member": index == 0,
        }
        for index in range(60)
    ]
    saved = contract.project_graph_data(contract.assign_server_ids(base))
    imported = contract.reconstruct_staged_graph_build(saved)
    original = json.dumps(saved, sort_keys=True)
    original_base = json.dumps(imported, sort_keys=True)

    async def unexpected(**kwargs):
        pytest.fail("Oversized saved edit input must not reach provider")

    monkeypatch.setattr(generation, "_run_generation", unexpected)
    with pytest.raises(
        generation.StagedGenerationError, match="generation_base_too_large"
    ):
        await generation.generate_component_candidate(
            request="Clarify the first owner's responsibility.",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set={**_write_set(), "component_limit": 60},
            upstream_fingerprint=_fingerprint("large saved base"),
            base_components=imported,
            edit_permissions=_permissions(
                editable_node_fields={
                    imported["components"][0]["server_id"]: ["description"]
                }
            ),
        )
    assert json.dumps(saved, sort_keys=True) == original
    assert json.dumps(imported, sort_keys=True) == original_base


def _expand_added_slot_definitions(provider, original):
    added = set(provider.get("$defs", {})) - set(original.get("$defs", {}))

    def expand(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if set(value) == {"$ref"} and reference.startswith("#/$defs/"):
                name = reference.removeprefix("#/$defs/")
                if name in added:
                    return expand(provider["$defs"][name])
            return {key: expand(child) for key, child in value.items()}
        if isinstance(value, list):
            return [expand(child) for child in value]
        return value

    result = expand(provider)
    if added:
        result["$defs"] = {
            name: value for name, value in result["$defs"].items() if name not in added
        }
        if not result["$defs"] and "$defs" not in original:
            result.pop("$defs")
    return result


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("nullable", [False, True])
def test_provider_slot_definitions_preserve_complete_schema_and_original(
    wrapped, nullable
):
    slot = generation._strict_object_schema(
        {
            "responsibility": {"type": "string", "minLength": 1, "maxLength": 800},
            "response_label": {
                "anyOf": [{"type": "string", "maxLength": 100}, {"type": "null"}]
            },
        }
    )
    if nullable:
        slot = {
            "description": "Retain null for unchanged slots.",
            "anyOf": [slot, {"type": "null"}],
        }
    schema = generation._strict_object_schema(
        {
            "updates": generation._strict_object_schema(
                {"slot_0": slot, "slot_1": slot}
            ),
            "removals": {"type": "array", "items": {"type": "integer", "enum": [0]}},
            "root_index": {
                "anyOf": [
                    {"type": "integer", "minimum": 0, "maximum": 1},
                    {"type": "null"},
                ]
            },
        }
    )
    if wrapped:
        schema = generation._component_create_response_schema(schema)
    schema["$defs"] = {"staged_update_slot_0": {"type": "boolean"}}
    schema["properties"]["existing"] = {"$ref": "#/$defs/staged_update_slot_0"}
    schema["required"].append("existing")
    snapshot = json.loads(json.dumps(schema))
    provider = generation._provider_generation_schema(schema)
    assert schema == snapshot
    assert provider["$defs"]["staged_update_slot_0"] == {"type": "boolean"}
    assert len(provider["$defs"]) == 2
    assert generation._canonical_json(
        _expand_added_slot_definitions(provider, schema)
    ) == generation._canonical_json(schema)


@pytest.mark.parametrize(
    "slots",
    [
        {},
        {"slot_0": {"type": "string"}},
        {"slot_0": {"type": "string"}, "slot_1": {"type": "string", "maxLength": 100}},
    ],
)
def test_provider_slot_definitions_leave_empty_single_and_unequal_slots_unchanged(
    slots,
):
    schema = generation._strict_object_schema(
        {"updates": generation._strict_object_schema(slots)}
    )
    assert generation._provider_generation_schema(schema) is schema


def test_provider_slot_definitions_preserve_native_recovery_permissions():
    case = _retained_correction("applied_domain")
    delta = _marketing_delta(case)
    schema = generation._component_create_response_schema(delta.schema)
    provider = generation._provider_generation_schema(schema)
    expanded = _expand_added_slot_definitions(provider, schema)
    assert generation._canonical_json(expanded) == generation._canonical_json(schema)
    valid = _delta_response(delta)
    assert delta.assemble(json.dumps(valid)) == delta.base
    invalid = {**valid, "updates": {**valid["updates"], "slot_999": None}}
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps(invalid))


def test_provider_slot_definitions_preserve_empty_existing_definitions():
    schema = generation._strict_object_schema(
        {
            "updates": generation._strict_object_schema(
                {
                    "slot_0": {"type": "string"},
                    "slot_1": {"type": "string"},
                }
            ),
        }
    )
    schema["$defs"] = {}
    provider = generation._provider_generation_schema(schema)
    assert _expand_added_slot_definitions(provider, schema) == schema


@pytest.mark.parametrize("corrected", [False, True])
def test_connection_label_guidance_survives_provider_schema_and_shared_slots(corrected):
    from adapters.llm_adapter import _anthropic_response_schema

    schema = (
        _paired_recovery()[0].schema
        if corrected
        else generation._connection_create_response_schema(
            generation.connection_generation_schema(_write_set())
        )
    )
    if corrected:
        updates = schema["properties"]["updates"]
        updates["properties"]["slot_1"] = json.loads(json.dumps(updates["properties"]["slot_0"]))
        updates["required"].append("slot_1")
    original = json.loads(json.dumps(schema))
    provider = generation._provider_generation_schema(schema)
    transformed = _anthropic_response_schema(provider)
    assert schema == original
    if corrected:
        assert provider["$defs"]  # Updates share one definition instead of duplicating bounds.

    def labels(value):
        if isinstance(value, dict):
            properties = value.get("properties", {})
            for field in ("label", "response_label"):
                if field in properties:
                    field_schema = properties[field]
                    yield next(
                        (branch for branch in field_schema.get("anyOf", [])
                         if branch.get("type") == "string"), field_schema
                    )
            for child in value.values():
                yield from labels(child)
        elif isinstance(value, list):
            for child in value:
                yield from labels(child)

    bounded = list(labels(transformed))
    assert len(bounded) >= 2
    for field in bounded:
        assert "pattern" not in field
        assert "maxLength" not in field
        assert "At most 160 characters; target 60 or fewer" in field["description"]
        assert "branch, action, and outcome" in field["description"]


@pytest.mark.parametrize("unit", ["x", "é", "😀", "e\u0301"])
def test_native_connection_label_parser_uses_codepoints(unit):
    label = (unit * contract.CONNECTION_LABEL_MAX_CHARS)[:contract.CONNECTION_LABEL_MAX_CHARS]
    row = {"source_index": 0, "target_index": 1, "label": label, "flow": 400, "sync": 500}
    parsed = generation._parse_connection_wire(
        json.dumps({"edges": [row]}), accepted_components=_accepted_components(), edge_limit=4,
    )
    assert parsed["edges"][0]["label"] == label
    with pytest.raises(generation.StagedGenerationError) as error:
        generation._parse_connection_wire(
            json.dumps({"edges": [{**row, "label": label + "x"}]}),
            accepted_components=_accepted_components(), edge_limit=4,
        )
    assert error.value.diagnostic_reason == "label_length"


def test_native_connection_label_parser_keeps_newlines_and_blank_rejection():
    label = "x" * 49 + "\n" + "x" * 50
    row = {"source_index": 0, "target_index": 1, "label": label, "flow": 400, "sync": 500}
    parsed = generation._parse_connection_wire(
        json.dumps({"edges": [row]}), accepted_components=_accepted_components(), edge_limit=4,
    )
    assert parsed["edges"][0]["label"] == label
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_connection_wire(
            json.dumps({"edges": [{**row, "label": " " * 100}]}),
            accepted_components=_accepted_components(), edge_limit=4,
        )


def test_observed_correction_label_is_admitted_without_truncation():
    label = (
        "Verified: valid facts with provenance and report version; "
        "denied, out of scope or invalidated: refused"
    )
    assert len(label) == 102
    wire = generation._parse_connection_wire(
        json.dumps({"edges": [{
            "source_index": 0, "target_index": 1, "label": label,
            "flow": 400, "sync": 500,
        }]}),
        accepted_components=_accepted_components(), edge_limit=4,
    )
    assert wire["edges"][0]["label"] == label


def _owned_component_wire() -> dict:
    wire = _component_wire()
    template = wire["components"][0]
    wire["components"] = [
        {**template, "label": "Student client", "type": 100},
        {**template, "label": "Cache", "type": 102, "primary_flow_member": False},
        {**template, "label": "Tutoring service", "type": 101},
        {
            **template,
            "label": "Conversation coordinator",
            "type": 109,
            "parent_index": 2,
        },
    ]
    return wire


@pytest.mark.parametrize("removed_index", [1, 2])
@pytest.mark.parametrize("recovery", [False, True])
def test_component_removal_reindexes_owned_internals(removed_index, recovery):
    original = _owned_component_wire()
    if recovery:
        delta = _recovery_delta("components", original, [removed_index])
        response = {
            "additions": [],
            "updates": {f"slot_{removed_index}": None},
            "capabilities": original["capabilities"],
            "removals": [removed_index],
        }
    else:
        base = {
            **original,
            "components": [
                {
                    **component,
                    "type": generation.NODE_TYPE_CODES[component["type"]],
                    "group_kind": "runtime",
                    "model_index": index,
                    "server_id": f"n{index}",
                }
                for index, component in enumerate(original["components"])
            ],
        }
        permissions = _permissions(removable_node_ids=[f"n{removed_index}"])
        delta = generation._component_edit_delta(
            base,
            permissions,
            generation.component_generation_schema(
                generation.create_write_set(component_limit=4, edge_limit=4),
            ),
        )
        response = {
            "additions": [],
            "updates": {},
            "capabilities": original["capabilities"],
        }
    if removed_index == 2:
        with pytest.raises(
            generation.StagedGenerationError, match="component_parent_removed"
        ):
            delta.assemble(json.dumps(response))
        return
    assembled = delta.assemble(json.dumps(response))
    parsed = generation._parse_component_wire(json.dumps(assembled), component_limit=4)
    assert parsed["components"][2]["parent_index"] == 1
    assert parsed["components"][1]["label"] == "Tutoring service"


@pytest.mark.parametrize("parent", [None, True, "2", 2.0, -1, 1, 3, 9])
def test_component_wire_requires_a_valid_application_service_parent(parent):
    wire = _owned_component_wire()
    wire["components"][3]["parent_index"] = parent
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ) as caught:
        generation._parse_component_wire(json.dumps(wire), component_limit=4)
    assert caught.value.diagnostic_reason == "component_parent_invalid"
    assert caught.value.diagnostic_path == "components.3.parent_index"


def test_component_wire_forbids_parent_on_application_service():
    wire = _owned_component_wire()
    wire["components"][2]["parent_index"] = 0
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ) as caught:
        generation._parse_component_wire(json.dumps(wire), component_limit=4)
    assert caught.value.diagnostic_reason == "component_parent_forbidden"
    assert caught.value.diagnostic_path == "components.2.parent_index"


@pytest.mark.parametrize("index,parent", [(2, None), (3, 2)])
def test_component_correction_schema_requires_parent_field_in_nonnull_updates(
    index, parent
):
    original = _owned_component_wire()
    write_set = generation.create_write_set(component_limit=4, edge_limit=4)
    delta = generation._semantic_correction_delta(
        stage="components",
        maturity="prototype",
        write_set=write_set,
        attempt=1,
        rejected_candidate=original,
        findings=[
            {
                "code": "mece_scope",
                "path": "components",
                "rule": "semantic_gate",
                "record_indexes": [index],
            }
        ],
        schema=generation.component_generation_schema(write_set),
    )
    slot = f"slot_{index}"
    update_schema = delta.schema["properties"]["updates"]["properties"][slot]["anyOf"][
        0
    ]
    assert "parent_index" in update_schema["required"]
    update = {**original["components"][index], "parent_index": parent}
    response = {**delta.extract(original), "updates": {slot: update}}
    assembled = delta.assemble(json.dumps(response))
    parsed = generation._parse_component_wire(json.dumps(assembled), component_limit=4)
    assert parsed["components"][index]["parent_index"] == parent
    del update["parent_index"]
    with pytest.raises(
        generation.StagedGenerationError, match="staged_generation_schema_invalid"
    ):
        delta.assemble(json.dumps(response))


def test_component_wire_requires_explicit_parent_without_inference():
    wire = _owned_component_wire()
    del wire["components"][3]["parent_index"]
    with pytest.raises(generation.StagedGenerationError) as caught:
        generation._parse_component_wire(json.dumps(wire), component_limit=4)
    assert caught.value.diagnostic_reason == "component_parent_invalid"
    assert caught.value.diagnostic_path == "components.3.parent_index"


@pytest.mark.parametrize("forbidden", [False, True])
def test_component_parent_failure_reaches_retry_prompt(forbidden):
    from agent import staged_graph_workflow as workflow

    wire = _owned_component_wire()
    index = 2 if forbidden else 3
    wire["components"][index]["parent_index"] = 0
    with pytest.raises(generation.StagedGenerationError) as caught:
        generation._parse_component_wire(json.dumps(wire), component_limit=4)
    reason = "component_parent_forbidden" if forbidden else "component_parent_invalid"
    path = f"components.{index}.parent_index"
    diagnostic = workflow._failure_diagnostic(
        caught.value,
        stage="components",
        attempt=1,
        candidate=None,
    )
    assert diagnostic["reason"] == reason
    assert diagnostic["path"] == path
    assert diagnostic["candidate_fingerprint"] == generation._fingerprint(wire)
    finding = workflow._safe_finding(caught.value, stage="components")
    assert finding["reason"] == reason
    assert finding["path"] == path
    prompt, _ = generation._attempt_prompt(
        stage="components",
        request="Expand tutoring internals.",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(_write_set()),
        structural_findings=[finding],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        architecture_context=_architecture_context(),
    )
    payload = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert payload["findings"]["structural"][0]["reason"] == reason
    assert payload["findings"]["structural"][0]["path"] == path


def test_component_correction_can_assign_an_added_service_owner():
    original = _owned_component_wire()
    delta = _recovery_delta("components", original, [1], component_limit=5)
    new_service = {**original["components"][2], "label": "Cache service"}
    updated = {**original["components"][1], "type": 109, "parent_index": 4}
    response = {
        "updates": {"slot_1": updated},
        "additions": [new_service],
        "capabilities": original["capabilities"],
        "removals": [],
    }
    assembled = delta.assemble(json.dumps(response))
    parsed = generation._parse_component_wire(json.dumps(assembled), component_limit=5)
    assert parsed["components"][1]["parent_index"] == 4
    assert parsed["components"][4]["label"] == "Cache service"


def test_component_correction_preserves_explicit_parent_after_removal():
    original = _owned_component_wire()
    practice_service = {**original["components"][2], "label": "Practice service"}
    original["components"].insert(3, practice_service)
    delta = _recovery_delta("components", original, [1, 4], component_limit=5)
    response = {
        "updates": {
            "slot_1": None,
            "slot_4": {**original["components"][4], "parent_index": 2},
        },
        "additions": [],
        "capabilities": original["capabilities"],
        "removals": [1],
    }
    assembled = delta.assemble(json.dumps(response))
    parsed = generation._parse_component_wire(json.dumps(assembled), component_limit=5)
    assert parsed["components"][3]["parent_index"] == 2
    assert parsed["components"][2]["label"] == "Practice service"




def test_scoped_component_edit_rejects_null_update_and_versions_additions_schema():
    delta = generation._component_edit_delta(
        _edit_base(),
        _permissions(editable_node_fields={"n1": ["label"]}),
        generation.component_generation_schema(_write_set()),
    )
    response = delta.extract(delta.base)
    assert response["updates"]["slot_0"] == {"label": "Request gateway"}
    assert generation._generation_schema_version("components", delta.schema) == (
        "staged_components_delta_v7"
    )
    response["updates"]["slot_0"] = None
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps(response))


@pytest.mark.parametrize(
    "accepted_ids,anchors,expected_anchors,expected_additions",
    [
        (
            ["n1", "n2", "n3", "n4", "n5", "n6", "n7"],
            ["n2", "n3", "n5", "n6"],
            [1, 2, 4, 5],
            [6],
        ),
        (
            ["n6", "n1", "n4", "n2", "n5", "n3", "n7"],
            ["n2", "n3", "n5", "n6"],
            [3, 5, 4, 0],
            [6],
        ),
        (
            ["n7", "n6", "n1", "n4", "n2", "n5", "n3"],
            ["n2", "n3", "n5", "n6"],
            [4, 6, 5, 1],
            [0],
        ),
        (
            ["n1", "n2", "n3", "n4", "n5", "n6", "n7"],
            ["n1", "n2", "n3", "n4", "n5", "n6"],
            [0, 1, 2, 3, 4, 5],
            [6],
        ),
        (
            ["n7", "n1", "n8", "n2", "n3", "n4", "n5", "n6"],
            ["n2", "n3", "n5", "n6"],
            [3, 4, 6, 7],
            [0, 2],
        ),
    ],
)
def test_connection_extension_identifies_additions_against_saved_ids(
    accepted_ids, anchors, expected_anchors, expected_additions
):
    permissions = _permissions(
        connection_addition_mode="extension",
        minimum_new_node_count=1,
        allowed_new_node_count=3,
        minimum_new_edge_count=1,
        allowed_new_edge_count=6,
        added_edge_anchor_node_ids=anchors,
        enforce_added_edge_contract_label=False,
    )
    plan = generation._connection_addition_plan(
        permissions,
        {node_id: index for index, node_id in enumerate(accepted_ids)},
        components_accepted=True,
        saved_component_ids=["n1", "n2", "n3", "n4", "n5", "n6"],
    )
    assert plan["anchor_component_indexes"] == expected_anchors
    assert plan["accepted_addition_indexes"] == expected_additions
    assert plan["component_addition_count"] == len(expected_additions)
    assert permissions["added_edge_anchor_node_ids"] == anchors


@pytest.mark.parametrize("mode", ["exact", "attachment"])
def test_connection_plan_identifies_reordered_addition_for_scoped_edits(mode):
    permissions = _permissions(
        connection_addition_mode=mode,
        allowed_new_node_count=1,
        allowed_new_edge_count=1,
        added_edge_anchor_node_ids=["n1"],
        enforce_added_edge_contract_label=mode == "exact",
        connection_addition_obligations=[
            {
                "source": "n1",
                "target": "$new_node_1",
                "required_contract": "requests validation",
            }
        ],
    )
    plan = generation._connection_addition_plan(
        permissions,
        {"n3": 0, "n2": 1, "n1": 2},
        components_accepted=True,
        saved_component_ids=["n1", "n2"],
    )
    assert plan["accepted_addition_indexes"] == [0]
    assert plan["anchor_component_indexes"] == [2]
    assert plan["obligations"] == [
        {
            "source": {"component_index": 2},
            "target": {"addition_index": 0},
            "required_contract": "requests validation",
        }
    ]


@pytest.mark.parametrize(
    "saved_ids,accepted_ids,permissions_change",
    [
        (None, ["n1", "n2"], {}),
        (["n1", "n1"], ["n1", "n2"], {}),
        (["n1"], ["n1"], {}),
        (["n1"], ["n1", "n2", "n3", "n4"], {}),
        (["n1"], ["n1", "n2"], {"minimum_new_node_count": True}),
        (["n1"], ["n1", "n2"], {"allowed_new_node_count": False}),
        (["n1"], ["n1", "n2"], {"added_edge_anchor_node_ids": ["n2"]}),
    ],
)
def test_connection_extension_rejects_invalid_baseline_counts_and_new_node_anchors(
    saved_ids, accepted_ids, permissions_change
):
    permissions = _permissions(
        connection_addition_mode="extension",
        minimum_new_node_count=1,
        allowed_new_node_count=2,
        minimum_new_edge_count=1,
        allowed_new_edge_count=2,
        added_edge_anchor_node_ids=["n1"],
    )
    permissions.update(permissions_change)
    with pytest.raises(
        generation.StagedGenerationError, match="edit_connection_plan_invalid"
    ):
        generation._connection_addition_plan(
            permissions,
            {node_id: index for index, node_id in enumerate(accepted_ids)},
            components_accepted=True,
            saved_component_ids=saved_ids,
        )


@pytest.mark.asyncio
async def test_connection_extension_prompt_retains_restricted_anchors_and_only_new_ids(
    monkeypatch,
):
    calls = []
    addition = {
        "source_index": 1,
        "target_index": 6,
        "label": "requests approval",
        "flow": 400,
        "sync": 500,
    }

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "candidate": {"updates": {}, "additions": [addition]},
                "clarification_questions": [],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    accepted = [
        {**_accepted_components()[1], "id": f"n{index + 1}", "index": index}
        for index in range(7)
    ]
    permissions = _permissions(
        connection_addition_mode="extension",
        minimum_new_node_count=1,
        allowed_new_node_count=3,
        minimum_new_edge_count=1,
        allowed_new_edge_count=6,
        added_edge_anchor_node_ids=["n2", "n3", "n5", "n6"],
        enforce_added_edge_contract_label=False,
    )
    result = await generation.generate_connection_candidate(
        request="Add approval inside the existing service.",
        resolved_maturity="prototype",
        write_set=generation.create_write_set(component_limit=9, edge_limit=12),
        upstream_fingerprint="a" * 64,
        accepted_components=accepted,
        saved_component_ids=["n1", "n2", "n3", "n4", "n5", "n6"],
        accepted_context=_accepted_context(),
        base_connections=[],
        edit_permissions=permissions,
    )
    prompt = json.loads(calls[0]["prompt"].split("\nINPUT\n", 1)[1])
    plan = prompt["connection_addition_plan"]
    assert plan["anchor_component_indexes"] == [1, 2, 4, 5]
    assert plan["accepted_addition_indexes"] == [6]
    assert plan["component_addition_count"] == 1
    assert result["wire"]["edges"] == [addition]


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("expansion", [False, True])
def test_service_expansion_connection_guidance_is_scoped(stage, expansion):
    prompt, _ = generation._attempt_prompt(
        stage=stage,
        request="Expand the release service.",
        state={"service_expansion": {"target_service_ids": ["n2"]}}
        if expansion
        else {},
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        architecture_context=_architecture_context() if stage == "components" else None,
        accepted_components=_accepted_components() if stage == "connections" else None,
        accepted_context=generation._accepted_context(_accepted_context())
        if stage == "connections"
        else None,
    )
    for guidance in (
        "Match each label to the actual sender and recipient",
        "delegated reply must name the relay and forwarded origin",
        "carry the exact authorized payload and stable operation ID through every hop",
        "Retained parent edges satisfy this only when their explicit contracts carry those values",
        "use allowed new internal-to-anchor exchanges",
        "request authoritative state and return the correlated state to the reconciliation owner",
        "Preserve locked parent records. Containment does not imply runtime forwarding",
    ):
        assert (guidance in prompt) == (expansion and stage == "connections")


@pytest.mark.parametrize("maximum", [1, 2])
def test_component_edit_additions_provider_schema_requires_owned_component_parent(
    maximum,
):
    from adapters.llm_adapter import _anthropic_response_schema

    schema = generation.component_generation_schema(_write_set())
    delta = generation._component_edit_delta(
        _edit_base(),
        _permissions(allowed_new_node_count=maximum),
        schema,
    )
    raw_parent = delta.schema["properties"]["additions"]["items"]["anyOf"][1][
        "properties"
    ]["parent_index"]
    original_parent = schema["properties"]["components"]["items"]["properties"][
        "parent_index"
    ]
    assert raw_parent["minimum"] == original_parent["minimum"]
    assert raw_parent["maximum"] == original_parent["maximum"]
    branches = _anthropic_response_schema(delta.schema)["properties"]["additions"][
        "items"
    ]["anyOf"]
    non_component, component = branches
    assert non_component["properties"]["type"]["enum"] == [
        code for code in generation.NODE_TYPE_CODES if code != 109
    ]
    assert non_component["properties"]["parent_index"] == {"type": "null"}
    assert "parent_index" not in non_component["required"]
    assert component["properties"]["type"]["enum"] == [109]
    assert "parent_index" in component["required"]
    assert component["properties"]["parent_index"] == {
        "type": "integer",
        "enum": [0] if maximum == 1 else [0, 2, 3],
    }
    assert 1 not in component["properties"]["parent_index"]["enum"]
    assert set(component["required"]) == set(
        schema["properties"]["components"]["items"]["required"]
    ) | {"parent_index"}
    assert (
        generation._generation_schema_version("components", delta.schema)
        == "staged_components_delta_v7"
    )
    assert (
        generation._generation_schema_version(
            "components", generation._component_create_response_schema(schema)
        )
        == generation._COMPONENT_SCHEMA_VERSION
    )


@pytest.mark.parametrize("parent", [None, True, 1, "0"])
def test_component_edit_owned_addition_rejects_invalid_parent_without_remapping(parent):
    delta = generation._component_edit_delta(
        _edit_base(),
        _permissions(allowed_new_node_count=1),
        generation.component_generation_schema(_write_set()),
    )
    addition = {
        **_component_wire()["components"][0],
        "label": "Internal coordinator",
        "type": 109,
        "parent_index": parent,
    }
    response = {
        "additions": [addition],
        "updates": {},
        "capabilities": delta.base["capabilities"],
    }
    assembled = delta.assemble(json.dumps(response))
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ):
        generation._parse_component_wire(json.dumps(assembled), component_limit=5)
    del addition["parent_index"]
    assembled = delta.assemble(json.dumps(response))
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ):
        generation._parse_component_wire(json.dumps(assembled), component_limit=5)


def test_component_edit_additions_omit_component_branch_without_possible_parent():
    base = _edit_base()
    base["components"][0]["type"] = "gateway"
    delta = generation._component_edit_delta(
        base,
        _permissions(allowed_new_node_count=1),
        generation.component_generation_schema(_write_set()),
    )
    branches = delta.schema["properties"]["additions"]["items"]["anyOf"]
    assert len(branches) == 1
    assert 109 not in branches[0]["properties"]["type"]["enum"]


@pytest.mark.parametrize("new_parent", [False, True])
def test_component_edit_additions_preserve_retained_or_forward_new_service_owner(
    new_parent,
):
    base = _edit_base()
    if new_parent:
        base["components"][0]["type"] = "gateway"
    maximum = 2 if new_parent else 1
    delta = generation._component_edit_delta(
        base,
        _permissions(allowed_new_node_count=maximum),
        generation.component_generation_schema(_write_set()),
    )
    child = {
        **_component_wire()["components"][0],
        "label": "Internal coordinator",
        "type": 109,
        "parent_index": 3 if new_parent else 0,
    }
    additions = [child]
    if new_parent:
        additions.append({**_component_wire()["components"][0], "label": "New service"})
    assembled = delta.assemble(
        json.dumps(
            {
                "additions": additions,
                "updates": {},
                "capabilities": base["capabilities"],
            }
        )
    )
    parsed = generation._parse_component_wire(json.dumps(assembled), component_limit=5)
    assert parsed["components"][2]["parent_index"] == (3 if new_parent else 0)


def test_component_edit_parent_schema_uses_retained_service_position_after_removal():
    wire = _owned_component_wire()
    base = {
        **wire,
        "components": [
            {
                **row,
                "type": generation.NODE_TYPE_CODES[row["type"]],
                "group_kind": "runtime",
                "model_index": index,
                "server_id": f"n{index}",
            }
            for index, row in enumerate(wire["components"])
        ],
    }
    delta = generation._component_edit_delta(
        base,
        _permissions(removable_node_ids=["n1"], allowed_new_node_count=1),
        generation.component_generation_schema(_write_set()),
    )
    assert delta.schema["properties"]["additions"]["items"]["anyOf"][1]["properties"][
        "parent_index"
    ]["enum"] == [1]
    addition = {**wire["components"][3], "label": "New internal", "parent_index": 1}
    parsed = generation._parse_component_wire(
        json.dumps(
            delta.assemble(
                json.dumps(
                    {
                        "additions": [addition],
                        "updates": {},
                        "capabilities": base["capabilities"],
                    }
                )
            )
        ),
        component_limit=5,
    )
    assert (
        parsed["components"][2]["parent_index"]
        == parsed["components"][3]["parent_index"]
        == 1
    )


def test_component_edit_parent_enum_stays_within_original_bounds_after_normalization():
    from adapters.llm_adapter import _anthropic_response_schema

    schema = generation.component_generation_schema(
        generation.create_write_set(component_limit=3, edge_limit=4)
    )
    delta = generation._component_edit_delta(
        _edit_base(),
        _permissions(allowed_new_node_count=4),
        schema,
    )
    parent = _anthropic_response_schema(delta.schema)["properties"]["additions"][
        "items"
    ]["anyOf"][1]["properties"]["parent_index"]
    assert parent == {"type": "integer", "enum": [0, 2]}


@pytest.mark.asyncio
async def test_component_extension_telemetry_versions_actual_wrapped_edit_schema(
    monkeypatch,
):
    calls = []
    addition = {
        **_component_wire()["components"][0],
        "label": "Internal coordinator",
        "type": 109,
        "parent_index": 0,
    }

    async def stream(**kwargs):
        calls.append(kwargs)
        return _response(
            {
                "candidate": {
                    "additions": [addition],
                    "updates": {},
                    "capabilities": _edit_base()["capabilities"],
                },
                "clarification_questions": [],
            }
        )

    monkeypatch.setattr(generation, "stream_structured_llm", stream)
    result = await generation.generate_component_candidate(
        request="Expand the service.",
        resolved_maturity="prototype",
        architecture_context=_architecture_context(),
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        base_components=_edit_base(),
        edit_permissions=_permissions(
            allowed_new_node_count=1, connection_addition_mode="extension"
        ),
    )
    assert result["wire"]["components"][2]["parent_index"] == 0
    candidate_schema = calls[0]["response_schema"]["properties"]["candidate"]["anyOf"][
        0
    ]
    assert "anyOf" in candidate_schema["properties"]["additions"]["items"]
    assert (
        calls[0]["telemetry"]["metadata"]["schema_version"]
        == "staged_components_edit_response_v2"
    )


@pytest.mark.parametrize("target_index,updated_type", [(1, 101), (1, 102), (0, 102)])
def test_component_edit_parent_eligibility_includes_authorized_type_updates(target_index, updated_type):
    base = _edit_base()
    delta = generation._component_edit_delta(
        base,
        _permissions(
            allowed_new_node_count=1,
            editable_node_fields={f"n{target_index + 1}": ["type"]},
        ),
        generation.component_generation_schema(_write_set()),
    )
    allowed = delta.schema["properties"]["additions"]["items"]["anyOf"][1][
        "properties"
    ]["parent_index"]["enum"]
    assert allowed == ([0, 1] if target_index == 1 else [0])
    child = {
        **_component_wire()["components"][0],
        "label": "Internal coordinator",
        "type": 109,
        "parent_index": target_index,
    }
    assembled = delta.assemble(
        json.dumps(
            {
                "additions": [child],
                "updates": {f"slot_{target_index}": {"type": updated_type}},
                "capabilities": base["capabilities"],
            }
        )
    )
    if updated_type == 101:
        parsed = generation._parse_component_wire(
            json.dumps(assembled), component_limit=5
        )
        assert parsed["components"][target_index]["type"] == 101
        assert parsed["components"][2]["parent_index"] == target_index
    else:
        with pytest.raises(generation.StagedGenerationError) as caught:
            generation._parse_component_wire(json.dumps(assembled), component_limit=5)
        assert caught.value.diagnostic_reason == "component_parent_invalid"



@pytest.mark.asyncio
async def test_high_service_expansion_uses_factored_schema_and_native_delta(monkeypatch):
    delta = generation._component_edit_delta(
        _edit_base(),
        _permissions(editable_node_fields={"n1": ["label"], "n2": ["label"]}),
        generation.component_generation_schema(_write_set()),
    )
    schema = json.loads(json.dumps(delta.schema))
    response = delta.extract(delta.base)
    captured = []

    async def expand(**kwargs):
        captured.append(kwargs)
        return _response(response)

    monkeypatch.setattr(generation, "expand_application_services", expand)
    raw = await generation._run_generation(
        stage="components", prompt="Inspect the declared high-complexity expansion.",
        schema=delta.schema, prompt_fingerprint="a" * 64,
        state={"service_expansion": {"complexity": "high"}}, attempt=1,
        upstream_fingerprint="b" * 64, write_set=_write_set(),
        timeout_seconds=130, max_output_tokens=65536,
    )
    assert len(captured) == 1
    expected = generation._provider_generation_schema(schema)
    assert captured[0]["response_schema"] == expected
    assert "$defs" in expected
    assert delta.schema == schema
    assert delta.assemble(raw) == delta.base
    response["updates"]["slot_0"]["unknown"] = "Invalid field"
    with pytest.raises(generation.StagedGenerationError):
        delta.assemble(json.dumps(response))


def test_component_metadata_bounds_survive_provider_transformation_and_repairs():
    from adapters.llm_adapter import _anthropic_response_schema

    canonical = generation.component_generation_schema(_write_set())
    schemas = [canonical]
    rejected = _component_wire()
    rejected["components"].append(
        {**rejected["components"][0], "label": "Request processor"}
    )
    for recovery_mode in (False, True):
        delta = generation._semantic_correction_delta(
            stage="components",
            maturity="prototype",
            write_set=_write_set(),
            attempt=1,
            rejected_candidate=rejected,
            findings=[
                {
                    "code": "objective_fidelity",
                    "path": "components",
                    "rule": "semantic_gate",
                    "record_indexes": [],
                }
            ],
            schema=canonical,
            recovery_mode=recovery_mode,
        )
        assert delta is not None
        schemas.append(delta.schema)

    for schema in schemas:
        wrapped = generation._component_create_response_schema(schema)
        original = json.loads(json.dumps(wrapped))
        provider = generation._provider_generation_schema(wrapped)
        transformed = _anthropic_response_schema(provider)
        assert wrapped == original
        if "updates" in schema["properties"]:
            assert provider["$defs"]
            for definition in transformed["$defs"].values():
                slot = definition["anyOf"][0]
                assert slot["properties"]["label"]["description"] == (
                    f"At most {contract.COMPONENT_LABEL_MAX_CHARS} characters."
                )
                assert slot["properties"]["group_label"]["description"] == (
                    f"At most {contract.GROUP_LABEL_MAX_CHARS} characters."
                )
        fields = transformed["properties"]["candidate"]["anyOf"][0]["properties"]
        assert fields["title"]["description"] == (
            f"At most {contract.TITLE_MAX_CHARS} characters."
        )
        assert "maxLength" not in fields["title"]
        assert fields["assumptions"]["description"] == (
            f"At most {generation._MAX_ASSUMPTIONS} assumptions."
        )
        assert "maxItems" not in fields["assumptions"]
        assert fields["assumptions"]["items"]["description"] == (
            f"At most {contract.ASSUMPTION_MAX_CHARS} characters."
        )
        record = (
            fields["components"]["items"]
            if "components" in fields
            else fields["additions"]["items"]
        )
        for name, limit in (
            ("label", contract.COMPONENT_LABEL_MAX_CHARS),
            ("group_label", contract.GROUP_LABEL_MAX_CHARS),
        ):
            assert record["properties"][name]["description"] == f"At most {limit} characters."
            assert "maxLength" not in record["properties"][name]
        questions = transformed["properties"]["clarification_questions"]["items"]
        assert questions["description"] == (
            f"At most {generation._CLARIFICATION_QUESTION_MAX_CHARS} characters."
        )
        assert "maxLength" not in questions

    boundary = {**_component_wire(), "title": "x" * contract.TITLE_MAX_CHARS}
    assert generation._parse_component_wire(
        json.dumps(boundary), component_limit=4
    )["title"] == boundary["title"]
    with pytest.raises(generation.StagedGenerationError) as error:
        generation._parse_component_wire(
            json.dumps({**boundary, "title": boundary["title"] + "x"}),
            component_limit=4,
        )
    assert error.value.diagnostic_reason == "title_length"
    assert error.value.diagnostic_path == "title"


@pytest.mark.parametrize("oversized", [False, True])
def test_exchange_correction_prompt_preserves_rejected_input_bound(oversized):
    delta, original, _, write_set, findings = _paired_recovery()
    rejected = original if not oversized else {"padding": "x" * 48001}
    arguments = dict(
        stage="connections", request="Repair the tool return",
        resolved_maturity="prototype", write_set=write_set,
        upstream_fingerprint="a" * 64, attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=[], gate_findings=findings, base=None,
        rejected_candidate=rejected, accepted_components=_accepted_components(),
        accepted_context=generation._accepted_context(_accepted_context()),
        correction_delta=delta, recovery_mode=True,
    )
    if oversized:
        with pytest.raises(
            generation.StagedGenerationError, match="generation_base_too_large"
        ):
            generation._attempt_prompt(**arguments)
    else:
        prompt, _ = generation._attempt_prompt(**arguments)
        payload = json.loads(prompt.split("\nINPUT\n", 1)[1])
        assert "rejected_candidate" not in payload
        assert payload["correction_exchanges"] == delta.base["exchanges"]


def test_global_connection_correction_keeps_expanded_rejected_candidate():
    delta, original, _, write_set, findings = _paired_recovery(global_finding=True)
    assert delta.record_key == "edges"
    prompt, _ = generation._attempt_prompt(
        stage="connections", request="Repair all contracts",
        resolved_maturity="prototype", write_set=write_set,
        upstream_fingerprint="a" * 64, attempt=1,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        structural_findings=[], gate_findings=findings, base=None,
        rejected_candidate=original, accepted_components=_accepted_components(),
        accepted_context=generation._accepted_context(_accepted_context()),
        correction_delta=delta, recovery_mode=True,
    )
    payload = json.loads(prompt.split("\nINPUT\n", 1)[1])
    assert payload["rejected_candidate"] == original
    assert "correction_exchanges" not in payload
    assert " The rejected_candidate is preserved by the server. Return only the " in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage,attempt",
    [
        ("components", 2), ("connections", 3),
        ("connections", 1.5), ("connections", True), ("components", False),
    ],
)
async def test_generation_rejects_attempt_beyond_configured_stage_limit(
    monkeypatch, stage, attempt,
):
    async def generate(**kwargs):
        raise AssertionError("out-of-range attempts must not call the provider")

    monkeypatch.setattr(generation, "_run_generation", generate)
    arguments = dict(
        request="Repair the request path.",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        attempt=attempt,
        prior_prompt_fingerprint="b" * 64,
        prior_write_set_fingerprint=generation._fingerprint(_write_set()),
        structural_findings=[{"code": "failed", "path": stage, "rule": "shape"}],
    )
    if stage == "components":
        arguments["architecture_context"] = _architecture_context()
        generate_candidate = generation.generate_component_candidate
    else:
        arguments["accepted_components"] = _accepted_components()
        arguments["accepted_context"] = _accepted_context()
        generate_candidate = generation.generate_connection_candidate
    with pytest.raises(
        generation.StagedGenerationError, match="correction_attempt_limit_exceeded"
    ):
        await generate_candidate(**arguments)


@pytest.mark.parametrize(
    "source,target,allowed",
    [
        (16, 9, False),
        (17, 9, False),
        (1, 2, False),
        (1, 16, True),
        (16, 1, True),
        (16, 17, True),
    ],
)
def test_extension_addition_schema_limits_endpoints_to_plan(source, target, allowed):
    components = [{"id": f"n{i + 1}", "index": i} for i in range(18)]
    base = [
        {
            "source_index": 1,
            "target_index": 2,
            "label": "saved",
            "flow": 400,
            "sync": 500,
        }
    ]
    permissions = _permissions(
        connection_addition_mode="extension",
        allowed_new_edge_count=2,
        minimum_new_edge_count=0,
    )
    delta = generation._connection_edit_delta(
        base,
        permissions,
        generation.connection_generation_schema(_write_set()),
        components,
        connection_addition_plan={
            "anchor_component_indexes": [1, 2],
            "accepted_addition_indexes": [16, 17],
        },
    )
    branches = delta.schema["properties"]["additions"]["items"]["anyOf"]
    assert (
        any(
            source in branch["properties"]["source_index"]["enum"]
            and target in branch["properties"]["target_index"]["enum"]
            for branch in branches
        )
        is allowed
    )
    for branch in branches:
        assert branch["additionalProperties"] is False
        assert branch["required"] == [
            "source_index",
            "target_index",
            "label",
            "flow",
            "sync",
        ]
        assert branch["properties"]["source_index"]["type"] == "integer"
        assert branch["properties"]["target_index"]["type"] == "integer"
    if allowed:
        edge = {
            **base[0],
            "source_index": source,
            "target_index": target,
            "label": "new",
        }
        wire = delta.assemble(json.dumps({"updates": {}, "additions": [edge]}))
        assert wire["edges"] == [base[0], edge]
        generation._parse_connection_wire(
            json.dumps(wire), accepted_components=components, edge_limit=10
        )
    assert delta.base["edges"] == base


@pytest.mark.parametrize("plan", [None, {"anchor_component_indexes": [1]}])
def test_extension_addition_schema_requires_accepted_plan(plan):
    with pytest.raises(
        generation.StagedGenerationError, match="edit_connection_plan_invalid"
    ):
        generation._connection_edit_delta(
            [],
            _permissions(connection_addition_mode="extension"),
            generation.connection_generation_schema(_write_set()),
            _accepted_components(),
            connection_addition_plan=plan,
        )


def test_extension_without_new_components_has_no_addition_capacity():
    delta = generation._connection_edit_delta(
        [],
        _permissions(
            connection_addition_mode="extension",
            allowed_new_edge_count=2,
            minimum_new_edge_count=0,
        ),
        generation.connection_generation_schema(_write_set()),
        _accepted_components(),
        connection_addition_plan={
            "anchor_component_indexes": [0],
            "accepted_addition_indexes": [],
        },
    )
    assert delta.schema["properties"]["additions"]["maxItems"] == 0
    assert "anyOf" not in delta.schema["properties"]["additions"]["items"]
    assert delta.assemble('{"updates":{},"additions":[]}') == {"edges": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["components", "connections"])
async def test_service_expansion_parent_interfaces_survive_author_correction(
    monkeypatch, stage
):
    calls = []
    addition = {**_component_wire()["components"][0], "type": 109, "parent_index": 0}
    edge = {
        "source_index": 0,
        "target_index": 2,
        "label": "process request",
        "flow": 400,
        "sync": 500,
    }

    async def generate(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "candidate": {
                    "updates": {},
                    "additions": [addition if stage == "components" else edge],
                    **(
                        {"capabilities": _edit_base()["capabilities"]}
                        if stage == "components"
                        else {}
                    ),
                },
                "clarification_questions": [],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", generate)
    permissions = _permissions(
        connection_addition_mode="extension",
        minimum_new_node_count=1,
        allowed_new_node_count=1,
        minimum_new_edge_count=1,
        allowed_new_edge_count=2,
        added_edge_anchor_node_ids=["n2", "n1"],
        enforce_added_edge_contract_label=False,
        service_expansion_target_ids=["n1"],
        service_expansion_anchors={"n1": ["n2", "n1"]},
    )
    kwargs = dict(
        request="Expand the service.",
        resolved_maturity="prototype",
        write_set=_write_set(),
        upstream_fingerprint="a" * 64,
        edit_permissions=permissions,
        state={"service_expansion": {"target_service_ids": ["n1"]}},
    )
    if stage == "components":
        kwargs.update(
            base_components=_edit_base(),
            baseline_connections=[],
            architecture_context=_architecture_context(),
        )
        author = generation.generate_component_candidate
    else:
        kwargs.update(
            accepted_components=[
                {
                    "id": "n1",
                    "index": 0,
                    "type": 101,
                    "responsibility": "Processes requests.",
                },
                {
                    "id": "n2",
                    "index": 1,
                    "type": 102,
                    "responsibility": "Stores results.",
                },
                {
                    "id": "new",
                    "index": 2,
                    "type": 109,
                    "parent_index": 0,
                    "responsibility": "Processes requests.",
                },
            ],
            saved_component_ids=["n1", "n2"],
            base_connections=[],
            accepted_context=_accepted_context(),
        )
        author = generation.generate_connection_candidate
    first = await author(**kwargs)
    await author(
        **kwargs,
        attempt=1,
        prior_prompt_fingerprint=first["prompt_fingerprint"],
        prior_write_set_fingerprint=generation._fingerprint(_write_set()),
        rejected_candidate=first["wire"],
        structural_findings=[
            {
                "code": "invalid_contract",
                "path": stage,
                "rule": "contract_validation",
                "reason": "An internal connection must remain within its parent interface.",
            }
        ],
    )
    plans = [
        json.loads(call["prompt"].split("\nINPUT\n", 1)[1])["connection_addition_plan"]
        for call in calls
    ]
    assert plans[0] == plans[1]
    assert plans[0]["parent_interfaces"] == [
        {"parent_index": 0, "anchor_component_indexes": [0, 1]}
    ]
    assert calls[0]["schema"] == calls[1]["schema"]
    for call in calls:
        assert (
            "union of anchors does not grant cross-parent authority" in call["prompt"]
        )
        assert "every affected writer and consumer" in call["prompt"]
        assert "compatible with the frozen graph" in call["prompt"]


def test_service_expansion_parent_interfaces_use_numeric_order_and_actual_ids():
    permissions = _permissions(
        connection_addition_mode="extension",
        allowed_new_node_count=2,
        minimum_new_edge_count=1,
        allowed_new_edge_count=6,
        added_edge_anchor_node_ids=["n10", "n2", "shared"],
        enforce_added_edge_contract_label=False,
        service_expansion_target_ids=["n2", "n10"],
        service_expansion_anchors={"n2": ["shared", "n2"], "n10": ["shared", "n10"]},
    )
    plan = generation._connection_addition_plan(
        permissions, {"shared": 2, "n2": 1, "n10": 0}
    )
    assert plan["parent_interfaces"] == [
        {"parent_index": 0, "anchor_component_indexes": [0, 2]},
        {"parent_index": 1, "anchor_component_indexes": [1, 2]},
    ]
    assert permissions["service_expansion_anchors"]["n2"] == ["shared", "n2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"service_expansion_anchors": None},
        {"service_expansion_target_ids": None},
        {"service_expansion_target_ids": ["unknown"]},
        {"service_expansion_target_ids": ["n1", "n1"]},
        {"service_expansion_anchors": {"unknown": ["n1", "n2"]}},
        {"service_expansion_anchors": {"n1": ["n2"]}},
        {"service_expansion_anchors": {"n1": ["n1", "unknown"]}},
        {"service_expansion_anchors": {"n1": ["n1", "n1", "n2"]}},
        {"service_expansion_anchors": {"n1": ["n1"]}},
    ],
)
async def test_malformed_service_expansion_parent_scope_prevents_provider_call(
    monkeypatch, change
):
    async def generate(**kwargs):
        pytest.fail("Malformed parent interfaces must fail before the provider call")

    monkeypatch.setattr(generation, "_run_generation", generate)
    permissions = _permissions(
        connection_addition_mode="extension",
        allowed_new_node_count=1,
        minimum_new_edge_count=1,
        allowed_new_edge_count=2,
        added_edge_anchor_node_ids=["n1", "n2"],
        enforce_added_edge_contract_label=False,
        service_expansion_target_ids=["n1"],
        service_expansion_anchors={"n1": ["n1", "n2"]},
    )
    permissions.update(change)
    with pytest.raises(
        generation.StagedGenerationError, match="edit_connection_plan_invalid"
    ):
        await generation.generate_component_candidate(
            request="Expand the service.",
            resolved_maturity="prototype",
            architecture_context=_architecture_context(),
            write_set=_write_set(),
            upstream_fingerprint="a" * 64,
            base_components=_edit_base(),
            edit_permissions=permissions,
        )
