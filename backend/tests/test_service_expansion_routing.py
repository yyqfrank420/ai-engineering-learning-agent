"""Service expansion selects validated scope before using a specialist model."""

import json

import pytest

from agent import deadlines
from agent.nodes import orchestrator_node as orchestrator
from agent.nodes import staged_graph_generation as generation
from agent.stream_utils import StructuredLLMResponse
from agent.tools import service_expansion_tool as expansion_tool
from config import settings


@pytest.fixture
def state():
    async def send(_event):
        pass

    return {
        "user_message": "Expand the tutoring service",
        "history": [],
        "send": send,
        "graph_data": {
            "title": "Learning platform",
            "design_origin": "applied",
            "version": 1,
            "nodes": [
                {"id": "tutor", "label": "Tutoring service", "type": "service"},
                {"id": "release", "label": "Release service", "type": "service"},
                {"id": "store", "label": "Material store", "type": "datastore"},
                {"id": "client", "label": "Student app", "type": "client"},
                {"id": "retrieve", "label": "Retrieval process", "type": "service"},
            ],
            "edges": [],
            "groups": [],
            "sequence": [],
        },
    }


def response(text, finish_reason="end_turn"):
    return StructuredLLMResponse(text, finish_reason, 1, 1, "mock", "mock")


def mock_plan(monkeypatch, plan, finish_reason="end_turn"):
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs)
        return response(
            plan if isinstance(plan, str) else json.dumps(plan), finish_reason
        )

    monkeypatch.setattr(expansion_tool, "stream_structured_llm", provider)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,targets",
    [
        ("Expand the tutoring service", ["tutor"]),
        ("Expand all individual services", ["tutor", "release"]),
    ],
)
@pytest.mark.parametrize("complexity", ["low", "high"])
async def test_planner_preserves_named_and_all_service_scope(
    monkeypatch, state, query, targets, complexity
):
    calls = mock_plan(
        monkeypatch,
        {
            "operation": "expand",
            "complexity": complexity,
            "target_service_ids": targets,
        },
    )
    plan = await expansion_tool.plan_service_expansion(state, query)
    assert plan == {
        "request": query,
        "complexity": complexity,
        "target_service_ids": targets,
    }
    call = calls[0]
    assert call["model"] == settings.orchestrator_model
    assert call["effort"] == "low"
    assert call["provider_attempt_limit"] == 1
    assert json.loads(call["messages"][0]["content"])["request"] == query
    assert set(
        call["response_schema"]["properties"]["target_service_ids"]["items"]["enum"]
    ) == {"tutor", "release", "retrieve"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan,finish_reason",
    [
        (
            {
                "operation": "expand",
                "complexity": "high",
                "target_service_ids": ["unknown"],
            },
            "end_turn",
        ),
        (
            {
                "operation": "expand",
                "complexity": "high",
                "target_service_ids": ["store"],
            },
            "end_turn",
        ),
        (
            {
                "operation": "expand",
                "complexity": "high",
                "target_service_ids": ["tutor", "tutor"],
            },
            "end_turn",
        ),
        (
            {"operation": "expand", "complexity": "high", "target_service_ids": []},
            "end_turn",
        ),
        (
            {
                "operation": "other",
                "complexity": "low",
                "target_service_ids": ["tutor"],
            },
            "end_turn",
        ),
        (
            {
                "operation": "expand",
                "complexity": "medium",
                "target_service_ids": ["tutor"],
            },
            "end_turn",
        ),
        (
            {
                "operation": "expand",
                "complexity": "high",
                "target_service_ids": "tutor",
            },
            "end_turn",
        ),
        ({"operation": "expand", "complexity": "high"}, "end_turn"),
        (
            {
                "operation": "expand",
                "complexity": "high",
                "target_service_ids": ["tutor"],
                "extra": True,
            },
            "end_turn",
        ),
        ("not JSON", "end_turn"),
        ([], "end_turn"),
        (
            {
                "operation": "expand",
                "complexity": "high",
                "target_service_ids": ["tutor"],
            },
            "max_tokens",
        ),
    ],
)
async def test_planner_rejects_invalid_or_incomplete_scope(
    monkeypatch, state, plan, finish_reason
):
    mock_plan(monkeypatch, plan, finish_reason)
    with pytest.raises(ValueError):
        await expansion_tool.plan_service_expansion(state, state["user_message"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Expand the material store",
        "Expand the student app",
        "Expand the retrieval process",
    ],
)
async def test_other_expansions_keep_ordinary_model_selection(
    monkeypatch, state, query
):
    state["user_message"] = query
    mock_plan(
        monkeypatch,
        {"operation": "other", "complexity": "high", "target_service_ids": []},
    )
    result = await orchestrator.orchestrator_route(state)
    assert not result.get("service_expansion")
    assert (
        deadlines.synthesis_timeout_seconds(result)
        == settings.graph_synthesis_timeout_s
    )


