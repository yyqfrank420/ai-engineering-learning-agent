"""Regression checks for saved graph content across generation paths."""

import copy

import pytest

from agent.nodes import graph_worker


@pytest.mark.asyncio
async def test_concept_followup_retains_user_edits_on_matching_canonical_ids(monkeypatch):
    saved = {
        "graph_type": "concept",
        "title": "Retrieval and generation",
        "version": "saved-v1",
        "nodes": [
            {
                "id": "concept_retrieval",
                "canonical_id": "concept:retrieval",
                "label": "My retrieval step",
                "type": "decision",
                "technology": "Book concept",
                "description": "Use the reader's selected sources.",
                "user_edited_fields": ["label", "type", "description"],
            }
        ],
        "edges": [],
        "sequence": [],
    }
    selected = {
        "graph_type": "concept",
        "title": "Retrieval and generation",
        "nodes": [
            {
                "id": "concept_retrieval",
                "canonical_id": "concept:retrieval",
                "label": "Retrieval",
                "type": "service",
                "technology": "Book concept",
                "description": "Finds relevant source material.",
                "confidence": 0.92,
                "evidence_chunk_ids": ["chunk-1"],
                "book_refs": ["Chapter 4, p.100"],
            },
            {
                "id": "concept_generation",
                "canonical_id": "concept:generation",
                "label": "Generation",
                "type": "service",
                "technology": "Book concept",
                "description": "Produces an answer.",
            },
        ],
        "edges": [],
        "sequence": [],
    }

    async def send(_event):
        pass

    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: object())
    monkeypatch.setattr(
        graph_worker,
        "select_canonical_graph",
        lambda **_kwargs: copy.deepcopy(selected),
    )
    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "Explain retrieval and generation in more detail",
            "design_query": "Explain retrieval and generation in more detail",
            "graph_data": saved,
            "approved_graph_data": copy.deepcopy(saved),
            "rag_chunks": [],
        },
        [],
    )

    by_id = {node["id"]: node for node in result["graph_data"]["nodes"]}
    retained = by_id["concept_retrieval"]
    assert retained["label"] == "My retrieval step"
    assert retained["type"] == "decision"
    assert retained["description"] == "Use the reader's selected sources."
    assert retained["user_edited_fields"] == ["description", "label", "type"]
    assert "canonical_id" not in retained
    assert "confidence" not in retained
    assert "evidence_chunk_ids" not in retained
    assert "book_refs" not in retained
    assert by_id["concept_generation"]["label"] == "Generation"
    assert by_id["concept_generation"]["canonical_id"] == "concept:generation"
    assert result["graph_data"]["version"] != saved["version"]


@pytest.mark.asyncio
async def test_concept_reselection_keeps_matching_overrides_and_fresh_new_records(monkeypatch):
    saved = {
        "graph_type": "concept",
        "title": "Retrieval",
        "version": "saved-v1",
        "nodes": [
            {
                "id": "concept_retrieval",
                "canonical_id": "concept:retrieval",
                "label": "My retrieval step",
                "type": "decision",
                "user_edited_fields": ["label", "type"],
            }
        ],
        "edges": [],
        "sequence": [],
    }
    selected = {
        "graph_type": "concept",
        "title": "Prompt engineering",
        "nodes": [
            {
                "id": "concept_retrieval",
                "canonical_id": "concept:retrieval",
                "label": "Retrieval",
                "type": "service",
            },
            {
                "id": "concept_prompt_engineering",
                "canonical_id": "concept:prompt_engineering",
                "label": "Prompt Engineering",
                "type": "service",
            },
        ],
        "edges": [],
        "sequence": [],
    }

    async def send(_event):
        pass

    monkeypatch.setattr(graph_worker, "load_canonical_graph_cached", lambda: object())
    monkeypatch.setattr(
        graph_worker,
        "select_canonical_graph",
        lambda **_kwargs: copy.deepcopy(selected),
    )
    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "Switch to prompt engineering",
            "graph_data": saved,
            "approved_graph_data": copy.deepcopy(saved),
            "rag_chunks": [],
        },
        [],
    )

    by_id = {node["id"]: node for node in result["graph_data"]["nodes"]}
    assert by_id["concept_retrieval"]["label"] == "My retrieval step"
    assert by_id["concept_retrieval"]["type"] == "decision"
    assert by_id["concept_retrieval"]["user_edited_fields"] == ["label", "type"]
    assert by_id["concept_prompt_engineering"]["label"] == "Prompt Engineering"
    assert "user_edited_fields" not in by_id["concept_prompt_engineering"]
    assert result["graph_data"]["title"] == "Prompt engineering"


def test_canonical_edge_override_clears_incoming_source_claims():
    saved = {
        "graph_type": "concept",
        "nodes": [],
        "edges": [
            {
                "source": "retrieval",
                "target": "generation",
                "edge_id": "canonical-edge",
                "label": "my saved relation",
                "technology": "Manual note",
                "user_edited_fields": ["label", "technology"],
            }
        ],
    }
    selected = {
        "graph_type": "concept",
        "nodes": [],
        "edges": [
            {
                "source": "retrieval",
                "target": "generation",
                "edge_id": "canonical-edge",
                "label": "feeds into",
                "technology": "Book evidence",
                "relation": "feeds_into",
                "confidence": 0.94,
                "supporting_chunk_ids": ["chunk-1"],
            }
        ],
    }

    result = graph_worker._preserve_canonical_user_content(saved, selected)

    assert result["edges"][0] == {
        "source": "retrieval",
        "target": "generation",
        "edge_id": "canonical-edge",
        "label": "my saved relation",
        "technology": "Manual note",
        "user_edited_fields": ["label", "technology"],
    }
    assert selected["edges"][0]["label"] == "feeds into"


