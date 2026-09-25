import json
import logging
import uuid

from adapters.database_adapter import (
    _adapt_query,
    _connect,
    execute,
    fetchall,
    fetchone,
)
from config import settings
from graph.content_edit import (
    GraphContentEditRequest,
    GraphEditConflict,
    GraphEditInvalid,
    GraphEditNotFound,
    GraphEditTooLarge,
    apply_graph_content_edit,
)

from storage.errors import ThreadMessageLimitExceeded

logger = logging.getLogger(__name__)

# Draft IDs stay addressable for open tabs and in-flight turns, but are not history.
# SQL interpolation below inserts only this fixed predicate; user values stay bound.
_HAS_CONTENT_SQL = """(graph_data IS NOT NULL OR EXISTS (
    SELECT 1 FROM chat_messages
    WHERE chat_messages.thread_id = chat_threads.id
      AND chat_messages.user_id = chat_threads.user_id
))"""


def count_threads(user_id: str) -> int:
    """Count saved conversations, excluding empty drafts."""
    row = fetchone(
        "SELECT COUNT(*) AS n FROM chat_threads WHERE user_id = ? AND {}".format(  # nosec B608
            _HAS_CONTENT_SQL
        ),
        (user_id,),
    )
    return row["n"] if row else 0


def get_oldest_thread_id(user_id: str) -> str | None:
    """Return the id of the user's least-recently-seen thread."""
    row = fetchone(
        """
        SELECT id FROM chat_threads
        WHERE user_id = ? AND {}
        ORDER BY last_seen_at ASC
        LIMIT 1
        """.format(_HAS_CONTENT_SQL),  # nosec B608
        (user_id,),
    )
    return row["id"] if row else None


def delete_thread(user_id: str, thread_id: str) -> None:
    """Atomically delete a thread and its messages on either database."""
    with _connect() as conn:
        conn.execute(
            _adapt_query(
                "DELETE FROM chat_messages WHERE thread_id = ? AND user_id = ?"
            ),
            (thread_id, user_id),
        )
        conn.execute(
            _adapt_query("DELETE FROM chat_threads WHERE id = ? AND user_id = ?"),
            (thread_id, user_id),
        )


def create_thread(user_id: str, title: str = "New chat") -> dict:
    with _connect() as conn:
        thread_id = str(uuid.uuid4())
        conn.execute(
            _adapt_query(
                """
                INSERT INTO chat_threads (id, user_id, title)
                VALUES (?, ?, ?)
                """
            ),
            (thread_id, user_id, title),
        )
        row = conn.execute(
            _adapt_query(
                """
                SELECT id, user_id, title, graph_data, created_at, updated_at, last_seen_at
                FROM chat_threads
                WHERE id = ? AND user_id = ?
                """
            ),
            (thread_id, user_id),
        ).fetchone()
        thread = dict(row) if row else None

    if thread and thread.get("graph_data"):
        try:
            thread["graph_data"] = (
                json.loads(thread["graph_data"])
                if isinstance(thread["graph_data"], str)
                else thread["graph_data"]
            )
        except Exception:
            thread["graph_data"] = None
    return thread


def get_thread(user_id: str, thread_id: str) -> dict | None:
    row = fetchone(
        """
        SELECT id, user_id, title, graph_data, created_at, updated_at, last_seen_at
        FROM chat_threads
        WHERE id = ? AND user_id = ?
        """,
        (thread_id, user_id),
    )
    if row and row.get("graph_data"):
        try:
            row["graph_data"] = (
                json.loads(row["graph_data"])
                if isinstance(row["graph_data"], str)
                else row["graph_data"]
            )
        except Exception:
            row["graph_data"] = None
    return row


def list_threads(user_id: str, limit: int = 20) -> list[dict]:
    rows = fetchall(
        """
        SELECT id, title, created_at, updated_at, last_seen_at
        FROM chat_threads
        WHERE user_id = ? AND {}
        ORDER BY last_seen_at DESC
        LIMIT ?
        """.format(_HAS_CONTENT_SQL),  # nosec B608
        (user_id, limit),
    )
    return rows


def get_latest_thread(user_id: str) -> dict | None:
    row = fetchone(
        """
        SELECT id, user_id, title, graph_data, created_at, updated_at, last_seen_at
        FROM chat_threads
        WHERE user_id = ? AND {}
        ORDER BY last_seen_at DESC
        LIMIT 1
        """.format(_HAS_CONTENT_SQL),  # nosec B608
        (user_id,),
    )
    if row and row.get("graph_data"):
        try:
            row["graph_data"] = (
                json.loads(row["graph_data"])
                if isinstance(row["graph_data"], str)
                else row["graph_data"]
            )
        except Exception:
            row["graph_data"] = None
    return row