@pytest.mark.parametrize(
    "query",
    [
        'Explain this quote: "expand all services"',
        'The document says "expand the tutoring service". What does that mean?',
        "```expand all services```",
    ],
)
def test_quoted_expansion_instructions_are_not_intent(state, query):
    state["user_message"] = query
    assert expansion_tool.service_expansion_request(state) is None


def test_continuation_uses_last_user_request(state):
    state["user_message"] = "please do"
    state["history"] = [
        {"role": "user", "content": "Expand the tutoring service"},
        {"role": "assistant", "content": "I can expand all the services too."},
    ]
    assert (
        expansion_tool.service_expansion_request(state) == "Expand the tutoring service"
    )
    state["history"].insert(1, {"role": "user", "content": "What is a token?"})
    assert expansion_tool.service_expansion_request(state) is None
    state["history"] = [{"role": "assistant", "content": "Expand all services?"}]
    assert expansion_tool.service_expansion_request(state) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("control", [{"graph_action": "answer"}, {"graph_mode": "off"}])
async def test_explicit_answer_only_routes_high_expansion_without_edit(
    monkeypatch, state, control
):
    state.update(control)
    mock_plan(
        monkeypatch,
        {"operation": "expand", "complexity": "high", "target_service_ids": ["tutor"]},
    )
    result = await orchestrator.orchestrator_route(state)
    assert result["route"] == "search"
    assert result["graph_intent"] is None
    assert result["service_expansion"]["complexity"] == "high"


@pytest.mark.asyncio
@pytest.mark.parametrize("complexity", ["low", "high"])
async def test_synthesis_uses_specialist_only_for_high_expansion(
    monkeypatch, state, complexity
):
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs)
        return "Expanded explanation"

    monkeypatch.setattr(orchestrator, "stream_explanation_blocks", provider)
    state.update(
        {
            "route": "search",
            "graph_intent": None,
            "service_expansion": {
                "complexity": complexity,
                "target_service_ids": ["tutor"],
            },
        }
    )
    result = await orchestrator.orchestrator_synthesise(state)
    assert result["response_text"] == "Expanded explanation"
    call = calls[0]
    assert call["model"] == (
        settings.service_expansion_model
        if complexity == "high"
        else settings.explanation_model
    )
    assert call["effort"] == ("medium" if complexity == "high" else "low")
    assert call["timeout_seconds"] == (
        settings.service_expansion_answer_timeout_s
        if complexity == "high"
        else settings.graph_synthesis_timeout_s
    )
    if complexity == "high":
        assert call["model"] == "claude-opus-5-5"
        assert settings.graph_synthesis_timeout_s < call["timeout_seconds"] <= 180


def test_specialist_answer_respects_remaining_deadline(monkeypatch):
    monkeypatch.setattr(deadlines.time, "monotonic", lambda: 100)
    state = {
        "service_expansion": {"complexity": "high"},
        "graph_intent": None,
        "terminal_deadline_s": 160,
    }
    expected = (
        60
        - settings.graph_finalization_reserve_s
        - settings.agent_orchestration_reserve_s
    )
    assert deadlines.synthesis_timeout_seconds(state) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("complexity", ["low", "high"])
