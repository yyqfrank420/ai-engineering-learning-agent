"""Server-owned limits for expanding application service internals."""

import copy

import pytest

from agent.nodes import graph_worker
from agent import staged_graph_workflow as workflow
from config import settings


def _graph():
    return {
        "graph_type": "architecture",
        "title": "Checkout",
        "design_origin": "applied",
        "resolved_complexity": "prototype",
        "assumptions": [],
        "sequence": [],
        "nodes": [
            {"id": "app", "type": "client", "label": "Customer app"},
            {"id": "payments", "type": "service", "label": "Payment service"},
            {"id": "orders", "type": "service", "label": "Order service"},
            {"id": "store", "type": "datastore", "label": "Order store"},
        ],
        "edges": [
            {"source": "app", "target": "payments", "label": "pays"},
            {"source": "app", "target": "orders", "label": "orders"},
            {"source": "orders", "target": "store", "label": "writes"},
        ],
        "groups": [
            {
                "id": "runtime",
                "label": "Checkout",
                "kind": "runtime",
                "nodeIds": ["app", "payments", "orders", "store"],
            }
        ],
    }


def _scope(graph, targets):
    return graph_worker.staged_edit_scope(
        "Expand the selected services",
        graph,
        resolved_complexity="prototype",
        service_expansion={
            "target_service_ids": targets,
            "complexity": "high",
            "request": "Expand the selected services",
        },
    )[1]


def _candidate(graph, parents):
    result = copy.deepcopy(graph)
    for index, parent in enumerate(parents):
        node_id = f"child_{index}"
        result["nodes"].append(
            {
                "id": node_id,
                "type": "component",
                "label": node_id,
                "parent_service_id": parent,
            }
        )
        result["edges"].append({"source": parent, "target": node_id, "label": "calls"})
        result["groups"][0]["nodeIds"].append(node_id)
    return result


@pytest.mark.parametrize("targets", [["payments"], ["payments", "orders"]])
def test_scope_accepts_named_and_all_valid_service_targets(targets):
    graph = _graph()
    permissions = _scope(graph, targets)
    assert permissions["minimum_new_node_count"] == len(targets)
    assert permissions["allowed_new_node_count"] == 3 * len(targets)
    candidate = _candidate(graph, [target for target in targets for _ in range(3)])
    assert (
        graph_worker.admit_graph_extension(graph, candidate, permissions) == candidate
    )
    assert candidate["nodes"][: len(graph["nodes"])] == graph["nodes"]


@pytest.mark.parametrize(
    "targets", [[], ["store"], ["missing"], ["payments", "payments"], [True]]
)
def test_scope_rejects_missing_non_service_duplicate_or_malformed_targets(targets):
    with pytest.raises(ValueError, match="distinct current application services"):
        _scope(_graph(), targets)


def test_scope_requires_capacity_for_each_selected_service(monkeypatch):
    monkeypatch.setattr(settings, "graph_safety_max_nodes", 5)
    with pytest.raises(ValueError, match="cannot expand every requested service"):
        _scope(_graph(), ["payments", "orders"])


@pytest.mark.parametrize(
    "change", ["service_type", "orphan", "wrong_parent", "missing_target", "too_many"]
)
def test_admission_rejects_unowned_or_unbounded_additions(change):
    graph = _graph()
    permissions = _scope(graph, ["payments", "orders"])
    candidate = _candidate(graph, ["payments", "orders"])
    if change == "service_type":
        candidate["nodes"][-1]["type"] = "service"
    elif change == "orphan":
        candidate["nodes"][-1].pop("parent_service_id")
    elif change == "wrong_parent":
        candidate["nodes"][-1]["parent_service_id"] = "store"
    elif change == "missing_target":
        candidate = _candidate(graph, ["payments", "payments"])
    else:
        candidate = _candidate(graph, ["payments"] * 4 + ["orders"])
    with pytest.raises(ValueError, match="selected service|one to three"):
        graph_worker.admit_graph_extension(graph, candidate, permissions)


@pytest.mark.parametrize("endpoint", ["store", "orders", "child_1"])
def test_connections_cannot_escape_selected_service_interfaces(endpoint):
    graph = _graph()
    candidate = _candidate(graph, ["payments", "orders"])
    candidate["edges"].append(
        {"source": "child_0", "target": endpoint, "label": "escapes"}
    )
    with pytest.raises(ValueError, match="parent interface|named connection scope"):
        graph_worker.admit_graph_extension(
            graph, candidate, _scope(graph, ["payments", "orders"])
        )


def test_connections_allow_service_neighbors_and_same_parent_siblings():
    graph = _graph()
    candidate = _candidate(graph, ["payments", "payments"])
    candidate["edges"].extend(
        [
            {"source": "child_0", "target": "app", "label": "responds"},
            {"source": "child_0", "target": "child_1", "label": "delegates"},
        ]
    )
    graph_worker.admit_graph_extension(graph, candidate, _scope(graph, ["payments"]))


