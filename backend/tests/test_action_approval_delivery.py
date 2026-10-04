"""Offline approval-contract boundaries; controlled verdicts are not model judgments."""

import asyncio
from copy import deepcopy
import json

import pytest

from agent import architecture_rubric as rubric
from agent.nodes import staged_graph_gate as gate
from agent.nodes import staged_graph_generation as generation
from agent.stream_utils import StructuredLLMResponse


# Exact raw cloud action-boundary subset: revision8bd4a49dc6383cff58b2844a7f7ef808b9f18b12,
# evaluation run36992512230, browser-results.json SHA256
# 9fbfd1ea8245a016a100592cd3005ade5e1e5d4a499cd12f6c6e645823eb99a6.
# n9 owns final approval; n3 returns only its preapproval validation verdict.
CAPTURED_COMPONENTS = [
    {
        "id": "n2",
        "lane": "main",
        "tier": None,
        "type": "service",
        "label": "Agent planner and reasoner",
        "layer": "architecture",
        "detail": None,
        "technology": "Application service",
        "description": "Analyzes the objective, plans steps, proposes typed tool actions with arguments, "
        "and reflects on tool results and memory to decide the next step or finish.",
        "design_origin": "applied",
    },
    {
        "id": "n3",
        "lane": "bottom",
        "tier": None,
        "type": "control",
        "label": "Action validation and policy check",
        "layer": "architecture",
        "detail": None,
        "technology": "Control component",
        "description": "Deterministically validates each proposed tool action's structure and allowed "
        "constraints against policy before any approval or execution, rejecting malformed "
        "or disallowed proposals.",
        "design_origin": "applied",
    },
    {
        "id": "n4",
        "lane": "main",
        "tier": None,
        "type": "service",
        "label": "Tool executor",
        "layer": "architecture",
        "detail": None,
        "technology": "Application service",
        "description": "Executes only validated and approved tool actions with a durable operation "
        "identity, invokes the target tool idempotently, reads back authoritative status, "
        "and returns results or errors to the planner.",
        "design_origin": "applied",
    },
    {
        "id": "n9",
        "lane": "bottom",
        "tier": None,
        "type": "control",
        "label": "Safety oversight and approval",
        "layer": "architecture",
        "detail": None,
        "technology": "Control component",
        "description": "Applies defensive guardrails for risky or irreversible tool actions, routes "
        "high-impact proposals for human approval, and can halt the agent on policy "
        "violations.",
        "design_origin": "applied",
    },
]
CAPTURED_RECORDS = [
    {
        "flow": "control",
        "sync": "sync",
        "label": "Propose typed tool action with arguments for normal or compensation step",
        "source": "n2",
        "target": "n3",
        "edge_id": "applied:n2__propose_typed_tool_action_with_argument_1db0c60478a00fa84e3a3351__n3",
        "relation": "propose_typed_tool_action_with_argument_1db0c60478a00fa84e3a3351",
        "technology": "Control flow",
        "description": "Propose typed tool action with arguments for normal or compensation step",
    },
    {
        "flow": "control",
        "sync": "sync",
        "label": "Verdict: accept; reject with violated structure or constraint before any approval or "
        "execution",
        "source": "n3",
        "target": "n2",
        "edge_id": "applied:n3__verdict_accept_reject_with_violated_str_be5c6e2606049328c5a43358__n2",
        "relation": "verdict_accept_reject_with_violated_str_be5c6e2606049328c5a43358",
        "technology": "Control flow",
        "description": "Verdict: accept; reject with violated structure or constraint before any "
        "approval or execution",
    },
    {
        "flow": "control",
        "sync": "sync",
        "label": "Request approval for validated risky normal or compensation action with exact payload",
        "source": "n3",
        "target": "n9",
        "edge_id": "applied:n3__request_approval_for_validated_risky_no_84ad31e06d4b0d640ee020f3__n9",
        "relation": "request_approval_for_validated_risky_no_84ad31e06d4b0d640ee020f3",
        "technology": "Control flow",
        "description": "Request approval for validated risky normal or compensation action with exact "
        "payload",
    },
    {
        "flow": "control",
        "sync": "sync",
        "label": "Approve with scope, reject with reason, or halt agent on violation",
        "source": "n9",
        "target": "n3",
        "edge_id": "applied:n9__approve_with_scope_reject_with_reason_o_d54727f250a6e1816161efb9__n3",
        "relation": "approve_with_scope_reject_with_reason_o_d54727f250a6e1816161efb9",
        "technology": "Control flow",
        "description": "Approve with scope, reject with reason, or halt agent on violation",
    },
    {
        "flow": "runtime",
        "sync": "sync",
        "label": "Invoke validated approved action with exact payload and durable operation identity",
        "source": "n2",
        "target": "n4",
        "edge_id": "applied:n2__invoke_validated_approved_action_with_e_e3494c863567c9d5ff45aa22__n4",
        "relation": "invoke_validated_approved_action_with_e_e3494c863567c9d5ff45aa22",
        "technology": "Runtime flow",
        "description": "Invoke validated approved action with exact payload and durable operation "
        "identity",
    },
]


