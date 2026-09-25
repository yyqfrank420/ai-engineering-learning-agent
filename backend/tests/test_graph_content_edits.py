import copy
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

import api.chat_websocket as chat_websocket
from adapters.database_adapter import init_db
from adapters.supabase_auth_adapter import get_current_user
from agent.graph_identity import applied_edge_metadata
from config import settings
from graph.content_edit import GraphContentEditRequest, GraphEditConflict
from main import create_app
from storage import runtime_state_store, thread_store
from storage.profile_store import upsert_profile
from storage.thread_store import (
    create_thread,
    edit_graph_content,
    get_graph,
    get_graph_artifact,
    persist_turn,
)


def _graph(*, version="graph-v1"):
    return {
        "graph_type": "architecture",
        "design_origin": "applied",
        "version": version,
        "title": "Payment architecture",
        "nodes": [
            {
                "id": "gateway",
                "label": "Payment gateway",
                "type": "gateway",
                "technology": "HTTPS",
                "description": "Accepts payment requests.",
                "detail": "Evidence-backed detail.",
                "book_refs": ["chapter-1"],
            },
            {
                "id": "ledger",
                "label": "Payment ledger",
                "type": "datastore",
                "technology": "PostgreSQL",
                "description": "Stores payment state.",
                "detail": None,
            },
        ],
        "edges": [
            {
                "source": "gateway",
                "target": "ledger",
                "label": "writes payment",
                "technology": "SQL",
                "sync": "sync",
                "flow": "runtime",
                "description": "Persists one payment.",
                **applied_edge_metadata("gateway", "ledger", "writes payment"),
            },
            {
                "source": "ledger",
                "target": "gateway",
                "label": "returns receipt",
                "technology": "HTTPS",
                "sync": "sync",
                "flow": "runtime",
                "description": "Returns the stored receipt.",
                **applied_edge_metadata("ledger", "gateway", "returns receipt"),
            },
        ],
        "sequence": [
            {"step": 1, "nodes": ["gateway"], "description": "Accept request."},
            {"step": 2, "nodes": ["ledger"], "description": "Store payment."},
        ],
        "groups": [
            {
                "id": "runtime",
                "label": "Runtime",
                "kind": "runtime",
                "nodeIds": ["gateway", "ledger"],
            }
        ],
        "view_state": {
            "layoutVersion": 17,
            "nodePositions": {
                "gateway": {"x": 120, "y": 80},
                "ledger": {"x": 340, "y": 80},
            },
            "viewport": {"x": 7, "y": 11, "k": 1.2},
        },
    }


def _seed(graph=None, contract=None):
    init_db()
    upsert_profile("user-1", "first@example.com")
    upsert_profile("user-2", "second@example.com")
    thread = create_thread("user-1", "Payment architecture")
    graph = copy.deepcopy(graph if graph is not None else _graph())
    assert persist_turn(
        "user-1",
        thread["id"],
        title="Payment architecture",
        user_content="Design payments",
        assistant_content="Here is the architecture.",
        graph_data=graph,
        graph_contract=contract,
    )
    return thread["id"], graph


def _client(user_id="user-1"):
    app = create_app(load_resources=False)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": user_id,
        "email": f"{user_id}@example.com",
    }
    return TestClient(app)


def _patch(client, thread_id, version, *, nodes=None, edges=None):
    body = {"expected_version": version}
    if nodes is not None:
        body["nodes"] = nodes
    if edges is not None:
        body["edges"] = edges
    return client.patch(f"/api/threads/{thread_id}/graph", json=body)