async def test_staged_generation_dispatches_high_expansions_through_specialist_tool(
    monkeypatch, state, stage, complexity
):
    calls = []
    tool_calls = []
    original_tool = generation.expand_application_services

    async def provider(**kwargs):
        calls.append(kwargs)
        return response('{"draft": true}')

    async def tracked_tool(**kwargs):
        tool_calls.append(kwargs)
        return await original_tool(**kwargs)

    monkeypatch.setattr(generation, "expand_application_services", tracked_tool)
    monkeypatch.setattr(generation, "stream_structured_llm", provider)
    monkeypatch.setattr(expansion_tool, "stream_structured_llm", provider)
    state["service_expansion"] = {
        "complexity": complexity,
        "target_service_ids": ["tutor"],
    }
    result = await generation._run_generation(
        stage=stage,
        prompt="Expand internals",
        prompt_fingerprint="prompt",
        schema={
            "type": "object",
            "properties": {"candidate": {"anyOf": [{"properties": {}}]}},
        },
        state=state,
        attempt=0,
        upstream_fingerprint="upstream",
        write_set={},
        timeout_seconds=60,
        max_output_tokens=8000,
    )
    assert result == '{"draft": true}'
    assert len(calls) == 1
    assert len(tool_calls) == (1 if complexity == "high" else 0)
    call = calls[0]
    assert call["model"] == (
        settings.service_expansion_model
        if complexity == "high"
        else settings.graph_builder_model
    )
    assert call["effort"] == ("medium" if complexity == "high" else generation._EFFORT)
    assert call["timeout_seconds"] == 60
    assert call["max_output_tokens"] == 8000
    assert call["provider_attempt_limit"] == 1
    if complexity == "high":
        assert "Component records" in call["system"]
        assert "parent_index" in call["system"]
        assert call["telemetry"]["metadata"]["target_service_ids"] == ["tutor"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan,finish_reason", [("not JSON", "end_turn"), ("{}", "max_tokens")]
)
async def test_invalid_plan_requests_clarification_without_edit(
    monkeypatch, state, plan, finish_reason
):
    mock_plan(monkeypatch, plan, finish_reason)
    result = await orchestrator.orchestrator_route(state)
    assert result["route"] == "memory"
    assert result["graph_intent"] is None
    assert result["graph_changed"] is False
    assert result["graph_operation"]["status"] == "needs_clarification"
    assert result["clarification_questions"]
    assert result["graph_data"] == state["graph_data"]
    assert not result.get("service_expansion")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "finish_reason,code",
    [
        ("max_tokens", "staged_generation_truncated"),
        ("stop", "staged_generation_incomplete"),
    ],
)
async def test_specialist_drafts_retain_staged_completion_checks(
    monkeypatch, state, finish_reason, code
):
    async def provider(**_kwargs):
        return response("partial draft", finish_reason)

    monkeypatch.setattr(expansion_tool, "stream_structured_llm", provider)
    state["service_expansion"] = {"complexity": "high", "target_service_ids": ["tutor"]}
    with pytest.raises(generation.StagedGenerationError) as caught:
        await generation._run_generation(
            stage="connections",
            prompt="Expand internals",
            prompt_fingerprint="prompt",
            schema={"type": "object", "properties": {}},
            state=state,
            attempt=0,
            upstream_fingerprint="upstream",
            write_set={},
            timeout_seconds=60,
            max_output_tokens=8000,
        )
    assert caught.value.code == code


@pytest.mark.asyncio
async def test_answer_only_expansion_clears_previous_failed_graph_operation(
    monkeypatch, state
):
    state.update(
        {
            "graph_mode": "off",
            "graph_intent": "edit",
            "graph_operation": {
                "kind": "edit",
                "status": "failed",
                "failure_code": "previous_failure",
            },
        }
    )
    mock_plan(
        monkeypatch,
        {"operation": "expand", "complexity": "high", "target_service_ids": ["tutor"]},
    )
    routed = await orchestrator.orchestrator_route(state)
    assert routed["route"] == "search"
    assert routed["graph_intent"] is None
    assert routed["graph_operation"] is None
    calls = []

    async def explain(**kwargs):
        calls.append(kwargs)
        return "Requested tutoring details"

    monkeypatch.setattr(orchestrator, "stream_explanation_blocks", explain)
    result = await orchestrator.orchestrator_synthesise(routed)
    assert result["response_text"] == "Requested tutoring details"
    assert calls[0]["model"] == settings.service_expansion_model
    assert calls[0]["effort"] == "medium"


