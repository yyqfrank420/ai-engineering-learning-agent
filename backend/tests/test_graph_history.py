import copy
import json

import pytest
from fastapi.testclient import TestClient

from adapters.database_adapter import execute, fetchone, init_db
from adapters.supabase_auth_adapter import get_current_user
from graph.content_edit import GraphEditConflict, GraphEditInvalid, GraphEditNotFound
from main import create_app
from storage import graph_history_store as history, runtime_state_store
from storage.message_store import get_messages
from storage.profile_store import upsert_profile
from storage.thread_store import (
    create_thread,
    delete_thread,
    get_graph,
    get_graph_artifact,
    get_thread,
    persist_turn,
    save_graph,
)


def graph(version):
    return {
        "version": version,
        "title": version,
        "nodes": [{"id": "a", "label": version}],
        "edges": [],
    }


def save(thread, value, request_id=None):
    current, _, revision_id = get_graph_artifact("owner", thread)
    return persist_turn(
        "owner",
        thread,
        expected_graph_version=(current or {}).get("version"),
        base_revision_id=revision_id,
        title="Test",
        user_content=value["title"] if value else "Question",
        assistant_content="Answer",
        graph_data=value,
        graph_contract={"graph_version": value["version"], "private": "secret-contract"}
        if value
        else None,
        client_request_id=request_id,
    )


@pytest.fixture
def thread(temp_data_dir):
    init_db()
    upsert_profile("owner", "owner@example.test")
    upsert_profile("other", "other@example.test")
    return create_thread("owner")["id"]


def test_generation_undo_redo_branch_messages_and_noop(thread):
    save(thread, graph("A"), "request-a")
    a = history.list_history("owner", thread)["current_revision_id"]
    save(thread, graph("B"), "request-b")
    state = history.list_history("owner", thread)
    b = state["current_revision_id"]
    assert [r["revision_number"] for r in state["revisions"]] == [1, 2]
    assert state["revisions"][1]["parent_revision_id"] == a
    restored = history.restore_revision("owner", thread, a, "B")
    assert restored["graph_data"]["title"] == "A"
    assert restored["graph_data"]["version"] not in {"A", "B"}
    assert (
        get_graph_artifact("owner", thread)[1]["graph_version"]
        == restored["graph_data"]["version"]
    )
    assert history.restore_revision("owner", thread, a, "B") == restored
    redone = history.restore_revision(
        "owner", thread, b, restored["graph_data"]["version"]
    )
    assert redone["graph_data"]["title"] == "B"
    history.restore_revision("owner", thread, a, redone["graph_data"]["version"])
    save(thread, graph("C"))
    state = history.list_history("owner", thread)
    assert state["revisions"][2]["parent_revision_id"] == a
    assert history.get_revision("owner", thread, b)["graph_data"]["title"] == "B"
    messages = get_messages("owner", thread)
    assert messages[1]["graph_revision_id"] == a
    assert messages[1]["client_request_id"] == "request-a"
    assert messages[0]["graph_revision_id"] is None
    save(thread, None)
    save(thread, get_graph("owner", thread))
    save(thread, graph("B"), "request-b")
    assert len(history.list_history("owner", thread)["revisions"]) == 3
    assert get_messages("owner", thread)[-1]["graph_revision_id"] is None


def test_layout_is_revision_local_and_latest_positions_survive_generation(thread):
    a_graph = graph("A")
    save(thread, a_graph)
    a = history.list_history("owner", thread)["current_revision_id"]
    view = {
        "layoutVersion": 1,
        "nodePositions": {"a": {"x": 9, "y": 12}, "removed": {"x": 1, "y": 1}},
        "viewport": {"x": 2, "y": 3, "k": 1},
    }
    assert save_graph("owner", thread, {"version": "A", "view_state": view})
    save(thread, graph("B"))
    assert get_graph("owner", thread)["view_state"]["nodePositions"] == {
        "a": {"x": 9, "y": 12}
    }
    b_view = copy.deepcopy(view)
    b_view["nodePositions"]["a"]["x"] = 88
    save_graph("owner", thread, {"version": "B", "view_state": b_view})
    restored = history.restore_revision("owner", thread, a, "B")
    assert restored["graph_data"]["view_state"] == view
    save_graph("owner", thread, {"version": "A", "view_state": b_view})
    assert get_graph("owner", thread) == restored["graph_data"]
    assert history.get_revision("owner", thread, a)["graph_data"]["version"] == "A"


