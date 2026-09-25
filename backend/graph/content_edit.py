"""Validated, topology-preserving edits to a saved graph."""

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.graph_identity import applied_edge_metadata
from agent.staged_graph_contract import (
    COMPONENT_LABEL_MAX_CHARS,
    COMPONENT_RESPONSIBILITY_MAX_CHARS,
    CONNECTION_LABEL_MAX_CHARS,
    Flow,
    NodeType,
)
from config import settings


class GraphEditNotFound(Exception):
    """The caller has no saved graph at this thread ID."""


class GraphEditConflict(Exception):
    """The graph changed or an agent turn is already editing the thread."""


class GraphEditTooLarge(Exception):
    """The edited graph exceeds the storage limit."""


class GraphEditInvalid(ValueError):
    """The requested selector or resulting graph is invalid."""


_NODE_FIELDS = frozenset({"label", "type", "technology", "description"})
_EDGE_FIELDS = frozenset({"label", "technology", "description", "flow", "sync"})
_NODE_SOURCE_FIELDS = (
    "canonical_id",
    "confidence",
    "evidence_chunk_ids",
    "book_refs",
)
_EDGE_SOURCE_FIELDS = ("confidence", "supporting_chunk_ids")


class NodeContentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=256)
    label: str | None = Field(default=None, max_length=COMPONENT_LABEL_MAX_CHARS)
    type: NodeType | None = None
    technology: str | None = Field(default=None, max_length=100)
    description: str | None = Field(
        default=None, max_length=COMPONENT_RESPONSIBILITY_MAX_CHARS
    )

    @model_validator(mode="after")
    def validate_edit(self):
        changed_fields = self.model_fields_set - {"id"}
        if not self.id.strip() or not changed_fields:
            raise ValueError("node edit requires an ID and at least one field")
        for field in changed_fields:
            value = getattr(self, field)
            if value is None or (
                field != "technology" and isinstance(value, str) and not value.strip()
            ):
                raise ValueError(f"node {field} cannot be blank or null")
        return self


class EdgeContentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    index: int = Field(ge=0)
    label: str | None = Field(default=None, max_length=CONNECTION_LABEL_MAX_CHARS)
    technology: str | None = Field(default=None, max_length=100)
    description: str | None = Field(
        default=None, max_length=COMPONENT_RESPONSIBILITY_MAX_CHARS
    )
    flow: Flow | None = None
    sync: Literal["sync", "async"] | None = None

    @model_validator(mode="after")
    def validate_edit(self):
        changed_fields = self.model_fields_set - {"index"}
        if not changed_fields:
            raise ValueError("edge edit requires at least one field")
        for field in changed_fields:
            value = getattr(self, field)
            if value is None or (
                field != "technology" and isinstance(value, str) and not value.strip()
            ):
                raise ValueError(f"edge {field} cannot be blank or null")
        return self


class GraphContentEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: str | None
    nodes: list[NodeContentEdit] = Field(default_factory=list)
    edges: list[EdgeContentEdit] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_edit(self):
        if self.expected_version is not None and not self.expected_version.strip():
            raise ValueError("expected_version cannot be blank")
        if not self.nodes and not self.edges:
            raise ValueError("graph edit cannot be empty")
        node_ids = [node.id for node in self.nodes]
        edge_indexes = [edge.index for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate node edit ID")
        if len(edge_indexes) != len(set(edge_indexes)):
            raise ValueError("duplicate edge edit index")
        if (
            len(self.nodes) > settings.graph_safety_max_nodes
            or len(self.edges) > settings.graph_safety_max_edges
        ):
            raise ValueError("graph edit exceeds record limit")
        return self


def _edited_fields(existing: dict[str, Any], changed: set[str]) -> list[str]:
    prior = existing.get("user_edited_fields")
    saved = (
        {
            field
            for field in prior
            if isinstance(field, str) and field in _NODE_FIELDS | _EDGE_FIELDS
        }
        if isinstance(prior, list)
        else set()
    )
    return sorted(saved | changed)


def apply_graph_content_edit(
    graph: dict[str, Any], request: GraphContentEditRequest
) -> tuple[dict[str, Any], bool]:
    """Return a new graph and whether any requested content changed."""
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
        raise GraphEditInvalid("saved graph nodes are invalid")
    if not isinstance(edges, list) or not all(isinstance(edge, dict) for edge in edges):
        raise GraphEditInvalid("saved graph edges are invalid")

    edited = deepcopy(graph)
    edited_nodes = edited["nodes"]
    edited_edges = edited["edges"]
    if not all(isinstance(node.get("id"), str) and node["id"] for node in edited_nodes):
        raise GraphEditInvalid("saved graph node IDs are invalid")
    node_by_id = {node["id"]: node for node in edited_nodes}
    if len(node_by_id) != len(edited_nodes):
        raise GraphEditInvalid("saved graph node IDs are ambiguous")

    changed = False
    changed_edge_labels: set[int] = set()
    for update in request.nodes:
        node = node_by_id.get(update.id)
        if node is None:
            raise GraphEditInvalid(f"unknown node ID: {update.id}")
        values = update.model_dump(exclude_unset=True, exclude={"id"})
        fields = {field for field, value in values.items() if node.get(field) != value}
        if not fields:
            continue
        if not fields <= _NODE_FIELDS:
            raise GraphEditInvalid("invalid node edit fields")
        node.update({field: values[field] for field in fields})
        for field in _NODE_SOURCE_FIELDS:
            node.pop(field, None)
        node["detail"] = None
        node["user_edited_fields"] = _edited_fields(node, fields)
        changed = True

    for update in request.edges:
        if update.index >= len(edited_edges):
            raise GraphEditInvalid(f"unknown edge index: {update.index}")
        edge = edited_edges[update.index]
        values = update.model_dump(exclude_unset=True, exclude={"index"})
        fields = {field for field, value in values.items() if edge.get(field) != value}
        if not fields:
            continue
        if not fields <= _EDGE_FIELDS:
            raise GraphEditInvalid("invalid edge edit fields")
        edge.update({field: values[field] for field in fields})
        if (
            "flow" in fields
            and edge.get("type") == "loop"
            and edge["flow"] != "feedback"
        ):
            raise GraphEditInvalid("loop edges require feedback flow")
        for field in _EDGE_SOURCE_FIELDS:
            edge.pop(field, None)
        if "label" in fields and graph.get("design_origin") != "applied":
            edge.pop("relation", None)
        if "label" in fields and graph.get("design_origin") == "applied":
            source = edge.get("source")
            target = edge.get("target")
            if not isinstance(source, str) or not isinstance(target, str):
                raise GraphEditInvalid("saved edge endpoints are invalid")
            edge.update(applied_edge_metadata(source, target, edge["label"]))
            changed_edge_labels.add(update.index)
        elif "label" in fields:
            changed_edge_labels.add(update.index)
        edge["user_edited_fields"] = _edited_fields(edge, fields)
        changed = True

    for index in changed_edge_labels:
        edge = edited_edges[index]
        for other_index, other in enumerate(edited_edges):
            if other_index == index:
                continue
            same_connection = (
                other.get("source") == edge.get("source")
                and other.get("target") == edge.get("target")
                and str(other.get("label") or "").strip().casefold()
                == str(edge.get("label") or "").strip().casefold()
            )
            same_applied_id = graph.get("design_origin") == "applied" and other.get(
                "edge_id"
            ) == edge.get("edge_id")
            if same_connection or same_applied_id:
                raise GraphEditInvalid("edge label duplicates another connection")
    return edited, changed
