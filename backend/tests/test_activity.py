import json

import pytest

from agent.activity import ActivityRecorder
from storage.message_activity import MessageActivity


def progress(phase="components", status="active", **extra):
    return {"type": "workflow_progress", "phase": phase, "status": status, **extra}


def test_mapper_only_records_known_public_workflow_events_and_tool_operations():
    recorder = ActivityRecorder()
    assert recorder.record({"type": "thinking_delta", "content": "private"}, 1) is None
    assert recorder.record({"type": "worker_status", "status": "private"}, 2) is None
    assert recorder.record(progress("unknown"), 3) is None
    assert recorder.record(progress(status="unknown"), 4) is None
    update = recorder.record(
        progress(detail="external_effects = True", diagnostic="secret"), 5
    )
    assert update["kind"] == "update"
    assert update["text"] == "I'm building the draft components."
    tool = recorder.record(progress("book"), 6)
    assert tool["kind"] == "tool" and tool["text"] == "Searching the book"
    assert "private" not in repr(recorder.snapshot(7))
    assert "external_effects" not in repr(recorder.snapshot(7))
    assert "secret" not in repr(recorder.snapshot(7))


@pytest.mark.parametrize(
    "detail", ["external_effects is false", "slot.name", '{"internal":"data"}']
)
def test_internal_public_findings_are_excluded(detail):
    recorder = ActivityRecorder()
    step = recorder.record(progress("architect", "complete", detail=detail), 0)
    assert step["text"] == "I've prepared the draft design."


def test_completed_public_findings_are_bounded_and_preview_counts_remain_drafts():
    recorder = ActivityRecorder()
    finding = "The runtime uses a queue."
    step = recorder.record(progress("architect", "complete", detail=finding), 10)
    assert finding in step["text"]
    recorder.record(
        {
            "type": "graph_preview",
            "data": {
                "title": "Queue design",
                "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                "edges": [{"source": "a", "target": "b"}],
            },
        },
        12,
    )
    components = recorder.record(progress("components", "complete"), 13)
    assert components["text"] == "I've prepared 2 draft components for Queue design."
    connections = recorder.record(progress("connections", "complete"), 14)
    assert connections["text"] == "I've prepared 1 draft connection for Queue design."
    assert "approved" not in components["text"] + connections["text"]
    assert (
        recorder.record(progress("review", "rejected"), 15)["text"]
        == "I couldn't complete this diagram check."
    )


def test_activity_deduplicates_consecutive_steps_bounds_history_and_hoisted_time():
    recorder = ActivityRecorder()
    assert recorder.snapshot(0) is None
    recorder.record(progress(), 10)
    assert recorder.record(progress(), 20) is None
    for index in range(1, 61):
        recorder.record(progress(status="complete" if index % 2 else "active"), index)
    snapshot = recorder.snapshot(2)
    assert len(snapshot["steps"]) == 48
    assert snapshot["steps"][0]["sequence"] == 13
    assert snapshot["steps"][-1]["sequence"] == 60
    assert snapshot["duration_ms"] == 60
    MessageActivity.model_validate(snapshot)
    assert recorder.snapshot(100_000_000)["duration_ms"] == 86_400_000


def test_activity_serialized_unicode_byte_envelope_drops_oldest_steps():
    recorder = ActivityRecorder()
    for index in range(60):
        recorder.record(
            progress(
                "architect" if index % 2 else "challenger",
                "complete",
                detail="😀" * 220,
            ),
            index,
        )
    snapshot = recorder.snapshot(100)
    assert len(snapshot["steps"]) < 48
    assert (
        len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode())
        <= 32_768
    )
    assert snapshot["steps"][-1]["sequence"] == 59
    MessageActivity.model_validate(snapshot)


@pytest.mark.parametrize(
    "event",
    [
        {"type": []},
        {"type": {}},
        progress(phase={}),
        progress(phase=[]),
        progress(status={}),
        progress(status=[]),
    ],
)
def test_malformed_event_types_are_ignored(event):
    recorder = ActivityRecorder()
    assert recorder.record(event, 0) is None
    assert recorder.snapshot(1) is None


@pytest.mark.parametrize(
    "graph",
    [
        {"nodes": [{"id": "a"}], "edges": []},
        {
            "nodes": [{"id": "a", "label": "A"}],
            "edges": [{"source": "a", "target": "missing"}],
        },
        {"nodes": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}], "edges": []},
    ],
)
def test_invalid_preview_identity_does_not_personalize_completed_update(graph):
    recorder = ActivityRecorder()
    assert recorder.record({"type": "graph_preview", "data": graph}, 0) is None
    assert (
        recorder.record(progress(status="complete"), 1)["text"]
        == "I've prepared the draft components for review."
    )


def test_invalid_or_reset_preview_cannot_reuse_stale_public_counts():
    recorder = ActivityRecorder()
    preview = {
        "type": "graph_preview",
        "data": {
            "title": "Earlier draft",
            "nodes": [{"id": "a", "label": "A"}],
            "edges": [],
        },
    }
    recorder.record(preview, 0)
    recorder.record({"type": "graph_preview", "data": None}, 1)
    assert (
        recorder.record(progress(status="complete"), 2)["text"]
        == "I've prepared the draft components for review."
    )
    recorder.record(preview, 3)
    recorder.record({"type": "response_reset"}, 4)
    assert (
        recorder.record(progress("connections", "complete"), 5)["text"]
        == "I've prepared the draft connections for review."
    )