def test_patch_persists_requested_content_and_preserves_graph_layout(temp_data_dir):
    thread_id, before = _seed()
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[
                {
                    "id": "gateway",
                    "label": "Payment intake",
                    "type": "service",
                    "description": "Validates each payment request.",
                }
            ],
            edges=[{"index": 0, "label": "records approved payment"}],
        )
        assert response.status_code == 200
        after = response.json()["graph_data"]
        assert (
            client.get(f"/api/threads/{thread_id}").json()["thread"]["graph_data"]
            == after
        )

    assert after == get_graph("user-1", thread_id)
    assert after["version"] != before["version"]
    assert after["nodes"][0]["label"] == "Payment intake"
    assert after["nodes"][0]["type"] == "service"
    assert after["nodes"][0]["description"] == "Validates each payment request."
    assert after["nodes"][1] == before["nodes"][1]
    assert after["edges"][0]["label"] == "records approved payment"
    assert after["edges"][0]["source"] == before["edges"][0]["source"]
    assert after["edges"][0]["target"] == before["edges"][0]["target"]
    assert {key: after["edges"][0][key] for key in ("edge_id", "relation")} == (
        applied_edge_metadata("gateway", "ledger", "records approved payment")
    )
    assert after["edges"][1] == before["edges"][1]
    for field in ("title", "sequence", "groups", "view_state"):
        assert after[field] == before[field]
    assert [node["id"] for node in after["nodes"]] == [
        node["id"] for node in before["nodes"]
    ]
    assert get_graph_artifact("user-1", thread_id) == (after, None)


def test_edit_invalidates_source_claims_and_prior_review_approval(temp_data_dir):
    graph = _graph()
    graph["nodes"][0].update(
        canonical_id="concept:payment_gateway",
        confidence=0.9,
        evidence_chunk_ids=["chunk-1"],
    )
    graph["edges"][0].update(confidence=0.8, supporting_chunk_ids=["chunk-2"])
    contract = {
        "graph_version": graph["version"],
        "source": "staged",
        "stage": "accepted",
        "maturity": "prototype",
        "capabilities": {
            "external_effects": True,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
        "objective": "Process approved payments",
        "component_gate": {"approved": True},
        "connection_gate": {"approved": True},
        "reviewed_graph_fingerprint": "prior-approval",
    }
    thread_id, before = _seed(graph, contract)
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[
                {"id": "gateway", "description": "Checks and routes approved payments."}
            ],
            edges=[{"index": 0, "label": "records approved payment"}],
        )
    assert response.status_code == 200
    after, stored_contract = get_graph_artifact("user-1", thread_id)
    assert after == response.json()["graph_data"]
    assert after["nodes"][0]["user_edited_fields"] == ["description"]
    for field in (
        "detail",
        "book_refs",
        "confidence",
        "evidence_chunk_ids",
        "canonical_id",
    ):
        assert field not in after["nodes"][0] or after["nodes"][0][field] is None
    assert after["edges"][0]["user_edited_fields"] == ["label"]
    for field in ("confidence", "supporting_chunk_ids"):
        assert field not in after["edges"][0]
    assert stored_contract == {
        "graph_version": after["version"],
        "source": "user_edit",
        "stage": "edited",
        "maturity": "prototype",
        "capabilities": {
            "external_effects": True,
            "retrieval_or_reuse": False,
            "learning_or_release": False,
        },
        "objective": "Process approved payments",
    }


def test_edge_index_selects_one_member_of_a_parallel_connection(temp_data_dir):
    graph = _graph()
    parallel = {
        **graph["edges"][0],
        "label": "writes payment audit",
        **applied_edge_metadata("gateway", "ledger", "writes payment audit"),
    }
    graph["edges"].insert(1, parallel)
    thread_id, before = _seed(graph)
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            edges=[{"index": 1, "label": "writes approved audit"}],
        )
    assert response.status_code == 200
    after = response.json()["graph_data"]
    assert after["edges"][0] == before["edges"][0]
    assert after["edges"][1]["label"] == "writes approved audit"
    assert after["edges"][2] == before["edges"][2]
    assert (
        after["edges"][1]["edge_id"]
        == applied_edge_metadata("gateway", "ledger", "writes approved audit")[
            "edge_id"
        ]
    )


def test_versionless_legacy_graph_can_be_edited_by_index(temp_data_dir):
    graph = _graph()
    del graph["version"]
    for edge in graph["edges"]:
        edge.pop("edge_id")
        edge.pop("relation")
    thread_id, before = _seed(graph)
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            None,
            edges=[{"index": 1, "label": "returns durable receipt"}],
        )
    assert response.status_code == 200
    after = response.json()["graph_data"]
    assert after["version"]
    assert after["edges"][0] == before["edges"][0]
    assert after["edges"][1]["label"] == "returns durable receipt"
    assert after["view_state"] == before["view_state"]
    assert get_graph_artifact("user-1", thread_id) == (after, None)


