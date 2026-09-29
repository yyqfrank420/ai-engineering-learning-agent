from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

from adapters.database_adapter import _adapt_query, _connect
from config import settings


@dataclass(frozen=True)
class RateLimitDimension:
    scope: str
    identifier: str
    event_type: str
    limit: int
    window_s: int | None


def _key_hash(dimension: RateLimitDimension) -> str:
    # Cloud Run requires the Turnstile secret. Local/test environments fall
    # back to the JWT secret or a deliberately non-production-only key.
    secret = (
        settings.turnstile_secret_key
        or settings.supabase_jwt_secret
        or "local-development-only"
    )
    return hmac.new(
        secret.encode("utf-8"),
        f"{dimension.scope}:{dimension.identifier}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def reserve_rate_limit(
    dimensions: tuple[RateLimitDimension, ...],
    *,
    bypass_limits: bool = False,
    created_at_epoch: float | None = None,
) -> tuple[str, ...] | None:
    """Atomically reserve one attempt across every supplied rate-limit dimension."""
    if not dimensions:
        raise ValueError("At least one rate-limit dimension is required")
    if any(dimension.limit < 0 for dimension in dimensions):
        raise ValueError("Rate-limit dimensions require non-negative limits")
    for dimension in dimensions:
        if dimension.window_s is None:
            if (dimension.scope, dimension.event_type) != (
                "evaluation_run",
                "llm_provider_attempt",
            ):
                raise ValueError(
                    "Lifetime quota is reserved for evaluation provider attempts"
                )
            if bypass_limits:
                raise ValueError("Lifetime evaluation quota cannot be bypassed")
        elif dimension.window_s <= 0:
            raise ValueError("Rate-limit windows must be positive")

    now = created_at_epoch if created_at_epoch is not None else time.time()
    event_ids = tuple(str(uuid.uuid4()) for _ in dimensions)
    hashed_dimensions = tuple(
        (dimension, _key_hash(dimension)) for dimension in dimensions
    )
    lock_keys = sorted(
        {
            f"rate-limit:{dimension.event_type}:{key_hash}"
            for dimension, key_hash in hashed_dimensions
        }
    )

    with _connect() as conn:
        if settings.use_postgres:
            for lock_key in lock_keys:
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
        else:
            conn.execute("BEGIN IMMEDIATE")

        # Keep historical provider reservations so an unrelated rate-limit call
        # cannot erase evidence or reopen a cumulative evaluation budget.
        conn.execute(
            _adapt_query(
                "DELETE FROM rate_limit_events "
                "WHERE expires_at_epoch <= ? AND event_type != 'llm_provider_attempt'"
            ),
            (now,),
        )

        if not bypass_limits:
            for dimension, key_hash in hashed_dimensions:
                row = conn.execute(
                    _adapt_query(
                        """
                        SELECT COUNT(*) AS n
                        FROM rate_limit_events
                        WHERE key_hash = ? AND event_type = ?
                          AND (? = 1 OR expires_at_epoch > ?)
                        """
                    ),
                    (
                        key_hash,
                        dimension.event_type,
                        int(dimension.window_s is None),
                        now,
                    ),
                ).fetchone()
                if (row["n"] if row else 0) >= dimension.limit:
                    return None

        for event_id, (dimension, key_hash) in zip(
            event_ids, hashed_dimensions, strict=True
        ):
            conn.execute(
                _adapt_query(
                    """
                    INSERT INTO rate_limit_events (
                        id, key_hash, event_type, created_at_epoch, expires_at_epoch
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """
                ),
                (
                    event_id,
                    key_hash,
                    dimension.event_type,
                    now,
                    float("inf")
                    if dimension.window_s is None
                    else now + dimension.window_s,
                ),
            )

    return event_ids


def release_rate_limit(event_ids: tuple[str, ...]) -> None:
    """Release reservations that should not count against their limit."""
    if not event_ids:
        return
    event_ids = tuple(dict.fromkeys(event_ids))
    batches = [
        event_ids[offset : offset + 500] for offset in range(0, len(event_ids), 500)
    ]
    with _connect() as conn:
        # Bandit cannot infer that placeholders are constants; IDs remain bound values.
        for batch in batches:
            placeholders = ", ".join("?" for _ in batch)
            provider_row = conn.execute(
                _adapt_query(
                    f"SELECT 1 FROM rate_limit_events WHERE id IN ({placeholders}) AND event_type = 'llm_provider_attempt' LIMIT 1"  # nosec
                ),
                batch,
            ).fetchone()
            if provider_row is not None:
                raise ValueError("Provider-attempt reservations cannot be released")
        for batch in batches:
            placeholders = ", ".join("?" for _ in batch)
            conn.execute(
                _adapt_query(
                    f"DELETE FROM rate_limit_events WHERE id IN ({placeholders}) AND event_type != 'llm_provider_attempt'"  # nosec
                ),
                batch,
            )