@pytest.mark.asyncio
@pytest.mark.parametrize("targets", [["tutor"], ["tutor", "release"]])
async def test_component_generation_retains_selected_parents_after_projection_and_correction(
    monkeypatch, targets
):
    from agent.nodes.graph_worker import staged_edit_scope
    from agent.staged_graph_contract import (
        project_graph_data,
        reconstruct_staged_graph_build,
    )

    graph = {
        "title": "Tutoring platform",
        "graph_type": "architecture",
        "design_origin": "applied",
        "resolved_complexity": "prototype",
        "assumptions": [],
        "nodes": [
            {
                "id": "client",
                "type": "client",
                "label": "Student app",
                "description": "Submits questions.",
            },
            {
                "id": "tutor",
                "type": "service",
                "label": "Tutoring service",
                "description": "Owns tutoring sessions.",
            },
            {
                "id": "release",
                "type": "service",
                "label": "Release service",
                "description": "Owns approved releases.",
            },
        ],
        "edges": [
            {
                "source": "client",
                "target": "tutor",
                "label": "asks question",
                "flow": "runtime",
                "sync": "sync",
            },
            {
                "source": "tutor",
                "target": "release",
                "label": "reads approved release",
                "flow": "runtime",
                "sync": "sync",
            },
        ],
        "sequence": [{"step": 1, "nodes": ["client", "tutor", "release"]}],
        "groups": [
            {
                "id": "runtime",
                "label": "Runtime",
                "kind": "runtime",
                "nodeIds": ["client", "tutor", "release"],
            }
        ],
    }
    projected = project_graph_data(reconstruct_staged_graph_build(graph))
    base = reconstruct_staged_graph_build(projected)
    expansion = {
        "target_service_ids": targets,
        "complexity": "high",
        "request": "Expand the selected services",
    }
    _, permissions = staged_edit_scope(
        expansion["request"],
        projected,
        resolved_complexity="prototype",
        service_expansion=expansion,
    )
    write_set = generation.create_write_set(
        component_limit=3 + permissions["allowed_new_node_count"], edge_limit=20
    )
    parent_indexes = {
        row["server_id"]: row["model_index"] for row in base["components"]
    }
    expected_parents = [
        {"index": row["model_index"], "label": row["label"]}
        for row in base["components"]
        if row["server_id"] in targets
    ]
    delta_response = {
        "candidate": {
            "additions": [
                {
                    "label": f"Internal {target} worker",
                    "type": 109,
                    "parent_index": parent_indexes[target],
                    "responsibility": "Owns an internal step of its parent service.",
                    "group_label": "Runtime",
                    "group_kind": 600,
                    "primary_flow_member": False,
                }
                for target in targets
            ],
            "updates": {},
            "capabilities": base["capabilities"],
        },
        "clarification_questions": [],
    }
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs)
        return response(json.dumps(delta_response))

    monkeypatch.setattr(expansion_tool, "stream_structured_llm", provider)
    arguments = {
        "request": expansion["request"],
        "resolved_maturity": "prototype",
        "architecture_context": "Stable review frame: tutoring service internals.",
        "write_set": write_set,
        "upstream_fingerprint": "a" * 64,
        "base_components": base,
        "edit_permissions": permissions,
        "state": {
            "service_expansion": expansion,
            "user_message": expansion["request"],
            "history": [],
        },
    }
    first = await generation.generate_component_candidate(**arguments)
    corrected = await generation.generate_component_candidate(
        **arguments,
        attempt=1,
        prior_prompt_fingerprint=first["prompt_fingerprint"],
        prior_write_set_fingerprint=generation._fingerprint(write_set),
        rejected_candidate=first["wire"],
        gate_findings=[
            {
                "code": "component_specificity",
                "path": "components",
                "rule": "service_ownership",
                "reason": "State narrower ownership.",
            }
        ],
    )
    assert corrected["wire"] == first["wire"]
    assert len(calls) == 2
    for attempt, call in enumerate(calls):
        prompt_input = json.loads(
            call["messages"][0]["content"].split("\nINPUT\n", 1)[1]
        )
        assert prompt_input["attempt"] == attempt
        assert prompt_input["service_expansion"]["parents"] == expected_parents
        assert all(
            "server_id" not in row and "model_index" not in row
            for row in prompt_input["base"]["components"]
        )
        assert call["model"] == settings.service_expansion_model
        assert call["effort"] == "medium"
    assert [row["parent_index"] for row in corrected["wire"]["components"][3:]] == [
        parent_indexes[target] for target in targets
    ]


