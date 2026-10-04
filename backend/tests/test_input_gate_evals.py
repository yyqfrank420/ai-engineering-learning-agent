"""Offline corpus checks validate gate wiring; live evaluation measures semantics."""

import json
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import get_current_user
from agent.stream_utils import StructuredLLMResponse
from api import chat_guards, chat_websocket, sse_handler
from eval.input_gate_cases import INPUT_GATE_CASES
from main import create_app
from storage import message_store, thread_store
from storage.profile_store import upsert_profile


_REAL_SCANNER = chat_guards.check_prompt_injection
_REJECTION_ERRORS = {
    "ACCEPT": None,
    "OFF_TOPIC": "Please ask a question about AI engineering or AI system architecture.",
    "UNSAFE": "Message blocked by security filter",
}
_REJECTED_CASES = tuple(
    case for case in INPUT_GATE_CASES if case.expected_verdict != "ACCEPT"
)


@pytest.fixture
def gate_model(case, monkeypatch):
    model = AsyncMock(
        return_value=StructuredLLMResponse(
            text=json.dumps({"verdict": case.expected_verdict}),
            finish_reason="end_turn",
            input_tokens=1,
            output_tokens=1,
            provider="anthropic",
            model="claude-opus-5",
        )
    )
    monkeypatch.setattr(chat_guards, "check_prompt_injection", _REAL_SCANNER)
    monkeypatch.setattr(chat_guards, "stream_structured_llm", model)
    monkeypatch.setattr(sse_handler, "chat_input_error", chat_guards.chat_input_error)
    monkeypatch.setattr(
        chat_websocket, "chat_input_error", chat_guards.chat_input_error
    )
    return model


def test_input_gate_corpus_is_immutable_and_identifiable():
    assert len(INPUT_GATE_CASES) == 10
    assert len({case.id for case in INPUT_GATE_CASES}) == 10
    assert {case.expected_verdict for case in INPUT_GATE_CASES} == {
        "ACCEPT",
        "OFF_TOPIC",
        "UNSAFE",
    }
    with pytest.raises(FrozenInstanceError):
        INPUT_GATE_CASES[0].message = "Changed corpus input"


@pytest.mark.parametrize("case", INPUT_GATE_CASES, ids=lambda case: case.id)
async def test_corpus_gate_contract(case, gate_model):
    history = [{"role": role, "content": content} for role, content in case.history]
    result = await chat_guards.chat_input_error(case.message, history)
    assert result == _REJECTION_ERRORS[case.expected_verdict]
    if case.id == "scanner_override_secret_leak":
        assert _REAL_SCANNER(case.message) is False
        gate_model.assert_not_awaited()
    else:
        assert _REAL_SCANNER(case.message) is True
        gate_model.assert_awaited_once()
        payload = json.loads(gate_model.await_args.kwargs["messages"][0]["content"])
        assert payload["history"] == history
        if case.id == "highlighted_ai_dinner_question":
            assert payload["latest_user_message"] == "What should I eat for dinner?"
            assert payload["effective_content"] == case.message
        else:
            assert payload["latest_user_message"] == case.message


def _forbidden(*args, **kwargs):
    raise AssertionError("Rejected corpus input entered the core workflow")


@pytest.mark.parametrize("transport", ["sse", "websocket"])
@pytest.mark.parametrize("case", _REJECTED_CASES, ids=lambda case: case.id)
def test_corpus_rejections_stop_core_and_persist_clean_turn(
    case, transport, gate_model, temp_data_dir, monkeypatch
):
    _assert_corpus_rejection(case, transport, gate_model, temp_data_dir, monkeypatch)


@pytest.mark.parametrize("transport", ["sse", "websocket"])
@pytest.mark.parametrize(
    "case",
    [case for case in INPUT_GATE_CASES if case.id == "semantic_admission_override"],
    ids=lambda case: case.id,
)
def test_empty_provider_refusal_rejects_before_core(
    case, transport, gate_model, temp_data_dir, monkeypatch
):
    gate_model.return_value = StructuredLLMResponse(
        text="",
        finish_reason="refusal",
        input_tokens=1,
        output_tokens=0,
        provider="anthropic",
        model="claude-opus-5",
    )
    _assert_corpus_rejection(case, transport, gate_model, temp_data_dir, monkeypatch)


def _assert_corpus_rejection(case, transport, gate_model, temp_data_dir, monkeypatch):
    init_db()
    user = {"id": "input-gate-eval-user", "email": "input-eval@example.com"}
    upsert_profile(user["id"], user["email"])
    thread = thread_store.create_thread(user["id"])
    for role, content in case.history:
        message_store.append(user["id"], thread["id"], role, content)
    app = create_app(load_resources=False)
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(chat_websocket, "get_current_user", lambda authorization: user)
    for module in (sse_handler, chat_websocket):
        monkeypatch.setattr(module, "_make_agent_tools", _forbidden)
        monkeypatch.setattr(module, "run_agent", _forbidden)
        monkeypatch.setattr(module, "graph_continuity_error", _forbidden)
        monkeypatch.setattr(module, "knowledge_base_ready", _forbidden)
    payload = {
        "thread_id": thread["id"],
        "content": case.message,
        "client_request_id": f"corpus-{case.id}",
    }
    with TestClient(app) as client:
        if transport == "sse":
            response = client.post("/api/chat", json=payload)
            assert response.status_code == 200
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
        else:
            with client.websocket_connect(
                "/api/chat/ws", headers={"origin": "http://localhost:5173"}
            ) as socket:
                socket.send_json({"type": "auth", "access_token": "test-token"})
                assert socket.receive_json()["type"] == "ready"
                socket.send_json({"type": "start", **payload})
                events = []
                while not events or events[-1]["type"] != "done":
                    events.append(socket.receive_json())
    expected_error = _REJECTION_ERRORS[case.expected_verdict]
    assert events == [
        {"type": "response_delta", "content": expected_error},
        {"type": "done"},
    ]
    messages = message_store.get_messages(user["id"], thread["id"])
    assert [(item["role"], item["content"]) for item in messages] == list(
        case.history
    ) + [
        ("user", case.message),
        ("assistant", expected_error),
    ]
    for item in messages[-2:]:
        assert item["activity"] is None
        assert item["retry_request"] is None
        assert item["graph_revision_id"] is None
    assert thread_store.get_graph(user["id"], thread["id"]) is None
    completed = thread_store.get_completed_turn(
        user["id"], thread["id"], payload["client_request_id"]
    )
    assert "retry_request" not in completed
    assert "activity" not in completed
    if case.id == "scanner_override_secret_leak":
        gate_model.assert_not_awaited()
    else:
        gate_model.assert_awaited_once()
        serialized = json.loads(gate_model.await_args.kwargs["messages"][0]["content"])
        assert serialized["history"] == [
            {"role": role, "content": content} for role, content in case.history
        ]