def test_stale_restore_and_owner_scope(thread):
    save(thread, graph("A"))
    a = history.list_history("owner", thread)["current_revision_id"]
    save(thread, graph("B"))
    with pytest.raises(GraphEditConflict):
        history.restore_revision("owner", thread, a, "A")
    for operation in [
        lambda: history.list_history("other", thread),
        lambda: history.get_revision("other", thread, a),
        lambda: history.restore_revision("other", thread, a, "B"),
    ]:
        with pytest.raises(GraphEditNotFound):
            operation()
    assert get_graph("owner", thread)["version"] == "B"


def test_legacy_seed_and_delete_cascade(thread):
    execute(
        "UPDATE chat_threads SET graph_data = ? WHERE id = ?",
        (json.dumps(graph("legacy")), thread),
    )
    state = history.list_history("owner", thread)
    assert len(state["revisions"]) == 1
    assert history.list_history("owner", thread) == state
    save(thread, graph("next"))
    delete_thread("owner", thread)
    assert (
        fetchone(
            "SELECT COUNT(*) AS n FROM graph_revisions WHERE thread_id = ?", (thread,)
        )["n"]
        == 0
    )


def test_legacy_seed_before_replacement(thread):
    execute(
        "UPDATE chat_threads SET graph_data = ? WHERE id = ?",
        (json.dumps(graph("legacy")), thread),
    )
    save(thread, graph("new"))
    state = history.list_history("owner", thread)
    assert len(state["revisions"]) == 2
    assert (
        history.get_revision("owner", thread, state["revisions"][0]["id"])[
            "graph_data"
        ]["version"]
        == "legacy"
    )


def test_history_api_excludes_contract_and_allows_restore_during_generation(thread):
    save(thread, graph("A"))
    a = history.list_history("owner", thread)["current_revision_id"]
    save(thread, graph("B"))
    app = create_app(load_resources=False)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "owner",
        "email": "owner@example.test",
    }
    with TestClient(app) as client:
        path = f"/api/threads/{thread}/graph"
        assert "secret-contract" not in client.get(path + "/history").text
        assert "secret-contract" not in client.get(path + "/history/" + a).text
        lease = runtime_state_store.register_active_stream(
            "owner", "chat-thread", ttl_s=60, scope_id=thread
        )
        try:
            assert (
                client.post(
                    path + "/restore", json={"revision_id": a, "expected_version": "B"}
                ).status_code
                == 200
            )
        finally:
            runtime_state_store.release_active_stream(lease)
        response = client.post(
            path + "/restore", json={"revision_id": a, "expected_version": "B"}
        )
        assert response.status_code == 200
        assert "secret-contract" not in response.text
        assert response.json()["revision_id"] == a
        assert (
            client.post(
                path + "/restore",
                json={"revision_id": "invalid", "expected_version": "B"},
            ).status_code
            == 422
        )


def test_old_writer_changes_are_archived_and_layout_reconciled(thread):
    save(thread, graph("A"))
    a = history.list_history("owner", thread)["current_revision_id"]
    layout = {"nodePositions": {"a": {"x": 99, "y": 1}}}
    current = {**graph("A"), "view_state": layout}
    execute(
        "UPDATE chat_threads SET graph_data = ? WHERE id = ?",
        (json.dumps(current), thread),
    )
    assert history.list_history("owner", thread)["current_revision_id"] == a
    assert (
        history.get_revision("owner", thread, a)["graph_data"]["view_state"] == layout
    )
    execute(
        "UPDATE chat_threads SET graph_data = ?, graph_contract = NULL WHERE id = ?",
        (json.dumps(graph("old-writer-B")), thread),
    )
    save(thread, graph("C"))
    state = history.list_history("owner", thread)
    assert [r["label"] for r in state["revisions"]] == ["A", "old-writer-B", "C"]
    assert state["revisions"][1]["parent_revision_id"] == a
    assert state["revisions"][2]["parent_revision_id"] == state["revisions"][1]["id"]


