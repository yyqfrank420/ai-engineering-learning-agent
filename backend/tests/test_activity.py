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
    assert (
        update["text"]
        == "I'll start with the main parts. Once the draft has been checked, I'll add the connections."
    )
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
    assert recorder.record(progress("architect", "complete", detail=detail), 0) is None


@pytest.mark.parametrize("phase", ["architect", "challenger"])
def test_completed_public_finding_is_its_own_bounded_paragraph(phase):
    recorder = ActivityRecorder()
    finding = "The runtime uses a queue."
    assert (
        recorder.record(progress(phase, "complete", detail=finding), 10)["text"]
        == finding
    )
    assert (
        len(recorder.record(progress(phase, "complete", detail="x" * 500), 11)["text"])
        == 220
    )


@pytest.mark.parametrize(
    "phase",
    [
        "context",
        "evidence",
        "architect",
        "challenger",
        "integrate",
        "revise",
        "explain",
        "synthesis",
    ],
)
def test_generic_completion_is_omitted_without_consuming_sequence(phase):
    recorder = ActivityRecorder()
    assert recorder.record(progress(phase, "complete"), 0) is None
    assert recorder.record(progress(phase, "active"), 1)["sequence"] == 0


@pytest.mark.parametrize(
    "phase,active,complete",
    [
        ("render", "Checking the layout", "Layout checked"),
        ("review", "Checking the draft", "Draft checked"),
    ],
)
def test_layout_and_review_are_quiet_check_rows(phase, active, complete):
    recorder = ActivityRecorder()
    for status, text in [
        ("active", active),
        ("complete", complete),
        ("retry", "Checking the draft again"),
        (
            "rejected",
            "Layout check not completed"
            if phase == "render"
            else "Review not completed",
        ),
        (
            "degraded",
            "Layout check not completed"
            if phase == "render"
            else "Review not completed",
        ),
    ]:
        step = recorder.record(progress(phase, status, detail="SECRET_DIAGNOSTIC"), 1)
        assert step["kind"] == "tool" and step["text"] == text


@pytest.mark.parametrize(
    "nodes,edges,components,connections",
    [
        (0, 0, "no components", "no connections"),
        (1, 1, "1 component", "1 connection"),
        (3, 2, "3 components", "2 connections"),
    ],
)
def test_draft_summaries_use_current_facts_and_grammatical_counts(
    nodes, edges, components, connections
):
    recorder = ActivityRecorder()
    draft = {
        "title": "Queue design",
        "component_count": nodes,
        "connection_count": edges,
        "labels": ["Queue", "Worker"][: min(2, nodes)],
    }
    first = recorder.record(progress("components", "complete", draft=draft), 1)
    assert f"for Queue design has {components}" in first["text"]
    assert ("including" in first["text"]) == bool(nodes)
    assert "before adding the connections" in first["text"]
    second = recorder.record(progress("connections", "complete", draft=draft), 2)
    assert f"{connections} across {components}" in second["text"]
    assert "before presenting the diagram" in second["text"]
    assert "approved" not in first["text"] + second["text"]


def test_activity_deduplicates_consecutive_steps_bounds_history_and_hoisted_time():
    recorder = ActivityRecorder()
    assert recorder.snapshot(0) is None
    recorder.record(progress(), 10)
    assert recorder.record(progress(), 20) is None
    for index in range(1, 61):
        recorder.record(progress(status="retry" if index % 2 else "active"), index)
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
    "summary",
    [
        None,
        [],
        {},
        {"component_count": True, "connection_count": 1},
        {"component_count": 2, "connection_count": False},
        {"component_count": -1, "connection_count": 1},
        {"component_count": 2, "connection_count": -1},
        {"component_count": 2.0, "connection_count": 1},
        {"component_count": 2, "connection_count": "1"},
        {"component_count": 2, "connection_count": 1, "labels": [False]},
        {"component_count": 2, "connection_count": 1, "labels": ["A", "B", "C"]},
        {"component_count": 1, "connection_count": 1, "labels": ["A", "B"]},
        {"component_count": 2, "connection_count": 1, "diagnostic": "private"},
    ],
)
@pytest.mark.parametrize("phase", ["components", "connections"])
def test_missing_or_invalid_draft_facts_are_omitted(phase, summary):
    recorder = ActivityRecorder()
    assert recorder.record(progress(phase, "complete", draft=summary), 1) is None
    assert recorder.snapshot(2) is None


