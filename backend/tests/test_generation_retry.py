import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from adapters.database_adapter import execute, init_db
from api.sse_handler import ChatRequest
from config import settings
from storage.message_store import get_messages
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, get_completed_turn, persist_turn


def request_options(content="Draw a diagram"):
    return ChatRequest(thread_id="thread", content=content).model_dump(
        exclude={"thread_id", "client_request_id", "retry_source_request_id", "steering_updates"}
    )


def test_retry_roundtrip_is_assistant_only_owned_and_idempotent(temp_data_dir):
    init_db()
    upsert_profile("owner", "owner@example.com")
    thread = create_thread("owner")
    request = request_options()
    args = dict(
        title="Failed",
        user_content=request["content"],
        assistant_content="Diagram failed",
        graph_data=None,
        client_request_id="attempt",
        retry_request=request,
    )
    assert persist_turn("owner", thread["id"], **args)
    assert persist_turn("owner", thread["id"], **{**args, "retry_request": None})
    messages = get_messages("owner", thread["id"])
    assert len(messages) == 2
    assert messages[0]["retry_request"] is None
    assert messages[1]["retry_request"] == request
    assert (
        get_completed_turn("owner", thread["id"], "attempt")["retry_request"] == request
    )
    assert get_messages("other", thread["id"]) == []
    assert get_completed_turn("other", thread["id"], "attempt") is None


@pytest.mark.parametrize(
    "state,failed",
    [
        ({"graph_operation": {"status": "failed"}}, True),
        ({"graph_publication": "preserved"}, True),
        ({"graph_publication": "withheld"}, True),
        ({"graph_publication": "approved"}, False),
        ({"graph_publication": "user_accepted"}, False),
        ({"graph_publication": "unchanged"}, False),
        (
            {
                "graph_operation": {"status": "needs_clarification"},
                "graph_publication": "withheld",
            },
            False,
        ),
        ({}, False),
    ],
)
def test_only_confirmed_failure_has_original_request(state, failed):
    body = ChatRequest(
        thread_id="thread",
        content="Original",
        complexity="production",
        graph_action="extend",
        expected_graph_version="old",
        diagram_requested=True,
        research_enabled=True,
    )
    result = body.failed_generation_retry_request(state)
    assert result == (
        body.model_dump(
            exclude={"thread_id", "client_request_id", "retry_source_request_id", "steering_updates"}
        )
        if failed
        else None
    )


def test_retry_content_byte_boundary_and_no_partial_writes(temp_data_dir, monkeypatch):
    init_db()
    upsert_profile("owner", "owner@example.com")
    thread = create_thread("owner")
    monkeypatch.setattr(settings, "max_message_bytes", 4)
    args = dict(
        title="Failed", user_content="draw", assistant_content="failed", graph_data=None
    )
    assert persist_turn(
        "owner", thread["id"], **args, retry_request=request_options("éé")
    )
    with pytest.raises(ValidationError):
        persist_turn(
            "owner", thread["id"], **args, retry_request=request_options("ééa")
        )
    assert len(get_messages("owner", thread["id"])) == 2
    with pytest.raises(ValidationError):
        persist_turn(
            "owner",
            thread["id"],
            **args,
            retry_request={**request_options("draw"), "access_token": "secret"},
        )
    assert len(get_messages("owner", thread["id"])) == 2


def test_sqlite_additive_upgrade_preserves_old_turns(temp_data_dir):
    init_db()
    upsert_profile("owner", "owner@example.com")
    thread = create_thread("owner")
    persist_turn(
        "owner",
        thread["id"],
        title="Old",
        user_content="old",
        assistant_content="answer",
        graph_data=None,
        client_request_id="old",
    )
    execute("ALTER TABLE chat_messages DROP COLUMN retry_request")
    init_db()
    assert all(
        row["retry_request"] is None for row in get_messages("owner", thread["id"])
    )
    assert (
        get_completed_turn("owner", thread["id"], "old")["assistant_content"]
        == "answer"
    )