@pytest.mark.parametrize("target_reply", ["Tutoring service", "All of them"])
def test_target_clarification_reply_resumes_prior_user_expansion(state, target_reply):
    state.update(
        user_message=target_reply,
        history=[
            {"role": "user", "content": "Expand the backend service"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    assert expansion_tool.service_expansion_request(state) == (
        f"Original expansion request: Expand the backend service\nLatest user reply: {target_reply}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "history",
    [
        [
            {"role": "user", "content": "Expand the backend service"},
            {
                "role": "assistant",
                "content": "Which service would you like to discuss?",
            },
        ],
        [
            {"role": "user", "content": "What is a token?"},
            {"role": "assistant", "content": "I can expand the Tutoring service."},
        ],
        [
            {
                "role": "user",
                "content": 'Explain this quote: "Expand the backend service"',
            },
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
        [
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            }
        ],
        [
            {"role": "user", "content": "Expand the backend service"},
            {"role": "user", "content": "What is a token?"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    ],
)
async def test_target_reply_does_not_create_intent_from_assistant_content(
    monkeypatch, state, history
):
    state.update(user_message="Tutoring service", history=history)
    assert expansion_tool.service_expansion_request(state) is None
    calls = mock_plan(
        monkeypatch,
        {"operation": "expand", "complexity": "high", "target_service_ids": ["tutor"]},
    )

    async def router(**_kwargs):
        return "SEARCH"

    monkeypatch.setattr(orchestrator, "stream_llm", router)
    result = await orchestrator.orchestrator_route(state)
    assert not calls
    assert not result.get("service_expansion")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_reply,targets",
    [("Tutoring service", ["tutor"]), ("All of them", ["tutor", "release"])],
)
async def test_orchestrator_routes_target_reply_to_scoped_service_expansion(
    monkeypatch, state, target_reply, targets
):
    state.update(
        user_message=target_reply,
        history=[
            {"role": "user", "content": "Expand the backend service"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    calls = mock_plan(
        monkeypatch,
        {"operation": "expand", "complexity": "high", "target_service_ids": targets},
    )
    result = await orchestrator.orchestrator_route(state)
    assert result["route"] == "search"
    assert result["graph_intent"] == "edit"
    assert result["service_expansion"]["target_service_ids"] == targets
    assert result["service_expansion"]["complexity"] == "high"
    combined = f"Original expansion request: Expand the backend service\nLatest user reply: {target_reply}"
    assert json.loads(calls[0]["messages"][0]["content"])["request"] == combined
    assert result["design_query"] == combined
    assert result["service_expansion"]["request"] == combined


@pytest.mark.asyncio
async def test_target_reply_cancellation_reaches_planner_and_does_not_select_specialist(
    monkeypatch, state
):
    state.update(
        user_message="Never mind, explain tokenization instead",
        history=[
            {"role": "user", "content": "Expand the backend service"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    calls = mock_plan(
        monkeypatch,
        {"operation": "other", "complexity": "low", "target_service_ids": []},
    )

    async def router(**_kwargs):
        return "SEARCH"

    monkeypatch.setattr(orchestrator, "stream_llm", router)
    result = await orchestrator.orchestrator_route(state)
    request = json.loads(calls[0]["messages"][0]["content"])["request"]
    assert request.endswith(
        "Latest user reply: Never mind, explain tokenization instead"
    )
    assert not result.get("service_expansion")


@pytest.mark.asyncio
async def test_failed_planner_uses_shared_target_question(monkeypatch, state):
    mock_plan(
        monkeypatch,
        {"operation": "clarify", "complexity": "low", "target_service_ids": []},
    )
    result = await orchestrator.orchestrator_route(state)
    assert result["response_text"] == expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION
    assert result["clarification_questions"] == [
        expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION
    ]


@pytest.mark.asyncio
async def test_repeated_target_clarifications_resume_with_all_replies_in_order(
    monkeypatch, state
):
    state.update(
        user_message="Tutoring service",
        history=[
            {"role": "user", "content": "Expand the backend service"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
            {"role": "user", "content": "The learning backend"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
            {"role": "user", "content": "The one that handles students"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    combined = (
        "Original expansion request: Expand the backend service\n"
        "Prior target reply: The learning backend\n"
        "Prior target reply: The one that handles students\n"
        "Latest user reply: Tutoring service"
    )
    assert expansion_tool.service_expansion_request(state) == combined
    calls = mock_plan(
        monkeypatch,
        {"operation": "expand", "complexity": "high", "target_service_ids": ["tutor"]},
    )
    result = await orchestrator.orchestrator_route(state)
    assert result["graph_intent"] == "edit"
    assert result["service_expansion"]["target_service_ids"] == ["tutor"]
    assert result["design_query"] == combined
    assert json.loads(calls[0]["messages"][0]["content"])["request"] == combined


@pytest.mark.parametrize(
    "intervening_reply,assistant_response",
    [
        ("The learning backend", "Would you like a walkthrough?"),
        ("Never mind, explain tokens instead", "Tokens are units of model input."),
    ],
)
def test_ordinary_assistant_response_breaks_pending_clarification_chain(
    state, intervening_reply, assistant_response
):
    state.update(
        user_message="Tutoring service",
        history=[
            {"role": "user", "content": "Expand the backend service"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
            {"role": "user", "content": intervening_reply},
            {"role": "assistant", "content": assistant_response},
            {"role": "user", "content": "Which service?"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    assert expansion_tool.service_expansion_request(state) is None


@pytest.mark.parametrize(
    "invalid_message",
    [
        None,
        {"role": "assistant", "content": "Target"},
        {"role": "user", "content": None},
        {"role": "user", "content": " "},
    ],
)
def test_invalid_user_message_breaks_clarification_chain(state, invalid_message):
    state.update(
        user_message="Tutoring service",
        history=[
            {"role": "user", "content": "Expand the backend service"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
            invalid_message,
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    assert expansion_tool.service_expansion_request(state) is None


def test_clarification_chain_without_original_user_expansion_does_not_resume(state):
    state.update(
        user_message="Tutoring service",
        history=[
            {"role": "user", "content": 'Explain "expand backend services"'},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
            {"role": "user", "content": "The learning backend"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    assert expansion_tool.service_expansion_request(state) is None


def test_pending_clarification_chain_keeps_prior_cancellation_visible_to_planner(state):
    state.update(
        user_message="Tutoring service",
        history=[
            {"role": "user", "content": "Expand the backend service"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
            {"role": "user", "content": "Never mind, explain tokenization"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    assert expansion_tool.service_expansion_request(state) == (
        "Original expansion request: Expand the backend service\n"
        "Prior target reply: Never mind, explain tokenization\n"
        "Latest user reply: Tutoring service"
    )


@pytest.mark.parametrize(
    "invalid_question",
    [
        None,
        {"role": "tool", "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION},
        {"role": "assistant", "content": None},
    ],
)
def test_invalid_assistant_question_breaks_clarification_chain(state, invalid_question):
    state.update(
        user_message="Tutoring service",
        history=[
            {"role": "user", "content": "Expand the backend service"},
            invalid_question,
            {"role": "user", "content": "The learning backend"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    assert expansion_tool.service_expansion_request(state) is None


def test_clarification_chain_uses_nearest_user_expansion_request(state):
    state.update(
        user_message="Tutoring service",
        history=[
            {"role": "user", "content": "Expand all services"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
            {"role": "user", "content": "Expand only one backend service"},
            {
                "role": "assistant",
                "content": expansion_tool.SERVICE_EXPANSION_TARGET_QUESTION,
            },
        ],
    )
    assert expansion_tool.service_expansion_request(state) == (
        "Original expansion request: Expand only one backend service\n"
        "Latest user reply: Tutoring service"
    )
