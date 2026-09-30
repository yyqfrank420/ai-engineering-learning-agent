import json
import logging
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.database_adapter import _adapt_query, _connect, fetchall, fetchone
from config import settings
from storage.errors import ThreadMessageLimitExceeded


logger = logging.getLogger(__name__)


class RetryRequest(BaseModel):
    """Original, bounded options for a confirmed failed diagram attempt."""

    content: str = Field(min_length=1)
    complexity: Literal["auto", "low", "prototype", "production"]
    graph_mode: Literal["on", "off"]
    diagram_requested: bool
    research_enabled: bool
    graph_action: Literal["extend", "new", "answer"] | None
    expected_graph_version: str | None = Field(
        default=None, min_length=1, max_length=128
    )

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("content")
    @classmethod
    def bound_content(cls, value: str) -> str:
        if len(value.encode("utf-8")) > settings.max_message_bytes:
            raise ValueError("Retry content exceeds the message byte limit")
        return value


def decode_retry_request(value: object) -> dict | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return RetryRequest.model_validate(parsed).model_dump()
    except (ValueError, TypeError) as exc:
        # Optional corrupt retry data must not hide the canonical conversation.
        logger.warning("Ignoring invalid retry metadata: %s", type(exc).__name__)
        return None


def count_messages(user_id: str, thread_id: str) -> int:
    """Return the number of messages in this thread."""
    row = fetchone(
        "SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ? AND user_id = ?",
        (thread_id, user_id),
    )
    return row["n"] if row else 0


def append(user_id: str, thread_id: str, role: str, content: str) -> None:
    with _connect() as conn:
        if not settings.use_postgres:
            conn.execute("BEGIN IMMEDIATE")
        thread_query = "SELECT id FROM chat_threads WHERE id = ? AND user_id = ?"
        if settings.use_postgres:
            thread_query += " FOR UPDATE"
        thread = conn.execute(
            _adapt_query(thread_query), (thread_id, user_id)
        ).fetchone()
        if thread is None:
            raise ValueError("Thread no longer exists")
        count = conn.execute(
            _adapt_query(
                "SELECT COUNT(*) AS n FROM chat_messages WHERE thread_id = ? AND user_id = ?"
            ),
            (thread_id, user_id),
        ).fetchone()["n"]
        if count >= settings.max_messages_per_thread:
            raise ThreadMessageLimitExceeded(
                "Thread message limit reached. Start a new chat to continue."
            )
        conn.execute(
            _adapt_query(
                """
                INSERT INTO chat_messages (id, thread_id, user_id, role, content)
                VALUES (?, ?, ?, ?, ?)
                """
            ),
            (str(uuid.uuid4()), thread_id, user_id, role, content),
        )


def get_history(user_id: str, thread_id: str, limit: int = 20) -> list[dict]:
    rows = fetchall(
        """
        SELECT role, content
        FROM chat_messages
        WHERE thread_id = ? AND user_id = ?
        ORDER BY message_sequence DESC
        LIMIT ?
        """,
        (thread_id, user_id, limit),
    )
    return list(reversed(rows))


def get_messages(user_id: str, thread_id: str, limit: int = 100) -> list[dict]:
    rows = fetchall(
        """
        SELECT id, role, content, created_at, graph_revision_id, client_request_id, retry_request
        FROM chat_messages
        WHERE thread_id = ? AND user_id = ?
        ORDER BY message_sequence ASC
        LIMIT ?
        """,
        (thread_id, user_id, limit),
    )
    return [
        {**row, "retry_request": decode_retry_request(row["retry_request"])}
        for row in rows
    ]
