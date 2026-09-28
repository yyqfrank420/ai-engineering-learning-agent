"""Graph checkpoints; chat_threads holds the active materialization for existing readers.

Content commits create revisions under the owned thread lock. Layout changes update
that revision in place. Contracts are internal and never included in history responses.
"""

import copy
import json
import uuid
from typing import Any, Literal

from adapters.database_adapter import _adapt_query, _connect
from config import settings
from graph.content_edit import GraphEditConflict, GraphEditInvalid, GraphEditNotFound


def decode_graph_json(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def lock_thread(conn: Any, user_id: str, thread_id: str) -> Any:
    query = "SELECT graph_data, graph_contract, active_graph_revision_id FROM chat_threads WHERE id = ? AND user_id = ?"
    if settings.use_postgres:
        query += " FOR UPDATE"
    row = conn.execute(_adapt_query(query), (thread_id, user_id)).fetchone()
    if row is None:
        raise GraphEditNotFound("Thread not found")
    return row


def append_revision(
    conn: Any,
    user_id: str,
    thread_id: str,
    graph: dict[str, Any],
    contract: dict[str, Any] | None,
    *,
    parent_id: str | None,
    source: Literal["generation", "content_edit"],
    label: str | None = None,
) -> str:
    revision_id = str(uuid.uuid4())
    number = conn.execute(
        _adapt_query(
            "SELECT COALESCE(MAX(revision_number), 0) + 1 AS n FROM graph_revisions WHERE thread_id = ? AND user_id = ?"
        ),
        (thread_id, user_id),
    ).fetchone()["n"]
    title = str(graph.get("title") or "Diagram").strip() or "Diagram"
    fallback = title if source == "generation" else f"Edited {title}"
    label = " ".join((label or fallback).split())[:160] or fallback[:160]
    conn.execute(
        _adapt_query("""
        INSERT INTO graph_revisions
        (id, thread_id, user_id, parent_revision_id, revision_number, graph_data, graph_contract, label, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """),
        (
            revision_id,
            thread_id,
            user_id,
            parent_id,
            number,
            json.dumps(graph, ensure_ascii=False),
            json.dumps(contract, ensure_ascii=False) if contract else None,
            label,
            source,
        ),
    )
    conn.execute(
        _adapt_query(
            "UPDATE chat_threads SET active_graph_revision_id = ? WHERE id = ? AND user_id = ?"
        ),
        (revision_id, thread_id, user_id),
    )
    return revision_id


def seed_current(conn: Any, user_id: str, thread_id: str, row: Any) -> str | None:
    """Reconcile old writers that only update the active thread materialization."""
    graph = decode_graph_json(row["graph_data"])
    active = (
        str(row["active_graph_revision_id"])
        if row["active_graph_revision_id"]
        else None
    )
    if graph is None:
        if active:
            conn.execute(
                _adapt_query(
                    "UPDATE chat_threads SET active_graph_revision_id = NULL WHERE id = ? AND user_id = ?"
                ),
                (thread_id, user_id),
            )
        return None
    if not isinstance(graph, dict):
        raise GraphEditInvalid("Saved graph is invalid")
    contract = decode_graph_json(row["graph_contract"])
    if (
        not isinstance(contract, dict)
        or not graph.get("version")
        or contract.get("graph_version") != graph.get("version")
    ):
        contract = None
    if active:
        previous = conn.execute(
            _adapt_query(
                "SELECT graph_data, graph_contract FROM graph_revisions WHERE id = ? AND thread_id = ? AND user_id = ?"
            ),
            (active, thread_id, user_id),
        ).fetchone()
        if previous is None:
            raise GraphEditInvalid("Saved graph revision is invalid")
        snapshot = decode_graph_json(previous["graph_data"])
        snapshot_content = {
            key: item
            for key, item in snapshot.items()
            if key not in {"version", "view_state"}
        }
        current_content = {
            key: item
            for key, item in graph.items()
            if key not in {"version", "view_state"}
        }
        if snapshot_content == current_content:
            synchronized = {**graph}
            if "version" in snapshot:
                synchronized["version"] = snapshot["version"]
            else:
                synchronized.pop("version", None)
            snapshot_contract = (
                {**contract, "graph_version": snapshot.get("version")}
                if contract and snapshot.get("version")
                else None
            )
            conn.execute(
                _adapt_query(
                    "UPDATE graph_revisions SET graph_data = ?, graph_contract = ? WHERE id = ? AND thread_id = ? AND user_id = ?"
                ),
                (
                    json.dumps(synchronized, ensure_ascii=False),
                    json.dumps(snapshot_contract, ensure_ascii=False)
                    if snapshot_contract
                    else None,
                    active,
                    thread_id,
                    user_id,
                ),
            )
            return active
    return append_revision(
        conn, user_id, thread_id, graph, contract, parent_id=active, source="generation"
    )


def preserve_latest_layout(graph: dict, current: dict | None) -> dict:
    """Retained stable nodes keep positions saved while generation was running."""
    if not current or not isinstance(current.get("view_state"), dict):
        return graph
    node_ids = {
        node["id"]
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and "id" in node
    }
    current_ids = {
        node["id"]
        for node in current.get("nodes", [])
        if isinstance(node, dict) and "id" in node
    }
    if not node_ids.intersection(current_ids):
        return graph
    result = copy.deepcopy(graph)
    view = copy.deepcopy(current["view_state"])
    positions = view.get("nodePositions")
    if isinstance(positions, dict):
        view["nodePositions"] = {
            key: value for key, value in positions.items() if key in node_ids
        }
    result["view_state"] = view
    return result


def list_history(user_id: str, thread_id: str) -> dict:
    with _connect() as conn:
        if not settings.use_postgres:
            conn.execute("BEGIN IMMEDIATE")
        row = lock_thread(conn, user_id, thread_id)
        active = seed_current(conn, user_id, thread_id, row)
        rows = conn.execute(
            _adapt_query("""
            SELECT id, parent_revision_id, revision_number, label, created_at, graph_data
            FROM graph_revisions WHERE thread_id = ? AND user_id = ? ORDER BY revision_number
        """),
            (thread_id, user_id),
        ).fetchall()
        revisions = []
        for item in rows:
            item = dict(item)
            graph = decode_graph_json(item.pop("graph_data"))
            revisions.append(
                {
                    **item,
                    "node_count": len(graph.get("nodes", [])),
                    "edge_count": len(graph.get("edges", [])),
                }
            )
        return {"current_revision_id": active, "revisions": revisions}


def get_revision(user_id: str, thread_id: str, revision_id: str) -> dict:
    with _connect() as conn:
        if not settings.use_postgres:
            conn.execute("BEGIN IMMEDIATE")
        thread = lock_thread(conn, user_id, thread_id)
        seed_current(conn, user_id, thread_id, thread)
        row = conn.execute(
            _adapt_query("""
            SELECT graph_data FROM graph_revisions WHERE id = ? AND thread_id = ? AND user_id = ?
        """),
            (revision_id, thread_id, user_id),
        ).fetchone()
        if row is None:
            raise GraphEditNotFound("Graph revision not found")
        return {
            "revision_id": revision_id,
            "graph_data": decode_graph_json(row["graph_data"]),
        }


def restore_revision(
    user_id: str, thread_id: str, revision_id: str, expected_version: str | None
) -> dict:
    with _connect() as conn:
        if not settings.use_postgres:
            conn.execute("BEGIN IMMEDIATE")
        thread = lock_thread(conn, user_id, thread_id)
        active = seed_current(conn, user_id, thread_id, thread)
        target = conn.execute(
            _adapt_query("""
            SELECT graph_data, graph_contract FROM graph_revisions
            WHERE id = ? AND thread_id = ? AND user_id = ?
        """),
            (revision_id, thread_id, user_id),
        ).fetchone()
        if target is None:
            raise GraphEditNotFound("Graph revision not found")
        current = decode_graph_json(thread["graph_data"])
        if active == revision_id:
            return {"revision_id": active, "graph_data": current}
        if not isinstance(current, dict) or current.get("version") != expected_version:
            raise GraphEditConflict("Graph changed. Reload it before restoring.")
        graph = copy.deepcopy(decode_graph_json(target["graph_data"]))
        if not isinstance(graph, dict):
            raise GraphEditInvalid("Saved graph is invalid")
        contract = copy.deepcopy(decode_graph_json(target["graph_contract"]))
        old_version = graph.get("version")
        graph["version"] = str(uuid.uuid4())
        if contract is not None:
            if (
                not isinstance(contract, dict)
                or contract.get("graph_version") != old_version
            ):
                raise GraphEditInvalid("Saved graph contract is invalid")
            contract["graph_version"] = graph["version"]
        conn.execute(
            _adapt_query("""
            UPDATE chat_threads SET graph_data = ?, graph_contract = ?, active_graph_revision_id = ?,
                updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
        """),
            (
                json.dumps(graph, ensure_ascii=False),
                json.dumps(contract, ensure_ascii=False) if contract else None,
                revision_id,
                thread_id,
                user_id,
            ),
        )
        return {"revision_id": revision_id, "graph_data": graph}