def test_next_chat_turn_reads_the_edited_graph_as_its_baseline(
    temp_data_dir, monkeypatch
):
    thread_id, before = _seed()
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "label": "Reviewed payment intake"}],
            edges=[{"index": 0, "label": "stores reviewed payment"}],
        )
    assert response.status_code == 200
    edited = response.json()["graph_data"]

    user = {"id": "user-1", "email": "first@example.com"}
    monkeypatch.setattr(chat_websocket, "get_current_user", lambda **_kwargs: user)
    observed = []

    async def agent(state, *_tools):
        observed.append(
            {
                "graph_data": copy.deepcopy(state["graph_data"]),
                "approved_graph_data": copy.deepcopy(state["approved_graph_data"]),
            }
        )
        return {**state, "response_text": "I used the edited graph."}

    monkeypatch.setattr(chat_websocket, "run_agent", agent)
    app = create_app(load_resources=False)
    app.state.vectorstore = object()
    app.state.parent_docs = [{"page_content": "payment design"}]
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws", headers={"origin": "http://localhost:5173"}
        ) as socket:
            socket.send_json({"type": "auth", "access_token": "test-token"})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_json(
                {
                    "type": "start",
                    "thread_id": thread_id,
                    "content": "Explain the updated design",
                    "client_request_id": "after-direct-edit",
                }
            )
            events = []
            for _ in range(20):
                event = socket.receive_json()
                events.append(event)
                if event.get("type") == "done":
                    break
            else:
                raise AssertionError(f"Chat turn did not complete: {events}")

    assert observed == [{"graph_data": edited, "approved_graph_data": edited}]
    assert {"type": "graph_data", "data": edited} in events


def test_noop_keeps_version_and_subsequent_edit_uses_current_version(temp_data_dir):
    contract = {
        "graph_version": "graph-v1",
        "source": "staged",
        "stage": "accepted",
        "maturity": "prototype",
        "component_gate": {"approved": True},
    }
    thread_id, before = _seed(contract=contract)
    with _client() as client:
        same = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "label": before["nodes"][0]["label"]}],
        )
        assert same.status_code == 200
        assert same.json()["graph_data"] == before
        assert get_graph_artifact("user-1", thread_id) == (before, contract)

        changed = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "description": "Checks the payment request."}],
        )
        assert changed.status_code == 200
        assert changed.json()["graph_data"]["version"] != before["version"]

    assert get_graph_artifact("user-1", thread_id)[0] == changed.json()["graph_data"]


def test_optional_technology_can_be_cleared_with_an_empty_string(temp_data_dir):
    thread_id, before = _seed()
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "technology": ""}],
            edges=[{"index": 0, "technology": ""}],
        )
    assert response.status_code == 200
    after = response.json()["graph_data"]
    assert after["nodes"][0]["technology"] == ""
    assert after["edges"][0]["technology"] == ""
    assert after["nodes"][0]["user_edited_fields"] == ["technology"]
    assert after["edges"][0]["user_edited_fields"] == ["technology"]
    assert after["edges"][0]["edge_id"] == before["edges"][0]["edge_id"]
    assert after["edges"][0]["relation"] == before["edges"][0]["relation"]


def test_stale_version_cannot_overwrite_a_newer_edit_or_layout(temp_data_dir):
    thread_id, before = _seed()
    with _client() as client:
        first = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "label": "New payment intake"}],
        )
        assert first.status_code == 200
        current = first.json()["graph_data"]
        stale = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "label": "Stale payment intake"}],
        )
        assert stale.status_code == 409

        stale_layout = client.put(
            f"/api/threads/{thread_id}/graph",
            json={
                "graph_data": {
                    "version": before["version"],
                    "view_state": {"viewport": {"k": 99}},
                }
            },
        )
        assert stale_layout.status_code == 204

    assert get_graph("user-1", thread_id) == current


