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
_STAGE_TEXT = {
    "context": ("I'm checking what you need.", "I've prepared your request."),
    "evidence": (
        "I'm reading the sources for your request.",
        "I've gathered the available evidence.",
    ),
    "architect": (
        "I'm planning a draft diagram for you.",
        "I've prepared the draft design.",
    ),
    "challenger": (
        "I'm checking the design assumptions.",
        "I've finished checking the design assumptions.",
    ),
    "components": (
        "I'm building the draft components.",
        "I've prepared the draft components for review.",
    ),
    "connections": (
        "I'm connecting the draft components.",
        "I've prepared the draft connections for review.",
    ),
    "integrate": (
        "I'm bringing the diagram together.",
        "I've combined the draft diagram.",
    ),
    "render": ("I'm checking the diagram layout.", "I've finished the layout check."),
    "review": (
        "I'm reviewing the draft diagram.",
        "I've finished reviewing the diagram.",
    ),
    "revise": ("I'm refining the draft diagram.", "I've finished this refinement."),
    "explain": ("I'm writing the answer for you.", "I've prepared your answer."),
    "synthesis": ("I'm writing the answer for you.", "I've prepared your answer."),
}
_TOOL_TEXT = {
    "book": ("Searching the book", "Book search finished"),
    "web": ("Searching the web", "Web search finished"),
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


class ActivityRecorder:
    def __init__(self) -> None:
        self._steps: list[dict] = []
        self._next_sequence = 0
        self._last_elapsed_ms = 0
        self._preview: dict | None = None

    def record(self, event: dict, elapsed_ms: int) -> dict | None:
        event_type = event.get("type")
        if not isinstance(event_type, str):
            return None
        if event_type == "response_reset":
            self._preview = None
            return None
        if event_type in {"graph_preview", "graph_data"}:
            self._preview = None
            graph = event.get("data")
            if isinstance(graph, dict):
                nodes, edges = graph.get("nodes"), graph.get("edges")
                if not isinstance(nodes, list) or not isinstance(edges, list):
                    return None
                if not all(
                    isinstance(node, dict)
                    and isinstance(node.get("id"), str)
                    and node["id"]
                    and isinstance(node.get("label"), str)
                    and node["label"]
                    for node in nodes
                ):
                    return None
                node_ids = {node["id"] for node in nodes}
                if len(node_ids) != len(nodes) or not all(
                    isinstance(edge, dict)
                    and isinstance(edge.get("source"), str)
                    and isinstance(edge.get("target"), str)
                    and edge["source"] in node_ids
                    and edge["target"] in node_ids
                    for edge in edges
                ):
                    return None
                self._preview = {
                    "title": _public_text(graph.get("title"), 120),
                    "nodes": len(graph["nodes"]),
                    "edges": len(edges) if isinstance(edges, list) else None,
                }
            return None
        if event_type != "workflow_progress":
            return None
        phase, status = event.get("phase"), event.get("status")
        if (
            not isinstance(phase, str)
            or not isinstance(status, str)
            or status not in _STATUSES
            or phase not in _STAGE_TEXT.keys() | _TOOL_TEXT.keys()
        ):
            return None
        kind = "tool" if phase in _TOOL_TEXT else "update"
        labels = _TOOL_TEXT if kind == "tool" else _STAGE_TEXT
        text = labels[phase][1 if status == "complete" else 0]
        if status == "retry":
            text = (
                "I'm refining the draft after its checks."
                if kind == "update"
                else "Retrying the search"
            )
        elif status == "rejected":
            text = (
                "I couldn't complete this diagram check."
                if kind == "update"
                else "Search did not complete"
            )
        elif status == "degraded":
            text = (
                "This step returned limited results."
                if kind == "update"
                else "Search coverage is limited"
            )
        elif status == "complete" and phase in {"architect", "challenger"}:
            finding = _public_text(event.get("detail"), 220)
            if finding:
                text += " " + finding
        elif (
            status == "complete"
            and phase in {"components", "connections"}
            and self._preview
        ):
            count = self._preview["nodes" if phase == "components" else "edges"]
            if count is not None:
                title = self._preview["title"]
                noun = phase[:-1] if count == 1 else phase
                text = f"I've prepared {count} draft {noun}{f' for {title}' if title else ''}."
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
