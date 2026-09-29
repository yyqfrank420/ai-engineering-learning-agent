"""Transport guards reject stale graph intent before model work starts."""

import json

import pytest
from fastapi.testclient import TestClient

from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import get_current_user
from main import create_app
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, get_graph, persist_turn


@pytest.fixture
def continuity_app(temp_data_dir, monkeypatch):
    init_db()
    user = {"id": "continuity-user", "email": "continuity@example.com"}
    upsert_profile(user["id"], user["email"])
    thread = create_thread(user["id"])
    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = [{"page_content": "agent design"}]
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(
        "api.chat_websocket.get_current_user", lambda authorization: user
    )
    return app, user, thread


def request_events(client, transport, body):
    if transport == "sse":
        response = client.post("/api/chat", json=body)
        if response.status_code == 422:
            return [{"type": "invalid_request"}]
        assert response.status_code == 200
        return [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
    with client.websocket_connect("/api/chat/ws") as socket:
        socket.send_json({"type": "auth", "access_token": "fixture-token"})
        assert socket.receive_json()["type"] == "ready"
        socket.send_json({"type": "start", **body})
        events = []
        for _ in range(30):
            event = socket.receive_json()
            events.append(event)
            if (
                event["type"] == "done"
                or event.get("content") == "Invalid chat request"
            ):
                return events
        raise AssertionError(events)


def seed_graph(user, thread):
    graph = {
        "version": "current-v1",
        "title": "Existing",
        "nodes": [],
        "edges": [],
        "sequence": [],
    }
    assert persist_turn(
        user["id"],
        thread["id"],
        title="Existing",
        user_content="Initial",
        assistant_content="Saved",
        graph_data=graph,
    )
    return graph


@pytest.mark.parametrize("transport", ["sse", "ws"])
@pytest.mark.parametrize(
    ("action", "version", "existing", "content", "expected"),
    [
        ("extend", "stale-v0", True, "Extend this diagram", "Reload this chat"),
        ("extend", None, True, "Extend this diagram", "Reload this chat"),
        ("extend", "current-v1", False, "Extend this diagram", "no diagram to extend"),
        ("new", None, True, "Design a new pipeline", "Start a new chat"),
        (None, None, True, "Design a new RAG system architecture", "Choose to extend"),
        ("invalid", None, False, "Hello", None),
    ],
)
def test_continuity_rejection_precedes_agent(
    continuity_app, monkeypatch, transport, action, version, existing, content, expected
):
    app, user, thread = continuity_app
    graph = seed_graph(user, thread) if existing else None
    called = []

    async def forbidden_agent(*args, **kwargs):
        called.append(True)
        raise AssertionError("Rejected request reached model work")

    monkeypatch.setattr("api.sse_handler.run_agent", forbidden_agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", forbidden_agent)
    body = {
        "thread_id": thread["id"],
        "content": content,
        "graph_action": action,
        "expected_graph_version": version,
    }
    with TestClient(app) as client:
        events = request_events(client, transport, body)
    assert not called
    assert get_graph(user["id"], thread["id"]) == graph
    if expected:
        assert any(
            event["type"] == "error" and expected in event["content"]
            for event in events
        ), events
        assert events[-1]["type"] == "done"
    else:
        assert events[0]["type"] in {"invalid_request", "error"}


@pytest.mark.parametrize("transport", ["sse", "ws"])
@pytest.mark.parametrize("action", ["extend", "answer"])
def test_explicit_intent_reaches_agent(continuity_app, monkeypatch, transport, action):
    app, user, thread = continuity_app
    graph = seed_graph(user, thread)
    observed = []

    async def fake_agent(state, *args):
        observed.append(state)
        return {**state, "response_text": "Saved diagram remains available."}

    monkeypatch.setattr("api.sse_handler.run_agent", fake_agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", fake_agent)
    with TestClient(app) as client:
        events = request_events(
            client,
            transport,
            {
                "thread_id": thread["id"],
                "content": "Extend this diagram",
                "graph_action": action,
                "expected_graph_version": "current-v1",
            },
        )
    assert len(observed) == 1
    assert observed[0]["graph_action"] == action
    assert observed[0]["graph_data"] == graph
    assert not [event for event in events if event["type"] == "error"], events
    assert events[-1]["type"] == "done"


@pytest.mark.parametrize("transport", ["sse", "ws"])
def test_authoritative_event_reads_committed_graph(
    continuity_app, monkeypatch, transport
):
    app, user, thread = continuity_app
    graph = seed_graph(user, thread)
    committed = {**graph, "title": "Committed layout"}

    async def fake_agent(state, *args):
        return {**state, "response_text": "Saved.", "graph_data": graph}

    def commit_latest_layout(*args, **kwargs):
        return persist_turn(*args, **{**kwargs, "graph_data": committed})

    monkeypatch.setattr("api.sse_handler.run_agent", fake_agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", fake_agent)
    monkeypatch.setattr("storage.thread_store.persist_turn", commit_latest_layout)
    with TestClient(app) as client:
        events = request_events(
            client,
            transport,
            {
                "thread_id": thread["id"],
                "content": "Explain this diagram",
                "graph_action": "answer",
            },
        )
    assert get_graph(user["id"], thread["id"]) == committed
    published = [event["data"] for event in events if event["type"] == "graph_data"]
    assert published == [committed]
