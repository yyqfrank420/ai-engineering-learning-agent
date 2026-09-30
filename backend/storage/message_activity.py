"""Bounded public activity retained with the canonical assistant message."""

import json
import logging
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


logger = logging.getLogger(__name__)
MAX_ACTIVITY_BYTES = 32_768
MAX_ACTIVITY_STEPS = 48
MAX_ACTIVITY_DURATION_MS = 86_400_000
WorkflowPhase = Literal[
    "context", "book", "web", "components", "connections", "synthesis",
    "evidence", "architect", "challenger", "integrate", "render", "review",
    "revise", "explain",
]


class ActivityStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sequence: int = Field(ge=0)
    kind: Literal["update", "tool"]
    phase: WorkflowPhase
    status: Literal["active", "complete", "retry", "rejected", "degraded"]
    text: str = Field(min_length=1, max_length=400)
    elapsed_ms: int = Field(ge=0, le=MAX_ACTIVITY_DURATION_MS)


class MessageActivity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    duration_ms: int = Field(ge=0, le=MAX_ACTIVITY_DURATION_MS)
    steps: list[ActivityStep] = Field(max_length=MAX_ACTIVITY_STEPS)

    @model_validator(mode="after")
    def validate_order_and_size(self) -> Self:
        for previous, current in zip(self.steps, self.steps[1:]):
            if current.sequence <= previous.sequence:
                raise ValueError("Activity sequences must be strictly increasing")
            if current.elapsed_ms < previous.elapsed_ms:
                raise ValueError("Activity elapsed times must be nondecreasing")
        if self.steps and self.steps[-1].elapsed_ms > self.duration_ms:
            raise ValueError("Activity steps cannot exceed completed duration")
        if len(self.model_dump_json().encode("utf-8")) > MAX_ACTIVITY_BYTES:
            raise ValueError("Activity exceeds the serialized byte limit")
        return self


def decode_message_activity(value: object) -> dict | None:
    if value is None:
        return None
    try:
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_ACTIVITY_BYTES:
            raise ValueError("Activity exceeds the serialized byte limit")
        parsed = json.loads(value) if isinstance(value, str) else value
        return MessageActivity.model_validate(parsed).model_dump()
    except (ValueError, TypeError) as exc:
        # Optional corrupt activity must not hide the canonical conversation.
        logger.warning("Ignoring invalid message activity: %s", type(exc).__name__)
        return None
