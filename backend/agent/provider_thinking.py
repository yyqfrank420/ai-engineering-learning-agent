"""Ephemeral, bounded forwarding of provider-supplied thinking deltas."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Literal
from uuid import uuid4

ThinkingPhase = Literal["components", "connections", "review", "explain"]
logger = logging.getLogger(__name__)


class ThinkingFeed:
    def __init__(
        self,
        send: Callable[[dict], Awaitable[None]] | None,
        phase: ThinkingPhase | None,
    ) -> None:
        self._send = send if phase is not None else None
        self._phase = phase
        self._operation_id = str(uuid4())
        self._pending = ""
        self._count = 0
        self._started = False

    async def __aenter__(self) -> "ThinkingFeed":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        try:
            await self.flush()
        except asyncio.CancelledError:
            if exc_type is None:
                raise
        return False

    async def add(self, content: str) -> None:
        if self._send is None or not isinstance(content, str):
            return
        fragment = content[: max(0, 8000 - self._count)]
        self._count += len(fragment)
        self._pending += fragment
        await self.flush()

    async def flush(self) -> None:
        if self._send is None or not self._pending:
            return
        content, self._pending = self._pending, ""
        event = {
            "type": "thinking_delta", "operation_id": self._operation_id,
            "phase": self._phase, "content": content,
            **({"reset": True} if not self._started else {}),
        }
        self._started = True
        try:
            await self._send(event)
        except Exception as exc:
            # Optional feedback must not replace the provider's result or error.
            logger.info("Provider thinking delivery failed (%s)", type(exc).__name__)
            self._send = None

    async def restart(self) -> None:
        await self.flush()
        self._operation_id = str(uuid4())
        self._pending = ""
        self._count = 0
        self._started = False