def test_two_writers_of_the_same_version_cannot_both_commit(temp_data_dir):
    thread_id, before = _seed()
    gate = Barrier(2, timeout=10)

    def write(label):
        request = GraphContentEditRequest(
            expected_version=before["version"],
            nodes=[{"id": "gateway", "label": label}],
        )
        gate.wait()
        try:
            edit_graph_content("user-1", thread_id, request)
            return "saved"
        except GraphEditConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(write, "Writer one")
        second = pool.submit(write, "Writer two")
        statuses = sorted((first.result(), second.result()))

    assert statuses == ["conflict", "saved"]
    saved = get_graph("user-1", thread_id)
    assert saved["nodes"][0]["label"] in {"Writer one", "Writer two"}
    assert saved["version"] != before["version"]


def test_postgres_edit_locks_the_owned_graph_row_before_writing(
    temp_data_dir, monkeypatch
):
    current = _graph()

    class Cursor:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def __init__(self):
            self.queries = []

        def execute(self, query, params=()):
            self.queries.append((query, params))
            if query.startswith("SELECT graph_data, graph_contract"):
                return Cursor({"graph_data": current, "graph_contract": None})
            return Cursor()

    connection = Connection()

    @contextmanager
    def fake_connect():
        yield connection

    monkeypatch.setattr(settings, "supabase_db_url", "postgresql://example")
    monkeypatch.setattr(thread_store, "_connect", fake_connect)
    request = GraphContentEditRequest(
        expected_version=current["version"],
        nodes=[{"id": "gateway", "label": "Updated payment gateway"}],
    )

    updated = edit_graph_content("user-1", "thread-1", request)

    select_query, select_params = connection.queries[0]
    assert "FOR UPDATE" in select_query
    assert "id = %s AND user_id = %s" in select_query
    assert select_params == ("thread-1", "user-1")
    update_query, update_params = connection.queries[1]
    assert "WHERE id = %s AND user_id = %s" in update_query
    assert update_params[-2:] == ("thread-1", "user-1")
    assert json.loads(update_params[0]) == updated


def test_patch_does_not_disclose_or_modify_another_users_graph(temp_data_dir):
    thread_id, before = _seed()
    with _client("user-2") as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "label": "Unauthorized edit"}],
        )
        missing = _patch(
            client,
            "missing-thread",
            before["version"],
            nodes=[{"id": "gateway", "label": "Unauthorized edit"}],
        )
    assert response.status_code == missing.status_code == 404
    assert get_graph("user-1", thread_id) == before


def test_patch_requires_an_existing_graph(temp_data_dir):
    init_db()
    upsert_profile("user-1", "first@example.com")
    thread = create_thread("user-1")
    with _client() as client:
        response = _patch(
            client,
            thread["id"],
            None,
            nodes=[{"id": "gateway", "label": "Cannot create via content edit"}],
        )
    assert response.status_code == 404
    assert get_graph("user-1", thread["id"]) is None