def test_unrelated_graph_does_not_inherit_viewport(thread):
    save(thread, graph("A"))
    save_graph(
        "owner",
        thread,
        {
            "version": "A",
            "view_state": {
                "nodePositions": {"a": {"x": 9, "y": 1}},
                "viewport": {"k": 10},
            },
        },
    )
    new = graph("B")
    new["nodes"][0]["id"] = "unrelated"
    save(thread, new)
    assert "view_state" not in get_graph("owner", thread)


def test_content_edit_creates_revision_and_noop_does_not(thread):
    from graph.content_edit import GraphContentEditRequest
    from storage.thread_store import edit_graph_content

    save(thread, graph("A"))
    before = history.list_history("owner", thread)
    edited = edit_graph_content(
        "owner",
        thread,
        GraphContentEditRequest(
            expected_version="A", nodes=[{"id": "a", "label": "Changed"}]
        ),
    )
    state = history.list_history("owner", thread)
    assert len(state["revisions"]) == 2
    assert state["revisions"][1]["parent_revision_id"] == before["current_revision_id"]
    assert state["revisions"][1]["label"] == "Edited A"
    edit_graph_content(
        "owner",
        thread,
        GraphContentEditRequest(
            expected_version=edited["version"], nodes=[{"id": "a", "label": "Changed"}]
        ),
    )
    assert len(history.list_history("owner", thread)["revisions"]) == 2


def test_database_rejects_cross_thread_and_owner_links(thread):
    import sqlite3

    save(thread, graph("A"))
    revision = history.list_history("owner", thread)["current_revision_id"]
    other = create_thread("other")["id"]
    with pytest.raises(sqlite3.IntegrityError):
        execute(
            "UPDATE chat_threads SET active_graph_revision_id = ? WHERE id = ?",
            (revision, other),
        )
    with pytest.raises(sqlite3.IntegrityError):
        execute(
            "UPDATE graph_revisions SET user_id = ? WHERE id = ?", ("other", revision)
        )
    with pytest.raises(sqlite3.IntegrityError):
        execute(
            "INSERT INTO chat_messages (id,thread_id,user_id,role,content,graph_revision_id) VALUES (?,?,?,?,?,?)",
            ("bad", other, "other", "assistant", "test", revision),
        )


