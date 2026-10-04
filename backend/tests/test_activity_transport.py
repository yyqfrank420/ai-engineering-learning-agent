"""Public activity is ordered, private reasoning is omitted, and done uses saved metadata."""

import asyncio

from fastapi.testclient import TestClient
import pytest

from adapters.database_adapter import init_db
from storage.message_store import get_messages
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, get_completed_turn
from test_api_security import _authed_app, _parse_sse_events
from test_chat_websocket import _ready_app, _receive_until


def _setup(transport, temp_data_dir, monkeypatch):
    if transport == "websocket":
        from adapters.supabase_auth_adapter import get_current_user

        app, user, thread = _ready_app(temp_data_dir, monkeypatch)
        app.dependency_overrides[get_current_user] = lambda: user
        return app, user, thread
    init_db()
    user = {"id": "user-1"}
    upsert_profile(user["id"], "friend@example.com")
    return _authed_app(), user, create_thread(user["id"])


def _run(client, transport, payload):
    if transport == "sse":
        return _parse_sse_events(client.post("/api/chat", json=payload).text)
    with client.websocket_connect(
        "/api/chat/ws", headers={"origin": "http://localhost:5173"}
    ) as socket:
        socket.send_json({"type": "auth", "access_token": "test-token"})
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"type": "start", **payload})
        return _receive_until(socket, "done", limit=40)


@pytest.mark.parametrize("transport", ["sse", "websocket"])
@pytest.mark.parametrize("failed", [False, True])
def test_activity_streams_persists_and_replays_with_no_new_provider_work(
    transport, failed, temp_data_dir, monkeypatch
):
    app, user, thread = _setup(transport, temp_data_dir, monkeypatch)
    calls = []

    async def agent(state, *_tools):
        calls.append(state["user_message"])
        await state["send"]({"type": "thinking_delta", "content": "PRIVATE_REASONING"})
        await asyncio.gather(
            *[
                state["send"](
                    {
                        "type": "workflow_progress",
                        "phase": phase,
                        "status": "active",
                        "title": "Internal title",
                        "detail": "slot.private",
                    }
                )
                for phase in ["book", "web"]
            ]
        )
        await state["send"](
            {
                "type": "workflow_progress",
                "phase": "review",
                "status": "rejected" if failed else "complete",
                "detail": "SECRET_DIAGNOSTIC",
            }
        )
        await state["send"]({"type": "response_delta", "content": "Answer"})
        return {
            **state,
            "response_text": "Answer",
            "graph_publication": "withheld" if failed else "unchanged",
        }

    monkeypatch.setattr("api.sse_handler.run_agent", agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", agent)
    payload = {
        "thread_id": thread["id"],
        "content": "Request",
        "client_request_id": "activity",
    }
    with TestClient(app) as client:
        events = _run(client, transport, payload)
        replay = _run(client, transport, payload)
        reloaded = client.get(f"/api/threads/{thread['id']}").json()
    live = [event for event in events if event["type"] == "activity_step"]
    assert [step["sequence"] for step in live] == [0, 1, 2]
    assert [step["kind"] for step in live] == ["tool", "tool", "tool"]
    assert {step["phase"] for step in live[:2]} == {"book", "web"}
    assert [step["elapsed_ms"] for step in live] == sorted(
        step["elapsed_ms"] for step in live
    )
    assert not any(event["type"] == "thinking_delta" for event in events)
    completed = get_completed_turn(user["id"], thread["id"], "activity")
    canonical = completed["activity"]
    assert events[-1] == {"type": "done", "activity": canonical}
    assert replay[-1] == events[-1]
    assert not any(event["type"] == "activity_step" for event in replay)
    assert canonical["steps"] == [
        {key: value for key, value in step.items() if key != "type"} for step in live
    ]
    assert canonical["duration_ms"] >= live[-1]["elapsed_ms"]
    assert "PRIVATE_REASONING" not in repr(events) + repr(completed)
    assert "SECRET_DIAGNOSTIC" not in repr(canonical)
    assert "slot.private" not in repr(canonical)
    assert reloaded["messages"][-1]["activity"] == canonical
    assert get_messages(user["id"], thread["id"])[0]["activity"] is None
    assert calls == ["Request"]


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_done_requeries_activity_of_idempotent_winner(
    transport, temp_data_dir, monkeypatch
):
    from storage import thread_store

    app, user, thread = _setup(transport, temp_data_dir, monkeypatch)
    winner = {
        "duration_ms": 42,
        "steps": [
            {
                "sequence": 0,
                "kind": "update",
                "phase": "explain",
                "status": "complete",
                "text": "I've prepared your answer.",
                "elapsed_ms": 42,
            }
        ],
    }
    original_persist = thread_store.persist_turn

    def competing_persist(*args, **kwargs):
        original_persist(*args, **{**kwargs, "activity": winner})
        return original_persist(*args, **kwargs)

    async def agent(state, *_tools):
        await state["send"](
            {"type": "workflow_progress", "phase": "explain", "status": "active"}
        )
        return {**state, "response_text": "Answer"}

    monkeypatch.setattr(thread_store, "persist_turn", competing_persist)
    monkeypatch.setattr("api.sse_handler.run_agent", agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", agent)
    with TestClient(app) as client:
        events = _run(
            client,
            transport,
            {
                "thread_id": thread["id"],
                "content": "Request",
                "client_request_id": "winner",
            },
        )
    assert events[-1] == {"type": "done", "activity": winner}
    assert get_completed_turn(user["id"], thread["id"], "winner")["activity"] == winner
    assert len(get_messages(user["id"], thread["id"])) == 2


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_optional_activity_failure_preserves_answer(
    transport, temp_data_dir, monkeypatch
):
    from agent.activity import ActivityRecorder

    app, user, thread = _setup(transport, temp_data_dir, monkeypatch)

    def unavailable(*_args):
        raise ValueError("optional feedback unavailable")

    async def agent(state, *_tools):
        await state["send"](
            {"type": "workflow_progress", "phase": "explain", "status": "active"}
        )
        return {**state, "response_text": "Answer"}

    monkeypatch.setattr(ActivityRecorder, "record", unavailable)
    monkeypatch.setattr("api.sse_handler.run_agent", agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", agent)
    with TestClient(app) as client:
        events = _run(
            client,
            transport,
            {
                "thread_id": thread["id"],
                "content": "Request",
                "client_request_id": "optional",
            },
        )
    assert events[-1] == {"type": "done"}
    assert (
        get_completed_turn(user["id"], thread["id"], "optional")["assistant_content"]
        == "Answer"
    )


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_request_without_id_keeps_its_saved_activity(
    transport, temp_data_dir, monkeypatch
):
    app, user, thread = _setup(transport, temp_data_dir, monkeypatch)

    async def agent(state, *_tools):
        await state["send"](
            {"type": "workflow_progress", "phase": "explain", "status": "active"}
        )
        return {**state, "response_text": "Answer"}

    monkeypatch.setattr("api.sse_handler.run_agent", agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", agent)
    with TestClient(app) as client:
        events = _run(
            client, transport, {"thread_id": thread["id"], "content": "Request"}
        )
    canonical = get_messages(user["id"], thread["id"])[-1]["activity"]
    assert canonical is not None
    assert events[-1] == {"type": "done", "activity": canonical}
