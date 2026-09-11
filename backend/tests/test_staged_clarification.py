import copy
import json
from unittest.mock import AsyncMock

import pytest

from agent import staged_graph_workflow as workflow
from agent.nodes import staged_graph_generation as generation


def _candidate():
    return {
        "title": "Request processing",
        "assumptions": [],
        "root_index": 0,
        "capabilities": {
            "external_effects": False,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
        "components": [
            {
                "label": "Request service",
                "type": 101,
                "responsibility": "Processes requests.",
                "group_label": "Runtime",
                "group_kind": 600,
                "primary_flow_member": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"candidate": None, "clarification_questions": []},
        {"candidate": _candidate(), "clarification_questions": ["What is the goal?"]},
        {"candidate": None, "clarification_questions": "What is the goal?"},
        {"candidate": None, "clarification_questions": [None]},
        {"candidate": None, "clarification_questions": [1]},
        {"candidate": None, "clarification_questions": [""]},
        {"candidate": None, "clarification_questions": ["   "]},
        {"candidate": None, "clarification_questions": ["x" * 241]},
        {"candidate": None, "clarification_questions": ["Which workflow?"] * 4},
        {"candidate": None, "clarification_questions": ["What goal?"], "extra": True},
        {"clarification_questions": ["What goal?"]},
    ],
)
def test_component_response_rejects_invalid_clarification(payload):
    with pytest.raises(generation.StagedGenerationError):
        generation._parse_component_response(json.dumps(payload), component_limit=4)


def test_component_response_retains_legacy_candidate_validation():
    candidate = _candidate()
    assert generation._parse_component_response(
        json.dumps({"candidate": candidate, "clarification_questions": []}),
        component_limit=4,
    ) == {
        "wire": generation._parse_component_wire(
            json.dumps(candidate), component_limit=4
        )
    }
    candidate["components"][0]["type"] = 999
    with pytest.raises(
        generation.StagedGenerationError, match="component_wire_invalid"
    ):
        generation._parse_component_response(
            json.dumps({"candidate": candidate, "clarification_questions": []}),
            component_limit=4,
        )


def test_component_response_accepts_bounded_trimmed_questions():
    assert generation._parse_component_response(
        json.dumps(
            {
                "candidate": None,
                "clarification_questions": [
                    " What goal? ",
                    "x" * 240,
                    "Which workflow?",
                ],
            }
        ),
        component_limit=4,
    ) == {"clarification_questions": ["What goal?", "x" * 240, "Which workflow?"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prior_graph",
    [None, {"nodes": [{"id": "prior"}], "edges": [], "title": "Existing graph"}],
)
async def test_create_clarification_uses_one_generation_and_no_downstream_calls(
    monkeypatch, prior_graph
):
    requests = []

    async def component_response(**kwargs):
        requests.append(kwargs)
        return json.dumps(
            {
                "candidate": None,
                "clarification_questions": [
                    "What business outcome should this system deliver?"
                ],
            }
        )

    monkeypatch.setattr(generation, "_run_generation", component_response)
    downstream = []
    for name in (
        "review_components",
        "review_connections",
        "generate_connection_candidate",
        "_render",
    ):
        boundary = AsyncMock(
            side_effect=AssertionError(f"unexpected downstream call: {name}")
        )
        monkeypatch.setattr(workflow, name, boundary)
        downstream.append(boundary)
    contract = (
        {"maturity": "prototype", "version": "prior-contract"} if prior_graph else None
    )
    state = {
        "request_id": "clarify-request",
        "user_message": "Build an agent for my business.",
        "complexity": "prototype",
        "graph_intent": "create",
        "graph_operation": {
            "kind": "create",
            "status": "candidate",
            "failure_code": None,
        },
        "graph_data": prior_graph,
        "approved_graph_data": prior_graph,
        "graph_contract": contract,
        "approved_graph_contract": contract,
        "evidence_bundle": {},
    }
    before = copy.deepcopy(state)

    result = await workflow.run_staged_graph_pipeline(state)

    assert len(requests) == 1
    assert requests[0]["schema"]["required"] == ["candidate", "clarification_questions"]
    prompt = requests[0]["prompt"]
    assert "business goal or actual workflow is missing" in prompt
    assert "educational diagram with an explicit subject" in prompt
    assert "reasonable stated assumptions suffice" in prompt
    assert all(boundary.await_count == 0 for boundary in downstream)
    assert result["graph_operation"] == {
        "kind": "create",
        "status": "needs_clarification",
        "failure_code": None,
    }
    assert result["clarification_questions"] == [
        "What business outcome should this system deliver?"
    ]
    assert result["graph_changed"] is False
    assert result["graph_publication"] == ("unchanged" if prior_graph else "none")
    assert result["graph_data"] == prior_graph
    assert result["approved_graph_data"] == prior_graph
    assert result["graph_contract"] == contract
    assert result["approved_graph_contract"] == contract
    assert state == before


@pytest.mark.asyncio
async def test_scoped_edit_schema_and_parser_reject_clarification(monkeypatch):
    calls = []

    async def component_response(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {"candidate": None, "clarification_questions": ["What goal?"]}
        )

    monkeypatch.setattr(generation, "_run_generation", component_response)
    candidate = _candidate()
    base = {
        **candidate,
        "components": [
            {
                **candidate["components"][0],
                "server_id": "n1",
                "model_index": 0,
                "type": "service",
                "group_kind": "runtime",
            }
        ],
    }
    permissions = {
        "editable_node_fields": {"n1": ["label"]},
        "removable_node_ids": [],
        "allowed_new_node_count": 0,
        "editable_edges": [],
        "editable_edge_fields": {},
        "removable_edge_ids": [],
        "allowed_new_edge_count": 0,
        "added_edge_anchor_node_ids": [],
        "connection_addition_obligations": [],
        "editable_composition_fields": [],
    }

    with pytest.raises(generation.StagedGenerationError, match="schema_invalid"):
        await generation.generate_component_candidate(
            request="Rename Request service to Request processor.",
            resolved_maturity="prototype",
            architecture_context="The service processes requests.",
            write_set=generation.exact_edit_write_set(
                component_ids=["n1"], edge_ids=[]
            ),
            upstream_fingerprint="a" * 64,
            base_components=base,
            edit_permissions=permissions,
        )

    assert len(calls) == 1
    assert "clarification_questions" not in calls[0]["schema"]["properties"]
    assert "clarification_questions" not in calls[0]["prompt"]