@pytest.mark.parametrize(
    "body",
    [
        {
            "expected_version": "graph-v1",
            "nodes": [{"id": "missing", "label": "Unknown node"}],
        },
        {
            "expected_version": "graph-v1",
            "edges": [{"index": 2, "label": "Wrong edge"}],
        },
        {
            "expected_version": "graph-v1",
            "edges": [{"index": -1, "label": "Wrong edge"}],
        },
        {
            "expected_version": "graph-v1",
            "edges": [{"index": True, "label": "Wrong edge"}],
        },
        {"expected_version": "graph-v1", "nodes": [{"id": "gateway", "label": "   "}]},
        {
            "expected_version": "graph-v1",
            "nodes": [{"id": "gateway", "description": "   "}],
        },
        {
            "expected_version": "graph-v1",
            "nodes": [{"id": "gateway", "technology": None}],
        },
        {"expected_version": "graph-v1", "edges": [{"index": 0, "label": "   "}]},
        {"expected_version": "graph-v1", "edges": [{"index": 0, "technology": None}]},
        {
            "expected_version": "graph-v1",
            "nodes": [{"id": "gateway", "label": "x" * 61}],
        },
        {
            "expected_version": "graph-v1",
            "nodes": [{"id": "gateway", "description": "x" * 221}],
        },
        {
            "expected_version": "graph-v1",
            "nodes": [{"id": "gateway", "technology": "x" * 101}],
        },
        {"expected_version": "graph-v1", "edges": [{"index": 0, "label": "x" * 101}]},
        {
            "expected_version": "graph-v1",
            "edges": [{"index": 0, "description": "x" * 221}],
        },
        {
            "expected_version": "graph-v1",
            "edges": [{"index": 0, "technology": "x" * 101}],
        },
        {
            "expected_version": "graph-v1",
            "nodes": [{"id": "gateway", "type": "widget"}],
        },
        {"expected_version": "graph-v1", "edges": [{"index": 0, "sync": "later"}]},
        {"expected_version": "graph-v1", "edges": [{"index": 0, "flow": "secret"}]},
        {
            "expected_version": "graph-v1",
            "nodes": [{"id": "gateway", "label": "A", "source": "ledger"}],
        },
        {
            "expected_version": "graph-v1",
            "edges": [{"index": 0, "label": "A", "target": "gateway"}],
        },
        {
            "expected_version": "graph-v1",
            "nodes": [
                {"id": "gateway", "label": "A"},
                {"id": "gateway", "description": "B"},
            ],
        },
        {
            "expected_version": "graph-v1",
            "edges": [{"index": 0, "label": "A"}, {"index": 0, "description": "B"}],
        },
        {"nodes": [{"id": "gateway", "label": "Missing version"}]},
        {"expected_version": "graph-v1", "nodes": [{"id": "gateway"}]},
        {"expected_version": "graph-v1", "nodes": [], "edges": []},
    ],
)
def test_invalid_patch_is_atomic(temp_data_dir, body):
    thread_id, before = _seed()
    with _client() as client:
        response = client.patch(f"/api/threads/{thread_id}/graph", json=body)
    assert response.status_code == 422
    assert get_graph("user-1", thread_id) == before


def test_mixed_valid_and_invalid_updates_commit_nothing(temp_data_dir):
    thread_id, before = _seed()
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "label": "Valid change"}],
            edges=[{"index": 99, "label": "Invalid target"}],
        )
    assert response.status_code == 422
    assert get_graph("user-1", thread_id) == before


def test_rejects_label_collision_on_parallel_edges(temp_data_dir):
    graph = _graph()
    parallel = {
        **graph["edges"][0],
        "label": "writes payment audit",
        **applied_edge_metadata("gateway", "ledger", "writes payment audit"),
    }
    graph["edges"].append(parallel)
    thread_id, before = _seed(graph)
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            edges=[{"index": 0, "label": "writes payment audit"}],
        )
    assert response.status_code == 422
    assert get_graph("user-1", thread_id) == before


def test_rejects_flow_edit_that_conflicts_with_a_loop_edge(temp_data_dir):
    graph = _graph()
    graph["edges"][0].update(type="loop", flow="feedback")
    thread_id, before = _seed(graph)
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            edges=[{"index": 0, "flow": "runtime"}],
        )
    assert response.status_code == 422
    assert get_graph("user-1", thread_id) == before


def test_content_edit_rejects_an_active_generation_lease(temp_data_dir):
    thread_id, before = _seed()
    lease = runtime_state_store.try_acquire_active_stream(
        "user-1", "chat-thread", limit=1, ttl_s=60, scope_id=thread_id
    )
    assert lease is not None
    try:
        with _client() as client:
            response = _patch(
                client,
                thread_id,
                before["version"],
                nodes=[{"id": "gateway", "label": "Concurrent edit"}],
            )
        assert response.status_code == 409
        assert get_graph("user-1", thread_id) == before
    finally:
        runtime_state_store.release_active_stream(lease)


def test_oversized_result_rejects_without_partial_write(temp_data_dir, monkeypatch):
    thread_id, before = _seed()
    original_bytes = len(json.dumps(before, ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(settings, "max_graph_data_bytes", original_bytes + 1)
    with _client() as client:
        response = _patch(
            client,
            thread_id,
            before["version"],
            nodes=[{"id": "gateway", "description": "A" * 220}],
        )
    assert response.status_code == 413
    assert get_graph("user-1", thread_id) == before