def test_graph_previews_and_resets_cannot_personalize_completion():
    recorder = ActivityRecorder()
    for event in [
        {
            "type": "graph_preview",
            "data": {
                "title": "Earlier draft",
                "nodes": [{"id": "a", "label": "A"}],
                "edges": [],
            },
        },
        {"type": "graph_data", "data": None},
        {"type": "response_reset"},
    ]:
        assert recorder.record(event, 0) is None
        assert recorder.record(progress("connections", "complete"), 1) is None
    draft = {
        "title": "Current",
        "component_count": 2,
        "connection_count": 3,
        "labels": [],
    }
    assert (
        "3 connections"
        in recorder.record(progress("connections", "complete", draft=draft), 2)["text"]
    )


def test_draft_names_are_sanitized_bounded_and_never_include_internal_fields():
    recorder = ActivityRecorder()
    draft = {
        "title": "internal_title",
        "component_count": 2,
        "connection_count": 1,
        "labels": ["external_effects", "Queue"],
    }
    step = recorder.record(
        progress("components", "complete", draft=draft, diagnostic="secret"), 0
    )
    assert "including Queue" in step["text"]
    assert (
        "internal" not in step["text"]
        and "external" not in step["text"]
        and "secret" not in step["text"]
    )
    draft = {**draft, "title": "😀" * 200, "labels": ["東京" * 100, "🚀" * 100]}
    step = recorder.record(progress("components", "complete", draft=draft), 1)
    assert len(step["text"]) <= 400
    MessageActivity.model_validate(recorder.snapshot(2))


@pytest.mark.parametrize("phase", ["components", "connections"])
def test_draft_clarification_and_failure_describe_known_outcome(phase):
    recorder = ActivityRecorder()
    assert (
        recorder.record(progress(phase, "degraded"), 1)["text"]
        == "I need a little more detail before I can build this part of the diagram."
    )
    assert (
        recorder.record(progress(phase, "rejected"), 2)["text"]
        == "I couldn't finish this draft. You can retry the request."
    )


def test_counts_too_large_for_public_sentences_are_rejected_without_formatting():
    recorder = ActivityRecorder()
    summary = {"component_count": 10**5000, "connection_count": 1}
    assert recorder.record(progress("components", "complete", draft=summary), 1) is None
    summary = {"component_count": 2, "connection_count": 10**5000}
    assert (
        recorder.record(progress("connections", "complete", draft=summary), 2) is None
    )


@pytest.mark.parametrize(
    "phase,ending",
    [
        ("components", "I'll check it before adding the connections."),
        (
            "connections",
            "I'll check how they fit together before presenting the diagram.",
        ),
    ],
)
def test_maximum_draft_display_values_keep_complete_sentences(phase, ending):
    recorder = ActivityRecorder()
    summary = {
        "title": "東京" * 100,
        "component_count": 10**20 - 1,
        "connection_count": 10**20 - 1,
        "labels": ["Queue" * 30, "Worker" * 30],
    }
    text = recorder.record(progress(phase, "complete", draft=summary), 0)["text"]
    assert len(text) <= 400
    assert text.endswith(ending)


@pytest.mark.parametrize("phase", ["components", "connections"])
def test_connections_without_components_are_not_public_facts(phase):
    recorder = ActivityRecorder()
    assert (
        recorder.record(
            progress(
                phase, "complete", draft={"component_count": 0, "connection_count": 1}
            ),
            0,
        )
        is None
    )


def test_duplicate_public_labels_are_named_once():
    recorder = ActivityRecorder()
    summary = {
        "component_count": 2,
        "connection_count": 1,
        "labels": ["Queue", " Queue "],
    }
    text = recorder.record(progress("components", "complete", draft=summary), 0)["text"]
    assert "including Queue." in text
    assert "Queue and Queue" not in text
