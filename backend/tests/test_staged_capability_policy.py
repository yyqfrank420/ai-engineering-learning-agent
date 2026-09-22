import json

import pytest

from agent.architecture_rubric import (
    RUBRIC_CRITERIA,
    STAGED_PRODUCTION_REQUIREMENTS,
    STAGED_REVIEW_STANDARD,
    staged_review_requirements,
)
from agent.nodes import staged_graph_gate as gate
from agent.nodes import staged_graph_generation as generation
from agent.staged_graph_contract import production_proofs_for_capabilities


_PREVIOUS_CAPABILITY_CRITERION = (
    "Classify capabilities from the candidate responsibilities and assumptions: "
    "external_effects means it can mutate an external system; retrieval_or_reuse "
    "means it retrieves or reuses stored artifacts; learning_or_release means "
    "feedback can change a model, prompt, ranking, or live configuration."
)

_PREVIOUS_REUSE_CRITERION = (
    "Store only accepted post-gate artifacts, or route cache, replay, retry, and "
    "shortcut paths back through the required gate with identity and version scope."
)


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_capability_policy_checks_each_owned_effect_in_one_review(maturity):
    criterion = staged_review_requirements("components", maturity)[
        "capability_classification"
    ]

    assert criterion.startswith(_PREVIOUS_CAPABILITY_CRITERION)
    assert (
        "Check each flag independently against named component responsibilities "
        "and assumptions, and report every unsupported flag in the same review."
    ) in criterion
    assert (
        "Internal dataset curation or publication and a passive downstream consumer "
        "alone do not imply external_effects or learning_or_release."
    ) in criterion
    assert (
        "Require an owner in this system for the external write or the feedback-driven "
        "change to a model, prompt, ranking, or live configuration, respectively."
    ) in criterion


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_generation_and_gate_receive_shared_capability_policy(maturity):
    request = (
        "Draw a closed-loop evaluation system from raw feedback through validation, "
        "scoring, review, and dataset updates."
    )
    generated_prompt, _ = generation._attempt_prompt(
        stage="components",
        request=request,
        resolved_maturity=maturity,
        write_set=generation.create_write_set(component_limit=16, edge_limit=24),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        architecture_context="Evaluation data ownership and provenance.",
    )
    reviewed_prompt = gate._prompt(
        gate="components",
        user_request=request,
        evidence_bundle={},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=(),
    )
    generated_criteria = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])[
        "acceptance_criteria"
    ]
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )

    assert generated_criteria == reviewed_criteria
    assert STAGED_REVIEW_STANDARD in generated_prompt
    assert STAGED_REVIEW_STANDARD in gate._GATE_SYSTEM
    assert generated_criteria == staged_review_requirements("components", maturity)
    assert generated_criteria["capability_classification"] != (
        _PREVIOUS_CAPABILITY_CRITERION
    )
    assert {"domain_specificity", "succinctness", "selected_depth"}.isdisjoint(
        generated_criteria
    )
    assert {"objective_fidelity", "brief_coverage", "mece_scope"} <= set(
        generated_criteria
    )
    schema = gate._response_schema(rule_codes=tuple(reviewed_criteria))
    codes = schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
        "enum"
    ]
    assert {"domain_specificity", "succinctness", "selected_depth"}.isdisjoint(codes)


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_presentation_policy_invalidates_previous_component_review(
    monkeypatch, maturity
):
    current_identity = gate.review_identity("components", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "components":
            for code in ("domain_specificity", "succinctness"):
                requirements[code] = RUBRIC_CRITERIA[code][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    assert gate.review_identity("components", maturity) != current_identity


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_presentation_policy_preserves_graph_correctness_rules(maturity):
    requirements = staged_review_requirements("connections", maturity)

    assert {
        "runtime_completeness",
        "edge_semantics",
        "safe_action_boundary",
        "gate_preserving_reuse",
    } <= set(requirements)


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_edge_policy_keeps_required_returns_and_controls_blocking(maturity):
    criterion = staged_review_requirements("connections", maturity)["edge_semantics"]

    for obligation in (
        "compatible with their source, recipient, payload, and declared behavior",
        "Block a missing required input or answer return",
        "a contradictory direction",
        "a path that bypasses a required control",
        "An unrelated verdict or acknowledgment cannot replace required data",
        "Feedback and deployment contracts cannot substitute for required runtime or control",
    ):
        assert obligation in criterion
    assert (
        "A redundant intermediate return or duplicate description is advisory unless "
        "it changes execution or violates a required control"
    ) in criterion
    assert "identify that concrete failure when rejecting" in criterion
    assert RUBRIC_CRITERIA["edge_semantics"] == (
        "connections",
        "Give each directed edge one distinct necessary contract, consolidate duplicate "
        "interactions, and keep reverse or parallel contracts compatible. Classify each "
        "interaction by its actual behavior; feedback and deployment contracts cannot "
        "substitute for required runtime or control interactions. Each read or request "
        "that expects returned data needs its matching payload from the authoritative "
        "owner back to the requester. An unrelated reverse verdict or acknowledgment "
        "does not supply that payload.",
    )


def test_prototype_action_policy_preserves_required_controls_without_extra_stages():
    criterion = staged_review_requirements("connections", "prototype")[
        "safe_action_boundary"
    ]

    for obligation in (
        "Preserve every explicitly requested approval, audit, recovery, or other action control",
        "concrete declared external mutation",
        "appropriate authorization before the action",
        "visible failure or denial handling",
        "An existing owner may apply a lightweight guardrail before dispatch",
        "Generic educational tool or environment labels, code execution, or an external_effects flag alone",
        "Read-only tool calls and internal memory operations do not require a new approval stage unless explicitly requested",
        "Identify the concrete mutation or requested control when rejecting",
    ):
        assert obligation in criterion


def test_production_and_legacy_action_policy_retain_exact_controls():
    criterion = "Put policy, exact-action approval, audit, and recovery controls on external mutations."

    assert RUBRIC_CRITERIA["safe_action_boundary"][1] == criterion
    assert (
        staged_review_requirements("connections", "production")["safe_action_boundary"]
        == criterion
    )


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_prototype_action_policy_invalidates_only_prototype_connection_review(
    monkeypatch, maturity
):
    current_identity = gate.review_identity("connections", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "connections":
            requirements["safe_action_boundary"] = RUBRIC_CRITERIA[
                "safe_action_boundary"
            ][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    previous_identity = gate.review_identity("connections", maturity)
    assert (previous_identity != current_identity) == (maturity == "prototype")


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_capability_clarification_invalidates_prior_review_identity(
    monkeypatch, maturity
):
    current_identity = gate.review_identity("components", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "components":
            requirements["capability_classification"] = _PREVIOUS_CAPABILITY_CRITERION
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    assert gate.review_identity("components", maturity) != current_identity


def test_production_review_consolidates_obligations_without_losing_failure_outcomes():
    requirements = staged_review_requirements(
        "connections",
        "production",
        ("state_effect_reconciliation", "retrieval_and_reuse_trust"),
    )

    assert "complete_reconciliation" not in requirements
    assert "safe_factual_failure" not in requirements
    assert "controlled_learning_and_release" not in requirements
    assert "learning_and_release" not in requirements
    reconciliation = requirements["state_effect_reconciliation"]
    for obligation in (
        "COMMITTED",
        "NOT_FOUND",
        "STILL_UNKNOWN",
        "same-key",
        "bounded",
    ):
        assert obligation in reconciliation
    retrieval = requirements["retrieval_and_reuse_trust"]
    for obligation in ("rejected/stale", "abstention", "invalidation", "entailment"):
        assert obligation in retrieval


def test_production_contracts_allow_internal_ownership_without_extra_graph_edges():
    requirements = staged_review_requirements("connections", "production")

    assert "between components" in requirements["topology_enforced_guarantees"]
    assert "required interaction" in requirements["topology_enforced_guarantees"]
    assert "state_order_integrity" not in requirements
    component_requirements = staged_review_requirements("components", "production")
    assert set(STAGED_PRODUCTION_REQUIREMENTS).isdisjoint(component_requirements)
    assert (
        requirements["state_effect_reconciliation"]
        == (STAGED_PRODUCTION_REQUIREMENTS["state_effect_reconciliation"])
    )
    assert "streaming_integrity" not in requirements


def test_streaming_controls_require_declared_continuous_or_unbounded_delivery():
    streaming = STAGED_PRODUCTION_REQUIREMENTS["streaming_integrity"]

    assert (
        "request or candidate contracts declare continuous or unbounded delivery"
        in streaming
    )
    assert (
        "Determine applicability from declared delivery behavior and completion boundaries"
        in streaming
    )
    assert (
        "Near-real-time timing, asynchronous transport, generic event ingestion, "
        "or the word 'stream' alone does not establish continuous streaming"
    ) in streaming
    assert "Cite the behavior that makes these controls necessary" in streaming
    for control in (
        "bounded backpressure",
        "ordering or event-time rules",
        "replay and deduplication",
        "late-data handling",
        "schema compatibility",
    ):
        assert control in streaming


def test_internal_dataset_writes_keep_idempotence_and_ambiguous_commit_review():
    requirements = staged_review_requirements(
        "connections",
        "production",
        ("audit_and_provenance", "retrieval_and_reuse_trust"),
    )

    assert "authorization_and_compensation" not in requirements
    reconciliation = requirements["state_effect_reconciliation"]
    for obligation in (
        "internal durable mutations",
        "deduplicate atomically",
        "same-key",
        "freshness",
        "fencing before execution",
    ):
        assert obligation in reconciliation


def test_reuse_control_details_remain_in_connection_review():
    components = staged_review_requirements("components", "production")
    connections = staged_review_requirements(
        "connections", "production", ("retrieval_and_reuse_trust",)
    )
    assert "retrieval_and_reuse_trust" not in components
    trust = connections["retrieval_and_reuse_trust"]
    for obligation in (
        "name invalidation and revalidation ownership",
        "Discard rejected/stale artifacts",
        "Failed required factual retrieval must end in clarification, abstention, "
        "or a bounded validated retry",
        "identity, version, and provenance",
        "Shortcuts cannot bypass these controls",
    ):
        assert obligation in trust


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_component_depth_removal_invalidates_only_component_approval(
    monkeypatch,
    maturity,
):
    guarantees = (
        ("audit_and_provenance", "retrieval_and_reuse_trust")
        if maturity == "production"
        else ()
    )
    component_identity = gate.review_identity("components", maturity)
    connection_identity = gate.review_identity("connections", maturity, guarantees)

    def previous_depth_requirements(stage, depth, required=()):
        requirements = staged_review_requirements(stage, depth, required)
        if stage == "components":
            requirements["selected_depth"] = RUBRIC_CRITERIA["selected_depth"][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_depth_requirements)

    assert gate.review_identity("components", maturity) != component_identity
    assert (
        gate.review_identity("connections", maturity, guarantees) == connection_identity
    )


@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.parametrize("required_gate", [False, True])
def test_memory_generation_and_review_share_conditional_gate_preservation(
    maturity, required_gate
):
    request = "Draw an agent that reads and writes task memory."
    if required_gate:
        request += " Require approval before reusing stored results."
    context = generation.AcceptedContext(
        assumptions=(request,),
        external_effects=False,
        retrieval_or_reuse=True,
        learning_or_release=False,
    )
    guarantees = production_proofs_for_capabilities(
        context.prompt_value()["capabilities"], maturity=maturity
    )
    generated_prompt, _ = generation._attempt_prompt(
        stage="connections",
        request=request,
        resolved_maturity=maturity,
        write_set=generation.create_write_set(component_limit=2, edge_limit=4),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        accepted_context=context,
    )
    reviewed_prompt = gate._prompt(
        gate="connections",
        user_request=request,
        evidence_bundle={"candidate_context": context.prompt_value()},
        resolved_maturity=maturity,
        candidate_records=[],
        required_production_guarantees=guarantees,
    )
    generated_input = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )

    assert generated_input["request"] == request
    assert generated_input["accepted_context"] == context.prompt_value()
    assert generated_input["acceptance_criteria"] == reviewed_criteria
    assert (
        reviewed_criteria["safe_action_boundary"]
        == staged_review_requirements("connections", maturity, guarantees)[
            "safe_action_boundary"
        ]
    )
    criterion = reviewed_criteria["gate_preserving_reuse"]
    assert (
        "required by the request, accepted responsibilities, or applicable maturity"
        in criterion
    )
    assert "cannot bypass those gates" in criterion
    assert "rejoin the required gate with its identity and version scope" in criterion
    assert (
        "Prototype memory or reuse alone does not require a new approval or version gate"
        in criterion
    )
    if maturity == "prototype":
        assert "retrieval_and_reuse_trust" not in reviewed_criteria
    else:
        trust = reviewed_criteria["retrieval_and_reuse_trust"]
        for obligation in (
            "entailment",
            "identity, version, and provenance",
            "invalidation",
            "Failed required factual retrieval",
            "Discard rejected/stale artifacts",
            "candidate explicitly makes example or creative reuse optional",
            "fresh generation through the same validation and approval controls",
            "Do not infer optionality or allow unsupported facts",
        ):
            assert obligation in trust


@pytest.mark.parametrize(
    "rule_code",
    ["audit_and_provenance", "retrieval_and_reuse_trust"],
)
def test_production_control_change_invalidates_saved_connection_approval(
    monkeypatch, rule_code
):
    guarantees = (rule_code,)
    current = gate.review_identity("connections", "production", guarantees)

    def changed_requirements(stage, depth, required=()):
        requirements = staged_review_requirements(stage, depth, required)
        if rule_code in requirements:
            requirements[rule_code] = "Previous control requirement"
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", changed_requirements)

    assert gate.review_identity("connections", "production", guarantees) != current


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_reuse_clarification_invalidates_prior_connection_review(monkeypatch, maturity):
    current_identity = gate.review_identity("connections", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "connections":
            requirements["gate_preserving_reuse"] = _PREVIOUS_REUSE_CRITERION
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    assert gate.review_identity("connections", maturity) != current_identity


@pytest.mark.parametrize("maturity", ["prototype", "production"])
@pytest.mark.parametrize("stage", ["components", "connections"])
def test_streaming_guidance_is_absent_from_staged_blocking_schema(stage, maturity):
    guarantees = production_proofs_for_capabilities(
        {
            "external_effects": True,
            "retrieval_or_reuse": True,
            "learning_or_release": True,
        },
        maturity=maturity,
    )
    requirements = staged_review_requirements(stage, maturity, guarantees)
    schema = gate._response_schema(rule_codes=tuple(requirements))
    codes = schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
        "enum"
    ]

    assert "streaming_integrity" not in requirements
    assert "streaming_integrity" not in codes
    assert RUBRIC_CRITERIA["streaming_integrity"] == (
        "connections",
        "For continuous streams, define bounded backpressure, ordering or event-time rules, "
        "replay and deduplication ownership, late-data handling, and compatible schema evolution.",
    )
    assert (
        "bounded backpressure" in STAGED_PRODUCTION_REQUIREMENTS["streaming_integrity"]
    )


def test_removing_streaming_blocker_invalidates_previous_connection_approval(
    monkeypatch,
):
    current = gate.review_identity("connections", "production")

    def previous_requirements(stage, depth, required=()):
        requirements = staged_review_requirements(stage, depth, required)
        if stage == "connections" and depth == "production":
            requirements["streaming_integrity"] = STAGED_PRODUCTION_REQUIREMENTS[
                "streaming_integrity"
            ]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)
    assert gate.review_identity("connections", "production") != current


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_edge_policy_invalidates_legacy_connection_approval(
    monkeypatch, maturity
):
    current = gate.review_identity("connections", maturity)

    def previous_requirements(stage, depth, required=()):
        requirements = staged_review_requirements(stage, depth, required)
        if stage == "connections":
            requirements["edge_semantics"] = RUBRIC_CRITERIA["edge_semantics"][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)
    assert gate.review_identity("connections", maturity) != current