def approval_candidate(route):
    if route == "captured_preapproval":
        return deepcopy(CAPTURED_COMPONENTS), deepcopy(CAPTURED_RECORDS)
    components = [
        {
            "id": "approval",
            "responsibility": "Issue the final allow, reject, or halt decision for the exact action identity and scope.",
        },
        {
            "id": "dispatch",
            "responsibility": "Dispatch only actions allowed by that final decision; reject or halt ends in an observable terminal outcome.",
        },
        {
            "id": "executor",
            "responsibility": "Enforce the final decision for the exact action identity and scope before external effects.",
        },
    ]
    contracts = {
        "direct": [
            (
                "approval",
                "executor",
                "Deliver final allow/reject/halt decision with exact action identity and scope before dispatch and effects; reject/halt terminates observably without execution",
            ),
        ],
        "forwarded": [
            (
                "approval",
                "dispatch",
                "Forward final decision with exact action identity and scope; bounded observable reject/halt",
            ),
            (
                "dispatch",
                "executor",
                "Forward same final allow/reject/halt decision, identity, scope and exact action; deny effects on reject/halt",
            ),
        ],
        "persisted_read": [
            (
                "approval",
                "store",
                "Persist authoritative final decision with action identity and scope; record reject/halt outcome without execution",
            ),
            (
                "dispatch",
                "store",
                "Read final decision for exact action identity and scope before dispatch; reject/halt ends observably",
            ),
            (
                "store",
                "dispatch",
                "Authoritative final allow/reject/halt decision and matching action identity and scope",
            ),
            (
                "dispatch",
                "executor",
                "Forward authoritative final decision, identity, scope and approved payload before effects",
            ),
        ],
        "same_owner": [
            (
                "executor",
                "external",
                "Execute exact action only after internal final approval enforcement; rejected or halted actions terminate observably",
            )
        ],
    }
    if route == "persisted_read":
        components.append(
            {
                "id": "store",
                "responsibility": "Own authoritative final decisions indexed by exact action identity and scope.",
            }
        )
    if route == "same_owner":
        components = [
            {
                "id": "executor",
                "responsibility": "Own final policy approval, action dispatch and execution; bind allow/reject/halt to exact action identity and scope before effects, and record bounded rejection or halt without execution.",
            }
        ]
    return components, [
        {"source": source, "target": target, "label": label}
        for source, target, label in contracts[route]
    ]


def generation_input(components, records, maturity):
    prompt, _ = generation._attempt_prompt(
        stage="connections",
        request="Draw an agent with policy-approved tool actions.",
        resolved_maturity=maturity,
        write_set=generation.create_write_set(component_limit=8, edge_limit=20),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base={"nodes": components, "edges": records},
        rejected_candidate=None,
        accepted_components=components,
    )
    return json.loads(prompt.split("\nINPUT\n", 1)[1])


