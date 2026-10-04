"""Input validation precedes orchestration and preserves live accepted turns."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import api.chat_websocket as chat_websocket
import api.sse_handler as sse_handler
import api.thread_route as thread_route
from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import get_current_user
from main import create_app
from storage import message_store, thread_store
from storage.profile_store import upsert_profile


REJECTION = "Please ask a question about AI engineering architecture."


def _setup(temp_data_dir, monkeypatch):
    init_db()
    user = {"id": "input-gate-user", "email": "input@example.com"}
    upsert_profile(user["id"], user["email"])
    thread = thread_store.create_thread(user["id"])
    app = create_app(load_resources=False)
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(chat_websocket, "get_current_user", lambda authorization: user)
    return app, user, thread


def _events(response):
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _forbidden(*args, **kwargs):
    raise AssertionError("Rejected input entered the core workflow")


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_rejected_input_is_persisted_and_replayed_before_core(
    temp_data_dir, monkeypatch, transport
):
    app, user, thread = _setup(temp_data_dir, monkeypatch)
    calls = []

    async def reject(text, history, **telemetry):
        calls.append((text, history))
        return REJECTION

    monkeypatch.setattr(sse_handler, "chat_input_error", reject)
    monkeypatch.setattr(sse_handler, "_make_agent_tools", _forbidden)
    monkeypatch.setattr(chat_websocket, "_make_agent_tools", _forbidden)
    monkeypatch.setattr(sse_handler, "graph_continuity_error", _forbidden)
    monkeypatch.setattr(chat_websocket, "graph_continuity_error", _forbidden)
    payload = {
        "thread_id": thread["id"],
        "content": "What's for dinner?",
        "client_request_id": "reject-1",
    }
    with TestClient(app) as client:
        for attempt in range(2):
            if transport == "sse":
                events = _events(client.post("/api/chat", json=payload))
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
            assert events[0] == {"type": "response_delta", "content": REJECTION}
            assert events[-1] == {"type": "done"}
            assert not any(
                event["type"] in {"worker_status", "thinking", "generation_started"}
                for event in events
            )
    assert len(calls) == 1
    history = message_store.get_history(user["id"], thread["id"])
    assert [item["content"] for item in history] == [payload["content"], REJECTION]
    assert thread_store.get_graph(user["id"], thread["id"]) is None


def test_sse_rejects_raw_steering_before_effective_prompt_reaches_core(
    temp_data_dir, monkeypatch
):
    app, user, thread = _setup(temp_data_dir, monkeypatch)
    observed = []

    async def gate(text, history, **telemetry):
        observed.append((text, history))
        return REJECTION if text == "Dinner suggestions please" else None

    monkeypatch.setattr(sse_handler, "chat_input_error", gate)
    monkeypatch.setattr(sse_handler, "_make_agent_tools", _forbidden)
    with TestClient(app) as client:
        events = _events(
            client.post(
                "/api/chat",
                json={
                    "thread_id": thread["id"],
                    "content": "Design a RAG assistant",
                    "steering_updates": ["Dinner suggestions please"],
                    "client_request_id": "steer-reject",
                },
            )
        )
    assert events == [
        {"type": "response_delta", "content": REJECTION},
        {"type": "done"},
    ]
    assert observed[1][0] == "Dinner suggestions please"
    assert observed[1][1][-1] == {"role": "user", "content": "Design a RAG assistant"}


def test_diagram_intent_rejection_bypasses_diagram_choice(temp_data_dir, monkeypatch):
    app, _, thread = _setup(temp_data_dir, monkeypatch)

    async def reject(text, history, **telemetry):
        assert telemetry["request_id"]
        return REJECTION

    monkeypatch.setattr(thread_route, "chat_input_error", reject)
    monkeypatch.setattr(thread_route, "diagram_submission_action", _forbidden)
    with TestClient(app) as client:
        response = client.post(
            f"/api/threads/{thread['id']}/diagram-intent", json={"message": "Dinner?"}
        )
    assert response.status_code == 200
    assert response.json() == {"action": "answer"}


@pytest.mark.parametrize("reject_composite", [False, True])
def test_websocket_rejected_steering_preserves_current_run(
    temp_data_dir, monkeypatch, reject_composite
):
    app, _, thread = _setup(temp_data_dir, monkeypatch)
    app.state.vectorstore = object()
    app.state.parent_docs = [{"page_content": "AI engineering"}]
    started = []
    cancelled = []
    gate_calls = []
    steering = "Focus on retrieval" if reject_composite else "Dinner suggestions please"
    rejection_text = (
        "Message blocked by security filter" if reject_composite else REJECTION
    )
    composite = f"Design a RAG assistant\n\nUser steering update 1:\n{steering}"

    async def gate(text, history, **telemetry):
        gate_calls.append(text)
        if text == (composite if reject_composite else steering):
            return rejection_text
        return None

    async def run(state, *tools):
        started.append(state["user_message"])
        await state["send"]({"type": "response_delta", "content": "Accepted draft"})
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    monkeypatch.setattr(sse_handler, "chat_input_error", gate)
    monkeypatch.setattr(chat_websocket, "chat_input_error", gate)
    monkeypatch.setattr(
        chat_websocket, "_make_agent_tools", lambda request: ([], [], [])
    )
    monkeypatch.setattr(chat_websocket, "run_agent", run)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json()["type"] == "ready"
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread["id"],
                    "content": "Design a RAG assistant",
                }
            )
            while socket.receive_json()["type"] != "response_delta":
                pass
            for _ in range(3):
                socket.send_json({"type": "steer", "content": steering})
                rejection = socket.receive_json()
                assert rejection == {
                    "type": "command_rejected",
                    "reason": rejection_text,
                }
            socket.send_json({"type": "steer", "content": steering})
            assert socket.receive_json() == {
                "type": "command_rejected",
                "reason": "Steering command was empty, unsafe, too large, or over the limit",
            }
            expected_attempt = [steering, composite] if reject_composite else [steering]
            assert gate_calls == ["Design a RAG assistant"] + expected_attempt * 3
            assert not cancelled
            assert started == ["Design a RAG assistant"]
            socket.send_json({"type": "stop"})
            while socket.receive_json()["type"] != "stopped":
                pass


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_retry_validates_reconstructed_canonical_input(
    temp_data_dir, monkeypatch, transport
):
    app, user, thread = _setup(temp_data_dir, monkeypatch)
    canonical = (
        "Design a RAG assistant\n\nUser steering update 1:\nDinner suggestions please"
    )
    thread_store.persist_turn(
        user["id"],
        thread["id"],
        title="Retry source",
        user_content=canonical,
        assistant_content="Previous generation failed",
        graph_data=None,
        client_request_id="source-request",
        retry_request={
            "content": "Design a RAG assistant",
            "complexity": "auto",
            "graph_mode": "on",
            "diagram_requested": False,
            "research_enabled": False,
            "graph_action": None,
            "expected_graph_version": None,
        },
    )
    observed = []

    async def gate(text, history, **telemetry):
        observed.append(text)
        return REJECTION

    monkeypatch.setattr(sse_handler, "chat_input_error", gate)
    monkeypatch.setattr(sse_handler, "_make_agent_tools", _forbidden)
    monkeypatch.setattr(chat_websocket, "_make_agent_tools", _forbidden)
    payload = {
        "thread_id": thread["id"],
        "content": "Untrusted retry replacement",
        "retry_source_request_id": "source-request",
        "client_request_id": "retry-request",
    }
    with TestClient(app) as client:
        if transport == "sse":
            events = _events(client.post("/api/chat", json=payload))
        else:
            with client.websocket_connect(
                "/api/chat/ws", headers={"origin": "http://localhost:5173"}
            ) as socket:
                socket.send_json({"type": "auth", "access_token": "test-token"})
                assert socket.receive_json()["type"] == "ready"
                socket.send_json({"type": "start", **payload})
                events = [socket.receive_json(), socket.receive_json()]
    assert events == [
        {"type": "response_delta", "content": REJECTION},
        {"type": "done"},
    ]
    assert observed == [canonical]
