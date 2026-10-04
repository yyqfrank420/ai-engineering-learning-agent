"""Bounded public activity derived from workflow events, with transport-owned time."""

import json
import re

from storage.message_activity import (
    ActivityStep,
    MessageActivity,
    MAX_ACTIVITY_BYTES,
    MAX_ACTIVITY_DURATION_MS,
    MAX_ACTIVITY_STEPS,
)

_STATUSES = {"active", "complete", "retry", "rejected", "degraded"}
# Twenty digits cover real collection lengths and leave room for complete public sentences.
_MAX_DRAFT_COUNT = 10**20 - 1
_STAGE_TEXT = {
    "context": "Preparing diagram context",
    "evidence": "Collecting design evidence",
    "architect": "Analyzing architecture",
    "challenger": "Reviewing architecture risks",
    "components": "Generating diagram components",
    "connections": "Generating diagram connections",
    "integrate": "Integrating review findings",
    "revise": "Revising the diagram",
    "explain": "Generating the explanation",
    "synthesis": "Generating the explanation",
}
_TOOL_TEXT = {
    "book": ("Retrieving book passages", "Book retrieval finished"),
    "web": ("Searching the web", "Web search finished"),
    "render": ("Checking the layout", "Layout checked"),
    "review": ("Checking the draft", "Draft checked"),
}
# Startup and routing are transport notifications, not evidence of workflow work.
_CONTEXT_STATUS_TEXT = {
    "Steering received \u2014 rebuilding the answer around your correction\u2026": (
        "Updating request context"
    ),
}
_INTERNAL_TEXT = re.compile(
    r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b|\b(?:capabilit(?:y|ies)|slot)[.:\[]|[{}]", re.I
)


def _public_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if _INTERNAL_TEXT.search(text):
        return ""
    return text[:limit]


def _draft_text(phase: str, summary: object) -> str:
    if not isinstance(summary, dict) or set(summary) - {
        "title",
        "component_count",
        "connection_count",
        "labels",
    }:
        return ""
    nodes, edges = summary.get("component_count"), summary.get("connection_count")
    if any(
        type(count) is not int or not 0 <= count <= _MAX_DRAFT_COUNT
        for count in (nodes, edges)
    ):
        return ""
    if nodes == 0 and edges > 0:
        return ""
    labels = summary.get("labels", [])
    if (
        not isinstance(labels, list)
        or len(labels) > min(2, nodes)
        or not all(isinstance(label, str) for label in labels)
    ):
        return ""
    title = _public_text(summary.get("title"), 80)
    public_labels = list(
        dict.fromkeys(text for label in labels if (text := _public_text(label, 48)))
    )
    components = (
        f"{nodes} component{'s' if nodes != 1 else ''}" if nodes else "no components"
    )
    if phase == "components":
        names = f", including {' and '.join(public_labels)}" if public_labels else ""
        subject = f"The draft for {title}" if title else "The draft"
        return f"{subject} has {components}{names}."
    connections = (
        f"{edges} connection{'s' if edges != 1 else ''}" if edges else "no connections"
    )
    return f"The draft now has {connections} across {components}."


class ActivityRecorder:
    def __init__(self) -> None:
        self._steps: list[dict] = []
        self._next_sequence = 0
        self._last_elapsed_ms = 0

    def record(self, event: dict, elapsed_ms: int) -> dict | None:
        event_type = event.get("type")
        if not isinstance(event_type, str):
            return None
        if event_type == "worker_status":
            worker, worker_status = event.get("worker"), event.get("status")
            if (
                worker != "orchestrator"
                or not isinstance(worker_status, str)
                or worker_status not in _CONTEXT_STATUS_TEXT
            ):
                return None
            phase, status = "context", "active"
            context_text = _CONTEXT_STATUS_TEXT[worker_status]
        elif event_type == "workflow_progress":
            phase, status = event.get("phase"), event.get("status")
            context_text = None
        else:
            return None
        if (
            not isinstance(phase, str)
            or not isinstance(status, str)
            or status not in _STATUSES
            or phase not in _STAGE_TEXT.keys() | _TOOL_TEXT.keys()
        ):
            return None
        kind = "tool" if phase in _TOOL_TEXT else "update"
        text = (
            _TOOL_TEXT[phase][1 if status == "complete" else 0]
            if kind == "tool"
            else context_text or _STAGE_TEXT[phase]
        )
        if status == "retry":
            if kind == "update":
                text = _STAGE_TEXT["revise"]
            elif phase in {"book", "web"}:
                text = "Retrying the search"
            else:
                text = "Checking the draft again"
        elif status in {"rejected", "degraded"}:
            if kind == "update":
                if phase in {"components", "connections"}:
                    text = (
                        "Diagram draft could not be completed"
                        if status == "rejected"
                        else "Clarification required"
                    )
                else:
                    text = (
                        "Diagram check could not be completed"
                        if status == "rejected"
                        else "This step returned limited results."
                    )
            elif phase in {"book", "web"}:
                text = (
                    "Search did not complete"
                    if status == "rejected"
                    else "Search coverage is limited"
                )
            else:
                text = (
                    "Layout check not completed"
                    if phase == "render"
                    else "Review not completed"
                )
        elif status == "complete" and kind == "update":
            if phase in {"architect", "challenger"}:
                text = _public_text(event.get("detail"), 220)
            elif phase in {"components", "connections"}:
                text = _draft_text(phase, event.get("draft"))
            else:
                return None
            if not text:
                return None
        elapsed_ms = min(
            MAX_ACTIVITY_DURATION_MS, max(self._last_elapsed_ms, elapsed_ms, 0)
        )
        if self._steps and all(
            self._steps[-1][key] == value
            for key, value in {
                "kind": kind,
                "phase": phase,
                "status": status,
                "text": text,
            }.items()
        ):
            return None
        step = ActivityStep(
            sequence=self._next_sequence,
            kind=kind,
            phase=phase,
            status=status,
            text=text[:400],
            elapsed_ms=elapsed_ms,
        ).model_dump()
        self._next_sequence += 1
        self._last_elapsed_ms = elapsed_ms
        self._steps = [*self._steps, step][-MAX_ACTIVITY_STEPS:]
        self._bound_steps(elapsed_ms)
        return {"type": "activity_step", **step}

    def snapshot(self, elapsed_ms: int) -> dict | None:
        if not self._steps:
            return None
        duration_ms = min(
            MAX_ACTIVITY_DURATION_MS, max(self._last_elapsed_ms, elapsed_ms, 0)
        )
        self._bound_steps(duration_ms)
        return MessageActivity(duration_ms=duration_ms, steps=self._steps).model_dump()

    def _bound_steps(self, duration_ms: int) -> None:
        while (
            len(
                json.dumps(
                    {"duration_ms": duration_ms, "steps": self._steps},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            > MAX_ACTIVITY_BYTES
        ):
            self._steps = self._steps[1:]