def touch_thread(user_id: str, thread_id: str, title: str | None = None) -> None:
    if title:
        execute(
            """
            UPDATE chat_threads
            SET title = ?, updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (title, thread_id, user_id),
        )
        return
    execute(
        """
        UPDATE chat_threads
        SET updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (thread_id, user_id),
    )


def get_graph(user_id: str, thread_id: str) -> dict | None:
    row = fetchone(
        "SELECT graph_data FROM chat_threads WHERE id = ? AND user_id = ?",
        (thread_id, user_id),
    )
    if row and row.get("graph_data"):
        try:
            return (
                json.loads(row["graph_data"])
                if isinstance(row["graph_data"], str)
                else row["graph_data"]
            )
        except Exception:
            return None
    return None


def get_graph_artifact(
    user_id: str,
    thread_id: str,
) -> tuple[dict | None, dict | None]:
    """Return the persisted graph and server-only contract for workflow recovery.

    Thread API reads deliberately select only ``graph_data``. Keep callers that
    need the contract on this storage boundary rather than adding it to thread
    response objects.
    """
    row = fetchone(
        """
        SELECT graph_data, graph_contract
        FROM chat_threads
        WHERE id = ? AND user_id = ?
        """,
        (thread_id, user_id),
    )
    if row is None:
        return None, None

    def deserialize(value: object) -> dict | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except (TypeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    graph_data = deserialize(row.get("graph_data"))
    graph_contract = deserialize(row.get("graph_contract"))
    if graph_contract is None:
        return graph_data, None

    graph_version = graph_data.get("version") if graph_data is not None else None
    contract_version = graph_contract.get("graph_version")
    if (
        not isinstance(contract_version, str)
        or not contract_version.strip()
        or contract_version != graph_version
    ):
        logger.warning(
            "thread_store: ignoring graph contract with invalid graph_version for thread %s",
            thread_id,
        )
        return graph_data, None

    return graph_data, graph_contract


def save_graph(user_id: str, thread_id: str, graph_data: dict) -> bool:
    """Persist only the submitted layout state on the current server graph.

    Returns True if saved, False if the serialised size exceeds
    settings.max_graph_data_bytes. A thread without a current graph remains
    unchanged.
    """
    with _connect() as conn:
        if not settings.use_postgres:
            conn.execute("BEGIN IMMEDIATE")
        thread_query = (
            "SELECT graph_data FROM chat_threads WHERE id = ? AND user_id = ? FOR UPDATE"
            if settings.use_postgres
            else "SELECT graph_data FROM chat_threads WHERE id = ? AND user_id = ?"
        )
        row = conn.execute(
            _adapt_query(thread_query),
            (thread_id, user_id),
        ).fetchone()
        if row is None or row["graph_data"] is None or "view_state" not in graph_data:
            return True

        stored_graph = row["graph_data"]
        try:
            current_graph = (
                json.loads(stored_graph)
                if isinstance(stored_graph, str)
                else stored_graph
            )
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "thread_store: current graph_data is invalid for thread %s; skipping layout save",
                thread_id,
            )
            return True
        if not isinstance(current_graph, dict):
            logger.warning(
                "thread_store: current graph_data is not an object for thread %s; skipping layout save",
                thread_id,
            )
            return True

        updated_graph = {**current_graph, "view_state": graph_data["view_state"]}
        serialized = json.dumps(updated_graph, ensure_ascii=False)
        byte_size = len(serialized.encode("utf-8"))
        if byte_size > settings.max_graph_data_bytes:
            logger.warning(
                "thread_store: graph_data too large (%d bytes > %d limit) for thread %s; skipping save",
                byte_size,
                settings.max_graph_data_bytes,
                thread_id,
            )
            return False

        submitted_version = graph_data.get("version")
        current_version = current_graph.get("version")
        if (
            not isinstance(submitted_version, str)
            or not isinstance(current_version, str)
            or submitted_version != current_version
        ):
            logger.info(
                "thread_store: stale graph layout ignored for thread %s",
                thread_id,
            )
            return True
        conn.execute(
            _adapt_query(
                """
                UPDATE chat_threads
                SET graph_data = ?, updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """
            ),
            (serialized, thread_id, user_id),
        )
    return True