def test_concurrent_generations_from_same_base_create_siblings(thread):
    from concurrent.futures import ThreadPoolExecutor

    save(thread, graph("A"))
    base = get_thread("owner", thread)["active_graph_revision_id"]

    def complete(number):
        value = graph(f"version-{number}")
        value["view_state"] = {"nodePositions": {"a": {"x": number, "y": 1}}}
        assert persist_turn(
            "owner", thread, title=f"Title {number}", user_content=f"Request {number}",
            assistant_content=f"Answer {number}", graph_data=value,
            expected_graph_version="A", base_revision_id=base,
            client_request_id=f"request-{number}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(complete, range(2)))
    state = history.list_history("owner", thread)
    assert [item["revision_number"] for item in state["revisions"]] == [1, 2, 3]
    assert [item["parent_revision_id"] for item in state["revisions"]] == [None, base, base]
    assert state["current_revision_id"] == state["revisions"][1]["id"]
    active = get_graph("owner", thread)
    active_number = int(active["version"].split("-")[-1])
    assert get_thread("owner", thread)["title"] == f"Title {active_number}"
    messages = get_messages("owner", thread)
    assert len(messages) == 6
    assert len({item["graph_revision_id"] for item in messages if item["role"] == "assistant"}) == 3
    branch = history.get_revision("owner", thread, state["revisions"][2]["id"])["graph_data"]
    assert branch["view_state"]["nodePositions"]["a"]["x"] != active_number

    # A repeated stale completion must preserve the first response and revision.
    complete(1 - active_number)
    assert history.list_history("owner", thread) == state
    assert len(get_messages("owner", thread)) == 6


def test_answer_only_completion_cannot_restore_its_stale_starting_graph(thread):
    save(thread, graph("A"))
    base = get_thread("owner", thread)["active_graph_revision_id"]
    save(thread, graph("B"))
    assert persist_turn(
        "owner", thread, title="Old title", user_content="Explain A",
        assistant_content="Answer", graph_data=None,
        expected_graph_version="A", base_revision_id=base,
    )
    assert get_graph("owner", thread)["version"] == "B"
    assert len(history.list_history("owner", thread)["revisions"]) == 2
    assert get_messages("owner", thread)[-1]["graph_revision_id"] is None


def test_postgres_uuid_active_pointer_is_normalized_for_restore_retry(monkeypatch):
    import uuid
    from contextlib import contextmanager

    active = uuid.uuid4()
    current = graph("fresh-activation")
    row = {
        "graph_data": current,
        "graph_contract": None,
        "active_graph_revision_id": active,
    }

    class Cursor:
        def fetchone(self):
            return {
                "graph_data": {**current, "version": "original"},
                "graph_contract": None,
            }

    class Connection:
        def execute(self, *args):
            return Cursor()

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(history, "_connect", connect)
    monkeypatch.setattr(history, "lock_thread", lambda *args: row)
    assert history.restore_revision("owner", "thread", str(active), "previous-B") == {
        "revision_id": str(active),
        "graph_data": current,
    }


def test_generation_labels_distinguish_requests_and_are_bounded(thread):
    for version, request in [
        ("A", "Build a support pipeline"),
        ("B", "  Add\n\ta review queue " + "detail " * 40),
    ]:
        value = graph(version)
        value["title"] = "Support pipeline"
        persist_turn(
            "owner",
            thread,
            expected_graph_version=(get_graph("owner", thread) or {}).get("version"),
            base_revision_id=get_thread("owner", thread)["active_graph_revision_id"],
            title="Chat",
            user_content=request,
            assistant_content="Answer",
            graph_data=value,
        )
    revisions = history.list_history("owner", thread)["revisions"]
    assert revisions[0]["label"] == "Build a support pipeline"
    assert revisions[1]["label"] == ("Add a review queue " + "detail " * 40)[:160]
    assert len(revisions[1]["label"]) == 160


@pytest.mark.parametrize("parent_scope", ["same-owner-other-thread", "other-owner", "missing"])
def test_stale_generation_rejects_invalid_parent_without_partial_turn(thread, parent_scope):
    save(thread, graph("A"))
    if parent_scope == "missing":
        import uuid
        parent = str(uuid.uuid4())
    else:
        owner = "owner" if parent_scope == "same-owner-other-thread" else "other"
        foreign_thread = create_thread(owner)["id"]
        persist_turn(
            owner, foreign_thread, title="Foreign", user_content="Question",
            assistant_content="Answer", graph_data=graph("Foreign"),
            expected_graph_version=None, base_revision_id=None,
        )
        parent = get_thread(owner, foreign_thread)["active_graph_revision_id"]
    before = history.list_history("owner", thread)
    with pytest.raises(GraphEditInvalid, match="Parent graph revision not found"):
        persist_turn(
            "owner", thread, title="Stale", user_content="Stale request",
            assistant_content="Stale answer", graph_data=graph("Stale"),
            expected_graph_version="older", base_revision_id=parent,
        )
    assert history.list_history("owner", thread) == before
    assert len(get_messages("owner", thread)) == 2
    assert get_graph("owner", thread)["version"] == "A"


def test_parallel_versionless_results_cannot_replace_first_commit(thread):
    from concurrent.futures import ThreadPoolExecutor

    def complete(title):
        return persist_turn(
            "owner", thread, title=title, user_content=title,
            assistant_content="Answer", graph_data={"title": title, "nodes": [], "edges": []},
            expected_graph_version=None, base_revision_id=None,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(complete, ["First request", "Second request"]))
    state = history.list_history("owner", thread)
    assert len(state["revisions"]) == 2
    assert [revision["parent_revision_id"] for revision in state["revisions"]] == [None, None]
    assert state["current_revision_id"] == state["revisions"][0]["id"]
    active = history.get_revision("owner", thread, state["revisions"][0]["id"])["graph_data"]
    assert get_graph("owner", thread) == active
    assert get_thread("owner", thread)["title"] == active["title"]
    assert len(get_messages("owner", thread)) == 4