def test_postgres_retry_migration_is_nullable_expand_with_bounded_locks(monkeypatch):
    path = (
        Path(__file__).parents[1]
        / "db/migrations/versions/20260930_0009_generation_retry.py"
    )
    spec = importlib.util.spec_from_file_location("retry_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    sql = " ".join(statements).lower()
    assert "lock_timeout = '5s'" in sql
    assert "add column retry_request jsonb" in sql
    assert "retry_request is null" in sql
    assert "role = 'assistant'" in sql
    assert "not valid" in sql
    assert "update " not in sql
    assert "drop " not in sql
    assert migration.down_revision == "20260929_0008"


@pytest.mark.parametrize("corrupt", ["not-json", '{"access_token":"secret"}'])
def test_corrupt_optional_retry_metadata_does_not_hide_conversation(
    temp_data_dir, caplog, corrupt
):
    init_db()
    upsert_profile("owner", "owner@example.com")
    thread = create_thread("owner")
    persist_turn(
        "owner",
        thread["id"],
        title="Failed",
        user_content="draw",
        assistant_content="failed",
        graph_data=None,
        client_request_id="attempt",
    )
    execute(
        "UPDATE chat_messages SET retry_request = ? WHERE role = 'assistant'",
        (corrupt,),
    )
    messages = get_messages("owner", thread["id"])
    assert messages[-1]["content"] == "failed"
    assert messages[-1]["retry_request"] is None
    assert (
        get_completed_turn("owner", thread["id"], "attempt")["assistant_content"]
        == "failed"
    )
    assert "Ignoring invalid retry metadata" in caplog.text
    assert "access_token" not in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_failed_completed_turn_persists_original_options(
    temp_data_dir, monkeypatch, transport
):
    from fastapi.testclient import TestClient
    from test_api_security import _authed_app
    from test_chat_websocket import _ready_app, _receive_until

    if transport == "websocket":
        app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    else:
        init_db()
        user = {"id": "user-1"}
        upsert_profile(user["id"], "friend@example.com")
        thread = create_thread(user["id"])
        app = _authed_app()

    async def failed_agent(state, *_tools):
        await state["send"]({"type": "response_delta", "content": "Diagram failed"})
        await state["send"]({"type": "generation_failed"})
        return {
            **state,
            "response_text": "Diagram failed",
            "graph_operation": {"kind": "create", "status": "failed"},
            "graph_publication": "withheld",
        }

    monkeypatch.setattr("api.sse_handler.run_agent", failed_agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", failed_agent)
    request = dict(
        content="Original diagram request",
        complexity="production",
        graph_mode="on",
        diagram_requested=True,
        research_enabled=True,
        graph_action="new",
        expected_graph_version=None,
    )
    payload = {
        **request,
        "thread_id": thread["id"],
        "client_request_id": "failed-attempt",
    }
    with TestClient(app) as client:
        if transport == "sse":
            response = client.post("/api/chat", json=payload)
            assert "generation_failed" in response.text
        else:
            with client.websocket_connect(
                "/api/chat/ws", headers={"origin": "http://localhost:5173"}
            ) as socket:
                socket.send_json({"type": "auth", "access_token": "test-token"})
                assert socket.receive_json()["type"] == "ready"
                socket.send_json({"type": "start", **payload})
                events = _receive_until(socket, "done")
                assert {"type": "generation_failed"} in events
    completed = get_completed_turn(user["id"], thread["id"], "failed-attempt")
    assert completed["retry_request"] == request
    assert get_messages(user["id"], thread["id"])[-1]["retry_request"] == request


@pytest.mark.parametrize("source_kind", ["missing", "success", "other_owner"])
def test_retry_source_requires_owned_confirmed_failure(temp_data_dir, source_kind):
    init_db()
    upsert_profile("owner", "owner@example.com")
    thread = create_thread("owner")
    if source_kind != "missing":
        persist_turn(
            "owner",
            thread["id"],
            title="Source",
            user_content="draw",
            assistant_content="result",
            graph_data=None,
            client_request_id="source",
            retry_request=request_options("draw")
            if source_kind == "other_owner"
            else None,
        )
    body = ChatRequest(
        thread_id=thread["id"],
        content="draw",
        client_request_id="fresh",
        retry_source_request_id="source",
    )
    with pytest.raises(ValueError, match="^Retry request is unavailable$"):
        body.resolve_retry_source("other" if source_kind == "other_owner" else "owner")


def test_retry_restores_effective_content_and_original_options_across_chain(
    temp_data_dir,
):
    init_db()
    upsert_profile("owner", "owner@example.com")
    thread = create_thread("owner")
    original = request_options("Original")
    original.update(
        graph_action="extend", expected_graph_version="old", complexity="production"
    )
    effective = (
        "Original\n\nUser steering update 1:\n" + "a" * settings.max_message_bytes
    )
    persist_turn(
        "owner",
        thread["id"],
        title="Failed",
        user_content=effective,
        assistant_content="failed",
        graph_data=None,
        client_request_id="source",
        retry_request=original,
    )
    body = ChatRequest(
        thread_id=thread["id"],
        content="Ignored client words",
        client_request_id="fresh",
        retry_source_request_id="source",
        expected_graph_version="current",
    )
    resolved, options = body.resolve_retry_source("owner")
    assert resolved.content == effective
    assert resolved.complexity == "production"
    assert resolved.graph_action == "extend"
    assert resolved.expected_graph_version == "current"
    assert options["content"] == "Original"
    retry = resolved.failed_generation_retry_request(
        {"graph_publication": "withheld"}, options
    )
    persist_turn(
        "owner",
        thread["id"],
        title="Failed",
        user_content=resolved.content,
        assistant_content="failed again",
        graph_data=None,
        client_request_id="fresh",
        retry_request=retry,
    )
    chain = body.model_copy(
        update={"retry_source_request_id": "fresh", "client_request_id": "fresh-again"}
    )
    resolved_chain, options_chain = chain.resolve_retry_source("owner")
    assert resolved_chain.content == effective
    assert options_chain == options


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_retry_transport_repeats_effective_request_and_replays_duplicate(
    temp_data_dir, monkeypatch, transport
):
    from fastapi.testclient import TestClient
    from test_api_security import _authed_app, _parse_sse_events
    from test_chat_websocket import _ready_app, _receive_until

    if transport == "websocket":
        app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    else:
        init_db()
        user = {"id": "user-1"}
        upsert_profile(user["id"], "friend@example.com")
        thread = create_thread(user["id"])
        app = _authed_app()
    effective = (
        "Original\n\nUser steering update 1:\n" + "a" * settings.max_message_bytes
    )
    original = request_options("Original")
    original.update(graph_action="new", diagram_requested=True)
    persist_turn(
        user["id"],
        thread["id"],
        title="Failed",
        user_content=effective,
        assistant_content="failed",
        graph_data=None,
        client_request_id="source",
        retry_request=original,
    )
    calls = []

    async def failed_agent(state, *_tools):
        calls.append(state["user_message"])
        await state["send"]({"type": "response_delta", "content": "failed again"})
        return {
            **state,
            "response_text": "failed again",
            "graph_publication": "withheld",
        }

    monkeypatch.setattr("api.sse_handler.run_agent", failed_agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", failed_agent)
    payload = dict(
        thread_id=thread["id"],
        content="Original",
        client_request_id="fresh",
        retry_source_request_id="source",
    )
    with TestClient(app) as client:
        for _ in range(2):
            if transport == "sse":
                events = _parse_sse_events(client.post("/api/chat", json=payload).text)
            else:
                with client.websocket_connect(
                    "/api/chat/ws", headers={"origin": "http://localhost:5173"}
                ) as socket:
                    socket.send_json({"type": "auth", "access_token": "test-token"})
                    assert socket.receive_json()["type"] == "ready"
                    socket.send_json({"type": "start", **payload})
                    events = _receive_until(socket, "done")
            assert events[-1] == {"type": "done"}
        too_large = {
            **payload,
            "content": "x" * (settings.max_message_bytes + 1),
            "client_request_id": "oversized",
        }
        if transport == "sse":
            assert "Message too large" in client.post("/api/chat", json=too_large).text
    assert calls == [effective]
    assert len(get_messages(user["id"], thread["id"])) == 4
    completed = get_completed_turn(user["id"], thread["id"], "fresh")
    assert completed["user_content"] == effective
    assert completed["retry_request"] == original


@pytest.mark.parametrize("effective_extra", [0, 1])
def test_retry_canonical_envelope_boundary(temp_data_dir, effective_extra):
    from api.sse_handler import max_effective_message_bytes

    init_db()
    upsert_profile("owner", "owner@example.com")
    thread = create_thread("owner")
    effective = "x" * (max_effective_message_bytes() + effective_extra)
    persist_turn(
        "owner",
        thread["id"],
        title="Failed",
        user_content=effective,
        assistant_content="failed",
        graph_data=None,
        client_request_id="source",
        retry_request=request_options(),
    )
    body = ChatRequest(
        thread_id=thread["id"],
        content="draw",
        client_request_id="fresh",
        retry_source_request_id="source",
    )
    if effective_extra:
        with pytest.raises(ValueError, match="^Retry request is unavailable$"):
            body.resolve_retry_source("owner")
    else:
        assert body.resolve_retry_source("owner")[0].content == effective


def test_retry_overflow_steer_preserves_active_agent(temp_data_dir, monkeypatch):
    import asyncio
    import threading
    from fastapi.testclient import TestClient
    from api.sse_handler import max_effective_message_bytes
    from test_chat_websocket import _ready_app, _receive_until

    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    effective = "x" * max_effective_message_bytes()
    persist_turn(
        user["id"],
        thread["id"],
        title="Failed",
        user_content=effective,
        assistant_content="failed",
        graph_data=None,
        client_request_id="source",
        retry_request=request_options(),
    )
    release = threading.Event()
    cancelled = []

    async def pending_agent(state, *_tools):
        await state["send"]({"type": "response_delta", "content": "pending"})
        try:
            while not release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return {**state, "response_text": "completed", "graph_publication": "withheld"}

    monkeypatch.setattr("api.chat_websocket.run_agent", pending_agent)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json()["type"] == "ready"
            socket.send_json(
                dict(
                    type="start",
                    thread_id=thread["id"],
                    content="draw",
                    client_request_id="fresh",
                    retry_source_request_id="source",
                )
            )
            _receive_until(socket, "response_delta")
            socket.send_json(
                dict(type="steer", client_request_id="fresh", content="new requirement")
            )
            rejected = _receive_until(socket, "command_rejected")
            assert rejected[-1]["type"] == "command_rejected"
            release.set()
            _receive_until(socket, "done")
    assert cancelled == []
    assert (
        get_completed_turn(user["id"], thread["id"], "fresh")["user_content"]
        == effective
    )


@pytest.mark.parametrize(
    "updates",
    [
        [" "],
        ["é" * (settings.max_message_bytes // 2) + "a"],
        ["one", "two", "three", "four"],
    ],
)
def test_replayed_steering_rejects_invalid_updates(updates):
    with pytest.raises(ValidationError):
        ChatRequest(thread_id="thread", content="Original", steering_updates=updates)


def test_replayed_steering_normalizes_whitespace_and_accepts_unicode_byte_boundary():
    updates = [" \t use  queues\n please ", "é" * (settings.max_message_bytes // 2)]
    body = ChatRequest(thread_id="thread", content="Original", steering_updates=updates)
    resolved, original = body.resolve_retry_source("owner")
    assert body.steering_updates == ["use queues please", updates[1]]
    assert resolved.content == (
        "Original\n\nUser steering update 1:\nuse queues please"
        f"\n\nUser steering update 2:\n{updates[1]}"
    )
    assert original["content"] == "Original"
    assert "steering_updates" not in original


@pytest.mark.parametrize("transport", ["sse", "websocket"])
def test_uncertain_retry_restores_two_steers_and_replays_completed_id(
    temp_data_dir, monkeypatch, transport
):
    from fastapi.testclient import TestClient
    from test_api_security import _authed_app, _parse_sse_events
    from test_chat_websocket import _ready_app, _receive_until

    if transport == "websocket":
        app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    else:
        init_db()
        user = {"id": "user-1"}
        upsert_profile(user["id"], "friend@example.com")
        thread = create_thread(user["id"])
        app = _authed_app()
    calls = []

    async def failed_agent(state, *_tools):
        calls.append(state["user_message"])
        return {**state, "response_text": "failed", "graph_publication": "withheld"}

    monkeypatch.setattr("api.sse_handler.run_agent", failed_agent)
    monkeypatch.setattr("api.chat_websocket.run_agent", failed_agent)
    payload = dict(
        thread_id=thread["id"],
        content="Original",
        client_request_id="uncertain",
        steering_updates=["use queues", "include retries"],
    )
    with TestClient(app) as client:
        for _ in range(2):
            if transport == "sse":
                events = _parse_sse_events(client.post("/api/chat", json=payload).text)
            else:
                with client.websocket_connect(
                    "/api/chat/ws", headers={"origin": "http://localhost:5173"}
                ) as socket:
                    socket.send_json({"type": "auth", "access_token": "test-token"})
                    assert socket.receive_json()["type"] == "ready"
                    socket.send_json({"type": "start", **payload})
                    events = _receive_until(socket, "done")
            assert events[-1] == {"type": "done"}
    effective = (
        "Original\n\nUser steering update 1:\nuse queues"
        "\n\nUser steering update 2:\ninclude retries"
    )
    assert calls == [effective]
    completed = get_completed_turn(user["id"], thread["id"], "uncertain")
    assert completed["user_content"] == effective
    assert completed["retry_request"] == request_options("Original")
    assert len(get_messages(user["id"], thread["id"])) == 2


def test_retry_source_restored_before_replayed_steering_and_envelope_checked(
    temp_data_dir,
):
    from api.sse_handler import max_effective_message_bytes

    init_db()
    upsert_profile("owner", "owner@example.com")
    thread = create_thread("owner")
    source = "Original\n\nUser steering update 1:\nprevious correction"
    for request_id, content in [("source", source), ("full", "x" * max_effective_message_bytes())]:
        persist_turn(
            "owner", thread["id"], title="Failed", user_content=content,
            assistant_content="failed", graph_data=None, client_request_id=request_id,
            retry_request=request_options("Original"),
        )
    body = ChatRequest(
        thread_id=thread["id"], content="Ignored", client_request_id="new",
        retry_source_request_id="source", steering_updates=["new correction"],
    )
    resolved, original = body.resolve_retry_source("owner")
    assert resolved.content == source + "\n\nUser steering update 1:\nnew correction"
    assert original["content"] == "Original"
    with pytest.raises(ValueError, match="^Retry request is unavailable$"):
        body.model_copy(update={"retry_source_request_id": "full"}).resolve_retry_source("owner")


def test_replayed_steering_runs_security_filter_after_normalization(monkeypatch):
    checked = []

    def reject_update(update):
        checked.append(update)
        return False

    monkeypatch.setattr("api.sse_handler.check_prompt_injection", reject_update)
    with pytest.raises(ValidationError):
        ChatRequest(
            thread_id="thread", content="Original",
            steering_updates=[" \t unsafe \n instructions "],
        )
    assert checked == ["unsafe instructions"]


def test_disconnect_before_persist_then_retry_preserves_accepted_steering(
    temp_data_dir, monkeypatch
):
    import asyncio
    from fastapi.testclient import TestClient
    from test_chat_websocket import _ready_app, _receive_until

    app, user, thread = _ready_app(temp_data_dir, monkeypatch)
    calls = []
    complete = False

    async def agent(state, *_tools):
        calls.append(state["user_message"])
        if not complete:
            await state["send"]({"type": "response_delta", "content": "draft"})
            await asyncio.Event().wait()
        return {**state, "response_text": "failed", "graph_publication": "withheld"}

    monkeypatch.setattr("api.chat_websocket.run_agent", agent)
    payload = dict(thread_id=thread["id"], content="Original", client_request_id="lost")
    updates = ["use queues", "include retries"]
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json()["type"] == "ready"
            socket.send_json({"type": "start", **payload})
            _receive_until(socket, "response_delta")
            for number, update in enumerate(updates, start=1):
                socket.send_json({"type": "steer", "client_request_id": "lost", "content": update})
                assert _receive_until(socket, "steer_applied")[-1]["steer_count"] == number
                _receive_until(socket, "response_delta")
        assert get_completed_turn(user["id"], thread["id"], "lost") is None
        complete = True
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json()["type"] == "ready"
            socket.send_json({"type": "start", **payload, "steering_updates": updates})
            _receive_until(socket, "done")
    effective = (
        "Original\n\nUser steering update 1:\nuse queues"
        "\n\nUser steering update 2:\ninclude retries"
    )
    assert len(calls) == 4
    assert calls[-2:] == [effective, effective]
    completed = get_completed_turn(user["id"], thread["id"], "lost")
    assert completed["user_content"] == effective
    assert completed["retry_request"] == request_options("Original")
