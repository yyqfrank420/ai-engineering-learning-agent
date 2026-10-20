import time
import uuid

from adapters.database_adapter import _adapt_query, _connect, execute, fetchall, fetchone
from config import settings


def record_request_event(user_id: str, event_type: str, *, created_at_epoch: float | None = None) -> None:
    execute(
        """
        INSERT INTO request_events (id, user_id, event_type, created_at_epoch)
        VALUES (?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), user_id, event_type, created_at_epoch or time.time()),
    )


def get_recent_request_events(user_id: str, event_type: str, *, since_epoch: float) -> list[dict]:
    return fetchall(
        """
        SELECT id, user_id, event_type, created_at_epoch
        FROM request_events
        WHERE user_id = ? AND event_type = ? AND created_at_epoch >= ?
        ORDER BY created_at_epoch DESC
        """,
        (user_id, event_type, since_epoch),
    )


def prune_request_events(*, older_than_epoch: float) -> None:
    execute(
        "DELETE FROM request_events WHERE created_at_epoch < ?",
        (older_than_epoch,),
    )


def create_search_tool_request(
    request_id: str,
    user_id: str,
    thread_id: str,
    *,
    expires_at_epoch: float,
) -> None:
    execute(
        """
        INSERT INTO search_tool_requests (
            request_id, user_id, thread_id, requested, created_at_epoch, expires_at_epoch
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (request_id, user_id, thread_id, False, time.time(), expires_at_epoch),
    )


def mark_search_tool_requested(request_id: str, user_id: str, thread_id: str) -> bool:
    row = fetchone(
        """
        SELECT request_id, expires_at_epoch
        FROM search_tool_requests
        WHERE request_id = ? AND user_id = ? AND thread_id = ?
        """,
        (request_id, user_id, thread_id),
    )
    if row is None or row["expires_at_epoch"] < time.time():
        return False

    execute(
        """
        UPDATE search_tool_requests
        SET requested = ?
        WHERE request_id = ? AND user_id = ? AND thread_id = ?
        """,
        (True, request_id, user_id, thread_id),
    )
    return True


def is_search_tool_requested(request_id: str, user_id: str, thread_id: str) -> bool:
    row = fetchone(
        """
        SELECT requested, expires_at_epoch
        FROM search_tool_requests
        WHERE request_id = ? AND user_id = ? AND thread_id = ?
        """,
        (request_id, user_id, thread_id),
    )
    if row is None or row["expires_at_epoch"] < time.time():
        return False
    return bool(row["requested"])


def delete_search_tool_request(request_id: str) -> None:
    execute(
        "DELETE FROM search_tool_requests WHERE request_id = ?",
        (request_id,),
    )


def prune_search_tool_requests(*, older_than_epoch: float) -> None:
    execute(
        "DELETE FROM search_tool_requests WHERE expires_at_epoch < ?",
        (older_than_epoch,),
    )


def register_active_stream(
    user_id: str,
    stream_type: str,
    *,
    ttl_s: float,
    scope_id: str | None = None,
) -> str:
    """Record nonexclusive activity so retention preserves in-flight threads."""
    now = time.time()
    stream_id = str(uuid.uuid4())
    effective_stream_type = f"{stream_type}:scope:{scope_id}" if scope_id else stream_type
    with _connect() as conn:
        # Retention takes this same brief owner lock while selecting/deleting
        # idle drafts. Registration must be atomic with that decision.
        # NO KEY UPDATE keeps message foreign-key reads compatible.
        if settings.use_postgres:
            profile = conn.execute(
                _adapt_query("SELECT id FROM profiles WHERE id = ? FOR NO KEY UPDATE"),
                (user_id,),
            ).fetchone()
            if profile is None:
                raise ValueError("Profile does not exist")
        else:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            _adapt_query(
                """
                INSERT INTO active_streams (id, user_id, stream_type, created_at_epoch, expires_at_epoch)
                VALUES (?, ?, ?, ?, ?)
                """
            ),
            (stream_id, user_id, effective_stream_type, now, now + ttl_s),
        )
    return stream_id


def release_active_stream(stream_id: str | None) -> None:
    if not stream_id:
        return
    execute("DELETE FROM active_streams WHERE id = ?", (stream_id,))


def prune_active_streams(*, older_than_epoch: float) -> None:
    execute(
        "DELETE FROM active_streams WHERE expires_at_epoch < ?",
        (older_than_epoch,),
    )
