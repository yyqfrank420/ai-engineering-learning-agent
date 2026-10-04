"""Server-owned limits for expanding application service internals."""

import copy
import json
from pathlib import Path

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


def _scope(graph, targets, *, resolved_complexity="prototype"):
    return graph_worker.staged_edit_scope(
        "Expand the selected services",
        graph,
        resolved_complexity=resolved_complexity,
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


# Accepted baseline and proposed children from the October 2 capture on 5eaf519.
# Turn 3 was rejected; this fixture tests routing admission and preservation only,
# and does not establish semantic approval.


def _local_serving_expansion():
    records = json.loads(
        (
            Path(__file__).parent / "fixtures/service_expansion_release_20261002.json"
        ).read_text()
    )
    baseline = records["baseline"]
    candidate = copy.deepcopy(baseline)
    candidate["nodes"].extend(records["internals"])
    candidate["groups"][0]["nodeIds"].extend(["n5", "n6"])
    candidate["groups"][1]["nodeIds"].extend(["n7", "n8"])
    permissions = _scope(baseline, ["n1", "n2"], resolved_complexity="production")
    additions = [
        ("n1", "n5", "Authenticated inference request with request ID"),
        ("n5", "n1", "Inference output with model version or typed error"),
        ("n1", "n6", "Apply version transition keyed by operation ID"),
        ("n6", "n1", "Applied active version or rejected transition with reason"),
        ("n2", "n7", "Request release transition with target and version"),
        ("n7", "n2", "Accepted transition operation ID or rejection reason"),
        (
            "n7",
            "n8",
            "Dispatch accepted transition with stable operation ID and version",
        ),
        (
            "n8",
            "n7",
            "Recorded applied version, rejection reason, or unresolved outcome",
        ),
        (
            "n8",
            "n1",
            "Apply release command with stable operation ID and expected active version",
        ),
        (
            "n1",
            "n8",
            "Command reply with matching operation ID, applied active version or rejection reason",
        ),
        (
            "n8",
            "n1",
            "Read authoritative active version and operation outcome after uncertain reply",
        ),
        (
            "n1",
            "n8",
            "Authoritative active version and recorded outcome keyed by operation ID",
        ),
    ]
    candidate["edges"].extend(
        {
            "source": source,
            "target": target,
            "label": label,
            "flow": "deployment",
            "sync": "sync",
        }
        for source, target, label in additions
    )
    return (
        baseline,
        _strict_connection_projection(baseline, candidate, permissions),
        permissions,
    )


def _strict_connection_projection(baseline, candidate, permissions):
    from agent.nodes import staged_graph_generation as generation
    from agent.staged_graph_contract import (
        project_graph_data,
        reconstruct_staged_graph_build,
    )

    build = reconstruct_staged_graph_build(
        candidate, request_id="offline-route-regression"
    )
    index_by_id = {row["server_id"]: row["model_index"] for row in build["components"]}
    flow_codes = {value: code for code, value in generation.FLOW_CODES.items()}
    sync_codes = {value: code for code, value in generation.SYNC_CODES.items()}
    wire = {
        "edges": [
            {
                "source_index": index_by_id[edge["source"]],
                "target_index": index_by_id[edge["target"]],
                "label": edge["label"],
                "flow": flow_codes[edge["flow"]],
                "sync": sync_codes[edge["sync"]],
            }
            for edge in candidate["edges"]
        ]
    }
    parsed = generation._parse_connection_wire(
        json.dumps(wire),
        accepted_components=[
            {**row, "index": row["model_index"]} for row in build["components"]
        ],
        edge_limit=settings.graph_safety_max_edges,
    )
    projected = project_graph_data(
        {**build, "connections": workflow._decode_connections(parsed)}
    )
    projected = workflow._preserve_existing_presentation(
        projected,
        baseline,
        edit_permissions=permissions,
    )
    return projected


def test_captured_service_scope_admits_dispatch_to_actual_serving_owner_and_read_back():
    baseline, candidate, permissions = _local_serving_expansion()
    before = copy.deepcopy(baseline)
    admitted = graph_worker.admit_staged_graph_edit(
        baseline,
        candidate,
        resolved_complexity="production",
        repair_contract=None,
        mutation_permissions=permissions,
    )
    assert "n1" in permissions["service_expansion_anchors"]["n2"]
    assert [
        (node["id"], node["parent_service_id"]) for node in admitted["nodes"][4:]
    ] == [
        ("n5", "n1"),
        ("n6", "n1"),
        ("n7", "n2"),
        ("n8", "n2"),
    ]
    for collection in ("nodes", "edges"):
        assert json.dumps(
            admitted[collection][: len(baseline[collection])]
        ) == json.dumps(baseline[collection])
    command, reply, read_back, observed = admitted["edges"][-4:]
    assert [
        (edge["source"], edge["target"])
        for edge in (command, reply, read_back, observed)
    ] == [
        ("n8", "n1"),
        ("n1", "n8"),
        ("n8", "n1"),
        ("n1", "n8"),
    ]
    assert "stable operation ID" in command["label"]
    assert "matching operation ID" in reply["label"]
    assert "Read authoritative active version" in read_back["label"]
    assert "Authoritative active version and recorded outcome" in observed["label"]
    assert baseline == before


@pytest.mark.parametrize(
    "change",
    [
        "foreign_anchor",
        "foreign_owner",
        "cross_service_internal",
        "saved_node",
        "saved_edge",
    ],
)
def test_captured_service_scope_rejects_foreign_authority_and_baseline_rewrites(change):
    baseline, candidate, permissions = _local_serving_expansion()
    if change == "foreign_anchor":
        candidate["edges"][-4]["target"] = "n4"
    elif change == "foreign_owner":
        candidate["nodes"][-1]["parent_service_id"] = "n3"
    elif change == "cross_service_internal":
        candidate["edges"][-4]["target"] = "n5"
    elif change == "saved_node":
        candidate["nodes"][0]["description"] = "Rewritten serving ownership"
    else:
        candidate["edges"][0]["label"] = "Rewritten release contract"
    with pytest.raises(
        ValueError, match="parent interface|selected service|changed saved"
    ):
        graph_worker.admit_staged_graph_edit(
            baseline,
            candidate,
            resolved_complexity="production",
            repair_contract=None,
            mutation_permissions=permissions,
        )


# Graph-only baseline and rejected second connection preview from cloud 00a69b8.
# The corrected exchanges below establish wire/scope admission and preservation,
# without claiming a fresh semantic approval.
def _cloud_serving_expansion():
    records = json.loads(
        (
            Path(__file__).parent / "fixtures/service_expansion_cloud_00a69b8.json"
        ).read_text()
    )
    baseline = records["baseline"]
    rejected = records["rejected_candidate"]
    permissions = _scope(baseline, ["n1", "n3"], resolved_complexity="production")
    return baseline, rejected, permissions


def _correct_cloud_dispatcher_exchanges(candidate):
    from agent.graph_identity import applied_edge_metadata

    corrected = copy.deepcopy(candidate)
    exchanges = [
        (
            "n11",
            "n1",
            "Deploy approved version/action to target with approval ref and stable operation ID",
        ),
        (
            "n1",
            "n11",
            "Serving API reply matching operation ID: loaded version, replayed result, or rejection reason",
        ),
        (
            "n11",
            "n1",
            "Read authoritative loaded version and activation status for operation ID after uncertain reply",
        ),
        (
            "n1",
            "n11",
            "Serving API authoritative status for operation ID: loaded version committed, not found, or applying",
        ),
    ]
    for index, (source, target, label) in enumerate(exchanges, start=36):
        corrected["edges"][index] = {
            **corrected["edges"][index],
            "source": source,
            "target": target,
            "label": label,
            "description": label,
            **applied_edge_metadata(source, target, label),
        }
    return corrected


def test_cloud_service_expansion_recovery_can_use_foreign_parent_with_existing_children():
    baseline, rejected, permissions = _cloud_serving_expansion()
    assert len(baseline["nodes"]) == 7 and len(baseline["edges"]) == 17
    assert len(rejected["nodes"]) == 12 and len(rejected["edges"]) == 43
    assert {
        node["id"]
        for node in baseline["nodes"]
        if node.get("parent_service_id") == "n1"
    } == {"n2", "n6", "n7"}
    assert "n1" in permissions["service_expansion_anchors"]["n3"]
    # Admission of the captured candidate does not establish semantic correctness.
    graph_worker.admit_staged_graph_edit(
        baseline,
        _strict_connection_projection(baseline, rejected, permissions),
        resolved_complexity="production",
        repair_contract=None,
        mutation_permissions=permissions,
    )
    corrected = _correct_cloud_dispatcher_exchanges(rejected)
    projected = _strict_connection_projection(baseline, corrected, permissions)
    admitted = graph_worker.admit_staged_graph_edit(
        baseline,
        projected,
        resolved_complexity="production",
        repair_contract=None,
        mutation_permissions=permissions,
    )
    changed = {
        index
        for index, (before, after) in enumerate(
            zip(rejected["edges"], admitted["edges"])
        )
        if before != after
    }
    assert changed == {36, 37, 38, 39}
    assert admitted["nodes"] == rejected["nodes"]
    assert admitted["groups"] == rejected["groups"]
    for field in ("sequence", "assumptions"):
        assert admitted[field] == baseline[field] == rejected[field]
    for collection in ("nodes", "edges"):
        assert json.dumps(
            admitted[collection][: len(baseline[collection])], sort_keys=True
        ) == json.dumps(baseline[collection], sort_keys=True)
    for before, after in zip(baseline["groups"], admitted["groups"]):
        assert {k: v for k, v in before.items() if k != "nodeIds"} == {
            k: v for k, v in after.items() if k != "nodeIds"
        }
        assert after["nodeIds"][: len(before["nodeIds"])] == before["nodeIds"]
    pairs = admitted["edges"][36:40]
    assert [(edge["source"], edge["target"]) for edge in pairs] == [
        ("n11", "n1"),
        ("n1", "n11"),
        ("n11", "n1"),
        ("n1", "n11"),
    ]
    assert pairs == corrected["edges"][36:40]


@pytest.mark.parametrize(
    "change", ["new_retained_relay", "rewrite_old_command", "rewrite_old_reply"]
)
def test_cloud_service_recovery_cannot_add_retained_relay_or_rewrite_saved_contract(
    change,
):
    baseline, rejected, permissions = _cloud_serving_expansion()
    corrected = _correct_cloud_dispatcher_exchanges(rejected)
    if change == "new_retained_relay":
        corrected["edges"].append(
            {
                "source": "n3",
                "target": "n1",
                "label": "Add missing operation-ID relay over retained services",
                "flow": "deployment",
                "sync": "sync",
            }
        )
    elif change == "rewrite_old_command":
        corrected["edges"][6]["label"] = (
            "Rewrite saved deploy contract to carry operation ID"
        )
    else:
        corrected["edges"][7]["label"] = (
            "Rewrite saved reply to return operation-correlated activation status"
        )
    projected = _strict_connection_projection(baseline, corrected, permissions)
    reason = (
        "extension connections must involve a new node"
        if change == "new_retained_relay"
        else "extension changed saved edges"
    )
    with pytest.raises(ValueError, match=reason):
        graph_worker.admit_staged_graph_edit(
            baseline,
            projected,
            resolved_complexity="production",
            repair_contract=None,
            mutation_permissions=permissions,
        )