@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.parametrize(
    "route",
    ["captured_preapproval", "direct", "forwarded", "persisted_read", "same_owner"],
)
def test_contracts_and_controlled_verdict_survive_generation_and_review(
    monkeypatch, maturity, route
):
    components, records = approval_candidate(route)
    original = deepcopy((components, records))
    authored = generation_input(components, records, maturity)
    assert authored["base"] == {"nodes": components, "edges": records}
    assert authored["accepted_components"] == components
    calls = []
    rejected = route == "captured_preapproval"
    reason = "Controlled boundary verdict: preliminary validation and an approved invocation label do not deliver the final approval decision."

    async def fake_review(**kwargs):
        calls.append(kwargs)
        codes = kwargs["response_schema"]["properties"]["rule_reviews"]["items"][
            "properties"
        ]["rule_code"]["enum"]
        rows = [
            {
                "rule_code": code,
                "satisfied": not (rejected and code == "safe_action_boundary"),
                "reason": reason
                if rejected and code == "safe_action_boundary"
                else "Controlled satisfied boundary response.",
                "record_indexes": [1, 4]
                if rejected and code == "safe_action_boundary"
                else [],
            }
            for code in codes
        ]
        return StructuredLLMResponse(
            text=json.dumps({"rule_reviews": rows}),
            finish_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
            provider="test",
            model="test",
        )

    monkeypatch.setattr(gate, "stream_structured_llm", fake_review)
    result = asyncio.run(
        gate.review_connections(
            user_request="Draw an agent with policy-approved tool actions.",
            evidence_bundle={"candidate_components": components},
            resolved_maturity=maturity,
            candidate_records=records,
        )
    )
    assert len(calls) == 1
    prompt = calls[0]["messages"][0]["content"]
    decoder = json.JSONDecoder()
    numbered, _ = decoder.raw_decode(
        prompt.split("Immutable candidate records: ", 1)[1]
    )
    evidence, _ = decoder.raw_decode(prompt.split("Evidence bundle: ", 1)[1])
    reviewed, _ = decoder.raw_decode(prompt.split("Acceptance criteria: ", 1)[1])
    assert [row["record"] for row in numbered] == records
    assert [row["record_index"] for row in numbered] == list(range(len(records)))
    assert evidence["candidate_components"] == components
    assert (
        "For required input, approval, and execution-output delivery, identify "
        "the declared producer, consumer, and actual required payload in the "
        "bounded reason. Reconstruct the complete directed route between them "
        "before marking the rule satisfied. Cite the actual "
        "record indexes for every cross-component hop, checking each direction "
        "and payload. Pairwise compatible exchanges do not establish that "
        "complete route. Do not invent a hop from a component responsibility "
        "or reverse an existing edge to complete the route."
    ) in prompt
    assert reviewed == authored["acceptance_criteria"]
    shared = rubric.RUBRIC_CRITERIA["safe_action_boundary"][1]
    delivery = shared[shared.index("For each declared policy or approval gate") :]
    assert delivery in reviewed["safe_action_boundary"]
    assert result["approved"] is not rejected
    assert result["findings"] == (
        [
            {
                "rule_code": "safe_action_boundary",
                "reason": reason,
                "record_indexes": [1, 4],
            }
        ]
        if rejected
        else []
    )
    assert (components, records) == original


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_changed_approval_policy_invalidates_connection_review_identity(
    monkeypatch, maturity
):
    previous = gate.review_identity("connections", maturity)
    component_identity = gate.review_identity("components", maturity)
    original = gate.staged_review_requirements

    def changed_requirements(stage, depth, guarantees=()):
        requirements = original(stage, depth, guarantees)
        if stage == "connections":
            requirements["safe_action_boundary"] += (
                " Changed final-decision release scope."
            )
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", changed_requirements)
    current = gate.review_identity("connections", maturity)
    assert current != previous
    assert gate.review_identity("components", maturity) == component_identity
    with pytest.raises(ValueError, match="policy differs"):
        gate._previous_review_evidence(
            {"stage": "connections", "review_identity": previous},
            gate="connections",
            identity=current,
            rule_codes=(),
            records=[],
            evidence_bundle={},
        )


def test_approval_delivery_connection_release_versions():
    assert generation._CONNECTION_PROMPT_VERSION == "staged_connections_v40"
    assert gate._CONNECTION_GATE_PROMPT_VERSION == "staged_connection_gate_v37"


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_declared_escalation_invalidates_previous_connection_review(monkeypatch, maturity):
    current = gate.review_identity("connections", maturity)
    component_identity = gate.review_identity("components", maturity)
    original = gate.staged_review_requirements
    escalation = rubric.RUBRIC_CRITERIA["edge_semantics"][1].split(
        "Treat declared escalation as an invoked capability.", 1
    )[1]
    escalation = "Treat declared escalation as an invoked capability." + escalation

    def previous_requirements(stage, depth, guarantees=()):
        requirements = original(stage, depth, guarantees)
        if stage == "connections":
            assert escalation in requirements["edge_semantics"]
            requirements["edge_semantics"] = requirements["edge_semantics"].replace(escalation, "")
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)
    prior = gate.review_identity("connections", maturity)
    assert prior != current
    assert gate.review_identity("components", maturity) == component_identity
    assert tuple(previous_requirements("connections", maturity)) == tuple(
        original("connections", maturity)
    )
    monkeypatch.setattr(gate, "staged_review_requirements", original)
    with pytest.raises(ValueError, match="policy differs"):
        gate._previous_review_evidence(
            {"stage": "connections", "review_identity": prior},
            gate="connections", identity=current, rule_codes=(), records=[], evidence_bundle={},
        )