def _edited_graph_contract(
    stored_contract: object, *, old_version: object, new_version: str
) -> dict | None:
    if stored_contract is None:
        return None
    try:
        contract = (
            json.loads(stored_contract)
            if isinstance(stored_contract, str)
            else stored_contract
        )
    except (TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(contract, dict)
        or not isinstance(old_version, str)
        or not old_version.strip()
        or contract.get("graph_version") != old_version
    ):
        return None

    # User edits retain design context, never a review decision for old content.
    updated: dict = {
        "graph_version": new_version,
        "source": "user_edit",
        "stage": "edited",
    }
    maturity = contract.get("maturity")
    if isinstance(maturity, str) and maturity in {"prototype", "production"}:
        updated["maturity"] = maturity
    capabilities = contract.get("capabilities")
    capability_names = {"external_effects", "retrieval_or_reuse", "learning_or_release"}
    if (
        isinstance(capabilities, dict)
        and set(capabilities) <= capability_names
        and all(isinstance(value, bool) for value in capabilities.values())
    ):
        updated["capabilities"] = capabilities
    objective = contract.get("objective")
    if isinstance(objective, str) and objective.strip():
        updated["objective"] = objective
    return updated


def edit_graph_content(
    user_id: str, thread_id: str, request: GraphContentEditRequest
) -> dict:
    """Edit an owned graph under a version check and one database transaction."""
    with _connect() as conn:
        if not settings.use_postgres:
            conn.execute("BEGIN IMMEDIATE")
        thread_query = (
            "SELECT graph_data, graph_contract FROM chat_threads "
            "WHERE id = ? AND user_id = ? FOR UPDATE"
            if settings.use_postgres
            else "SELECT graph_data, graph_contract FROM chat_threads "
            "WHERE id = ? AND user_id = ?"
        )
        row = conn.execute(_adapt_query(thread_query), (thread_id, user_id)).fetchone()
        if row is None or row["graph_data"] is None:
            raise GraphEditNotFound("Thread graph not found")

        try:
            graph = (
                json.loads(row["graph_data"])
                if isinstance(row["graph_data"], str)
                else row["graph_data"]
            )
        except (TypeError, json.JSONDecodeError) as exc:
            raise GraphEditInvalid("saved graph is invalid") from exc
        if not isinstance(graph, dict):
            raise GraphEditInvalid("saved graph is invalid")
        old_version = graph.get("version")
        if old_version != request.expected_version:
            raise GraphEditConflict("Graph changed. Reload it before editing.")

        edited, changed = apply_graph_content_edit(graph, request)
        if not changed:
            return graph

        new_version = str(uuid.uuid4())
        edited["version"] = new_version
        serialized = json.dumps(edited, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > settings.max_graph_data_bytes:
            raise GraphEditTooLarge("Graph data too large")
        contract = _edited_graph_contract(
            row["graph_contract"],
            old_version=old_version,
            new_version=new_version,
        )
        conn.execute(
            _adapt_query(
                """
                UPDATE chat_threads
                SET graph_data = ?, graph_contract = ?,
                    updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """
            ),
            (
                serialized,
                json.dumps(contract, ensure_ascii=False)
                if contract is not None
                else None,
                thread_id,
                user_id,
            ),
        )
    return edited


def persist_turn(
    user_id: str,
    thread_id: str,
    *,
    title: str,
    user_content: str,
    assistant_content: str,
    graph_data: dict | None,
    graph_contract: dict | None = None,
    client_request_id: str | None = None,
) -> bool:
    """Atomically and idempotently persist a completed turn and optional graph.

    Returns False only when the graph exceeds its size limit; the messages and
    thread metadata are still committed together. Reusing a non-null
    ``client_request_id`` returns without duplicating an already completed turn.
    Any database error rolls the complete turn back, avoiding partial history.
    """
    serialized_graph: str | None = None
    serialized_contract: str | None = None
    graph_saved = True
    if graph_data is not None:
        candidate = json.dumps(graph_data, ensure_ascii=False)
        if len(candidate.encode("utf-8")) > settings.max_graph_data_bytes:
            graph_saved = False
        else:
            serialized_graph = candidate

    if graph_contract is not None:
        if not isinstance(graph_data, dict):
            raise ValueError("graph_contract requires graph_data")
        if not isinstance(graph_contract, dict):
            raise ValueError("graph_contract must be an object")
        graph_version = graph_data.get("version")
        contract_version = graph_contract.get("graph_version")
        if (
            not isinstance(graph_version, str)
            or not graph_version.strip()
            or contract_version != graph_version
        ):
            raise ValueError(
                "graph_contract.graph_version must match graph_data.version"
            )
        serialized_contract = json.dumps(graph_contract, ensure_ascii=False)

    with _connect() as conn:
        if settings.use_postgres:
            # Lock the history owner before thread locks to serialize retention
            # across concurrent completed turns for this user.
            conn.execute(
                _adapt_query("SELECT id FROM profiles WHERE id = ? FOR UPDATE"),
                (user_id,),
            ).fetchone()
        else:
            # Acquire SQLite's write lock before checking the idempotency key.
            conn.execute("BEGIN IMMEDIATE")
        thread_query = (
            "SELECT id FROM chat_threads WHERE id = ? AND user_id = ? FOR UPDATE"
            if settings.use_postgres
            else "SELECT id FROM chat_threads WHERE id = ? AND user_id = ?"
        )
        thread = conn.execute(
            _adapt_query(thread_query),
            (thread_id, user_id),
        ).fetchone()
        if thread is None:
            raise ValueError("Thread no longer exists")

        if client_request_id is not None:
            prior_rows = conn.execute(
                _adapt_query(
                    """
                    SELECT role FROM chat_messages
                    WHERE thread_id = ? AND user_id = ? AND client_request_id = ?
                    """
                ),
                (thread_id, user_id, client_request_id),
            ).fetchall()
            if prior_rows:
                prior_roles = {row["role"] for row in prior_rows}
                if prior_roles != {"user", "assistant"}:
                    raise RuntimeError(
                        "Stored turn is incomplete; refusing an ambiguous retry"
                    )
                return True

        row = conn.execute(
            _adapt_query(
                "SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ? AND user_id = ?"
            ),
            (thread_id, user_id),
        ).fetchone()
        message_count = row["n"] if row else 0
        if message_count + 2 > settings.max_messages_per_thread:
            raise ThreadMessageLimitExceeded(
                "Thread message limit reached. Start a new chat to continue."
            )

        for role, content in (("user", user_content), ("assistant", assistant_content)):
            conn.execute(
                _adapt_query(
                    """
                    INSERT INTO chat_messages (
                        id, thread_id, user_id, role, content, client_request_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    str(uuid.uuid4()),
                    thread_id,
                    user_id,
                    role,
                    content,
                    client_request_id,
                ),
            )

        if serialized_graph is not None:
            conn.execute(
                _adapt_query(
                    """
                    UPDATE chat_threads
                    SET title = ?, graph_data = ?, graph_contract = ?, updated_at = CURRENT_TIMESTAMP,
                        last_seen_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """
                ),
                (title, serialized_graph, serialized_contract, thread_id, user_id),
            )
        else:
            conn.execute(
                _adapt_query(
                    """
                    UPDATE chat_threads
                    SET title = ?, updated_at = CURRENT_TIMESTAMP, last_seen_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """
                ),
                (title, thread_id, user_id),
            )

        # Opening a blank composer must never evict a conversation. Apply the
        # existing history cap only after a completed turn is safely stored.
        prior_threads = conn.execute(
            _adapt_query(
                """
                SELECT id FROM chat_threads
                WHERE user_id = ? AND id <> ? AND {}
                ORDER BY last_seen_at DESC, created_at DESC, id DESC
                """.format(_HAS_CONTENT_SQL)  # nosec B608
            ),
            (user_id, thread_id),
        ).fetchall()
        for prior in prior_threads[settings.max_threads_per_user - 1 :]:
            conn.execute(
                _adapt_query(
                    "DELETE FROM chat_messages WHERE thread_id = ? AND user_id = ?"
                ),
                (prior["id"], user_id),
            )
            conn.execute(
                _adapt_query("DELETE FROM chat_threads WHERE id = ? AND user_id = ?"),
                (prior["id"], user_id),
            )

    return graph_saved


def get_completed_turn(
    user_id: str,
    thread_id: str,
    client_request_id: str | None,
) -> dict[str, str] | None:
    """Return the canonical stored response for a completed idempotent turn.

    A partial turn is never replayed because its outcome is ambiguous. The
    completed-turn transaction should prevent that state, but treating it as an
    error keeps corruption visible instead of silently inventing a response.
    """
    if client_request_id is None:
        return None

    rows = fetchall(
        """
        SELECT role, content
        FROM chat_messages
        WHERE user_id = ? AND thread_id = ? AND client_request_id = ?
        """,
        (user_id, thread_id, client_request_id),
    )
    if not rows:
        return None

    content_by_role = {row["role"]: row["content"] for row in rows}
    if set(content_by_role) != {"user", "assistant"}:
        raise RuntimeError("Stored turn is incomplete; refusing an ambiguous retry")
    return {
        "user_content": content_by_role["user"],
        "assistant_content": content_by_role["assistant"],
    }