def test_canonical_edge_fallback_skips_ambiguous_records():
    saved = {
        "graph_type": "concept",
        "nodes": [],
        "edges": [
            {
                "source": "a",
                "target": "b",
                "label": "relates to",
                "technology": value,
                "user_edited_fields": ["technology"],
            }
            for value in ("First override", "Second override")
        ],
    }
    selected = {
        "graph_type": "concept",
        "nodes": [],
        "edges": [
            {
                "source": "a",
                "target": "b",
                "label": "relates to",
                "technology": "Book evidence",
            }
        ],
    }

    result = graph_worker._preserve_canonical_user_content(saved, selected)

    assert result == selected


@pytest.mark.asyncio
async def test_explicit_create_does_not_overlay_old_canonical_content(monkeypatch):
    saved = {
        "graph_type": "concept",
        "nodes": [
            {
                "id": "concept_retrieval",
                "label": "My retrieval step",
                "user_edited_fields": ["label"],
            }
        ],
        "edges": [],
    }
    fresh = {
        "graph_type": "architecture",
        "design_origin": "applied",
        "nodes": [{"id": "concept_retrieval", "label": "Fresh design component"}],
        "edges": [],
    }

    async def send(_event):
        pass

    async def generate(*_args, **_kwargs):
        return copy.deepcopy(fresh)

    monkeypatch.setattr(graph_worker, "_generate_applied_architecture", generate)
    result = await graph_worker.graph_worker_node(
        {
            "send": send,
            "user_message": "Design a new retrieval system",
            "graph_intent": "create",
            "graph_data": saved,
            "approved_graph_data": copy.deepcopy(saved),
            "complexity": "prototype",
        },
        [],
    )

    assert result["graph_data"]["nodes"] == fresh["nodes"]
    assert result["graph_operation"]["kind"] == "create"


def _saved_applied_graph():
    return {
        "graph_type": "architecture",
        "design_origin": "applied",
        "resolved_complexity": "prototype",
        "title": "Reader request flow",
        "assumptions": [],
        "nodes": [
            {
                "id": node_id,
                "label": label,
                "type": node_type,
                "technology": "Python service",
                "description": (
                    "Checks authorization and access control."
                    if index == 0
                    else "Owns a bounded request responsibility."
                ),
                "user_edited_fields": ["type", "description"] if index == 0 else [],
            }
            for index, (node_id, label, node_type) in enumerate(
                (
                    ("reader", "Reader UI", "decision"),
                    ("service_b", "Service B", "service"),
                    ("service_c", "Service C", "service"),
                )
            )
        ],
        "edges": [
            {
                "source": source,
                "target": target,
                "label": label,
                "technology": "Saved protocol",
                "sync": "sync",
                "flow": "runtime",
                "description": "Moves a bounded request.",
                "user_edited_fields": ["label", "technology"] if index == 0 else [],
            }
            for index, (source, target, label) in enumerate(
                (
                    ("reader", "service_b", "submits saved request"),
                    ("service_b", "service_c", "passes result"),
                )
            )
        ],
        "sequence": [],
    }


def test_staged_edit_admission_retains_markers_on_unchanged_records():
    saved = _saved_applied_graph()
    candidate = copy.deepcopy(saved)
    candidate["nodes"][1]["label"] = "Coordinator B"
    contract, permissions = graph_worker.staged_edit_scope(
        "Rename Service B to Coordinator B.",
        saved,
        resolved_complexity="prototype",
    )

    result = graph_worker.admit_staged_graph_edit(
        saved,
        candidate,
        resolved_complexity="prototype",
        repair_contract=contract,
        mutation_permissions=permissions,
    )

    assert result["nodes"][0]["type"] == "decision"
    assert result["nodes"][0]["user_edited_fields"] == ["description", "type"]
    assert result["edges"][0]["user_edited_fields"] == ["label", "technology"]
    assert result["nodes"][1]["label"] == "Coordinator B"


def test_legacy_patch_retains_manual_decision_type_when_another_node_changes():
    saved = _saved_applied_graph()

    result = graph_worker._apply_applied_graph_patch(
        saved,
        {"update_nodes": [{"id": "service_b", "set": {"label": "Coordinator B"}}]},
        safety_max_nodes=3,
        resolved_complexity="prototype",
    )

    assert result["nodes"][0]["type"] == "decision"
    assert result["nodes"][0]["description"] == (
        "Checks authorization and access control."
    )
    assert result["nodes"][0]["user_edited_fields"] == ["description", "type"]
    assert result["nodes"][1]["label"] == "Coordinator B"


def test_legacy_patch_clears_only_explicitly_changed_user_edit_markers():
    saved = _saved_applied_graph()

    result = graph_worker._apply_applied_graph_patch(
        saved,
        {
            "update_nodes": [{"id": "reader", "set": {"type": "control"}}],
            "update_edges": [
                {"edge_id": "edge_1", "set": {"label": "checks saved request"}}
            ],
        },
        safety_max_nodes=3,
        resolved_complexity="prototype",
    )

    assert result["nodes"][0]["type"] == "control"
    assert result["nodes"][0]["user_edited_fields"] == ["description"]
    assert result["edges"][0]["label"] == "checks saved request"
    assert result["edges"][0]["user_edited_fields"] == ["technology"]