@pytest.mark.parametrize("collection", ["nodes", "edges", "groups"])
def test_expansion_cannot_change_saved_records(collection):
    graph = _graph()
    candidate = _candidate(graph, ["payments"])
    candidate[collection][0]["label"] = "Changed"
    with pytest.raises(ValueError, match="changed saved"):
        graph_worker.admit_graph_extension(
            graph, candidate, _scope(graph, ["payments"])
        )


@pytest.mark.parametrize(
    "override",
    [{"graph_action": "answer"}, {"graph_mode": "off"}, {"graph_intent": None}],
)
def test_expansion_never_forces_explicit_answer_or_graph_off(monkeypatch, override):
    monkeypatch.setattr(settings, "graph_pipeline_mode", "legacy")
    state = {
        "is_applied_design": True,
        "graph_intent": "edit",
        "graph_mode": "auto",
        "service_expansion": {"target_service_ids": ["payments"]},
    }
    assert workflow.should_use_staged_graph_pipeline(state)
    assert not workflow.should_use_staged_graph_pipeline({**state, **override})


def test_legacy_normalization_preserves_and_validates_component_parent():
    graph = _candidate(_graph(), ["payments"])
    for node in graph["nodes"]:
        node.update(
            technology="Component"
            if node["type"] == "component"
            else "Application service",
            description=node["label"],
        )
    for edge in graph["edges"]:
        edge.update(technology="HTTP", description=edge["label"])
    result = graph_worker._normalise_applied_graph(
        graph,
        safety_max_nodes=60,
        resolved_complexity="prototype",
    )
    assert result["nodes"][-1]["parent_service_id"] == "payments"
    graph["nodes"][-1]["parent_service_id"] = "store"
    with pytest.raises(ValueError, match="application service"):
        graph_worker._normalise_applied_graph(
            graph, safety_max_nodes=60, resolved_complexity="prototype"
        )


@pytest.mark.asyncio
async def test_multi_service_expansion_preserves_parent_ownership_and_runs_existing_gates(
    monkeypatch,
):
    from agent.staged_graph_contract import assign_server_ids, project_graph_data
    from test_staged_graph_workflow import (
        _components_wire,
        _connections_wire,
        _install_success_boundaries,
        _state,
    )

    events = []
    _install_success_boundaries(monkeypatch, events=events)
    wire = _components_wire()
    wire["components"].append(
        {
            **wire["components"][1],
            "label": "Order service",
            "responsibility": "Owns order creation.",
        }
    )
    connections = _connections_wire()
    connections["edges"].append(
        {**connections["edges"][0], "target_index": 2, "label": "submits order"}
    )
    build = assign_server_ids(
        {
            **wire,
            "components": workflow._decode_components(wire),
            "connections": workflow._decode_connections(connections),
            "maturity": "prototype",
            "source": "staged",
            "stage": "connections",
            "request_id": "saved",
        }
    )
    saved = project_graph_data(build)
    targets = [node["id"] for node in saved["nodes"] if node["type"] == "service"]
    for index in [1, 2]:
        wire["components"].append(
            {
                "label": f"Internal worker {index}",
                "type": 109,
                "parent_index": index,
                "responsibility": "Owns a step inside the parent service.",
                "group_label": "Runtime",
                "group_kind": 600,
                "primary_flow_member": False,
            }
        )
        connections["edges"].append(
            {
                "source_index": index,
                "target_index": index + 2,
                "label": "delegates internal work",
                "flow": 400,
                "sync": 500,
            }
        )

    async def components(**kwargs):
        assert kwargs["request"] == "Expand all application services"
        assert kwargs["edit_permissions"]["service_expansion_target_ids"] == targets
        events.append("components")
        return {"wire": wire, "prompt_fingerprint": "service-components"}

    async def edges(**kwargs):
        assert [
            row["parent_index"]
            for row in kwargs["accepted_components"]
            if row["type"] == 109
        ] == [1, 2]
        events.append("connections")
        return {"wire": connections, "prompt_fingerprint": "service-connections"}

    monkeypatch.setattr(workflow, "generate_component_candidate", components)
    monkeypatch.setattr(workflow, "generate_connection_candidate", edges)
    result = await workflow.run_staged_graph_pipeline(
        _state(
            graph_intent="edit",
            graph_action="edit",
            user_message="please do",
            graph_data=saved,
            approved_graph_data=saved,
            complexity="auto",
            service_expansion={
                "target_service_ids": targets,
                "complexity": "high",
                "request": "Expand all application services",
            },
        )
    )
    assert result["graph_publication"] == "approved", result["graph_operation"]
    expanded = result["graph_data"]
    assert expanded["nodes"][:3] == saved["nodes"]
    assert expanded["edges"][:2] == saved["edges"]
    assert [node["parent_service_id"] for node in expanded["nodes"][3:]] == targets
    assert all(
        node["type"] == "component" and node["technology"] == "Component"
        for node in expanded["nodes"][3:]
    )
    assert "component_gate" in events and "connection_gate" in events
