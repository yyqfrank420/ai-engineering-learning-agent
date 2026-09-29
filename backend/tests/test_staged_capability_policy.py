import json
from pathlib import Path

import pytest

from agent.architecture_rubric import (
    RUBRIC_CRITERIA,
    STAGED_PRODUCTION_REQUIREMENTS,
    STAGED_REVIEW_STANDARD,
    TOPOLOGY_PROOF_REQUIREMENTS,
    staged_review_requirements,
)
from agent.nodes import staged_graph_gate as gate
from agent.nodes import staged_graph_generation as generation
from agent.staged_graph_contract import production_proofs_for_capabilities


def test_production_component_coverage_checks_owners_before_connections():
    criterion = staged_review_requirements("components", "production")["brief_coverage"]
    assert "declared behavior and responsibilities" in criterion
    assert "including when a capability flag needs correction" in criterion
    assert "storage of evidence alone does not own evaluation or approval" in criterion
    assert "Report all missing or incompatible owners in this pass" in criterion
    assert "affected component indexes" in criterion
    assert "Compatible operations may share an existing owner" in criterion
    assert "do not require separate components" in criterion
    assert "not edges, sequence, or payload proofs" in criterion
    assert "Do not introduce capabilities or features" in criterion
    assert "frozen baseline responsibilities grants no authority to change them" in criterion
    assert staged_review_requirements("components", "prototype")["brief_coverage"] == (
        RUBRIC_CRITERIA["brief_coverage"][1]
    )
    assert "brief_coverage" not in staged_review_requirements("connections", "production")


@pytest.mark.parametrize("declares_release", [False, True])
def test_component_owner_guidance_does_not_depend_on_correct_capability_flags(declares_release):
    records = [
        {"label": "Rollout Manager", "responsibility": "Owns model canary, promotion and rollback."},
        {"label": "Telemetry Store", "responsibility": "Stores serving logs and rollout outcomes."},
    ]
    evidence = {"candidate_context": {"capabilities": {
        "external_effects": False, "retrieval_or_reuse": False,
        "learning_or_release": declares_release,
    }}}
    prompt = gate._prompt(
        gate="components", user_request="Design production model serving.",
        evidence_bundle=evidence, resolved_maturity="production",
        candidate_records=records, required_production_guarantees=(),
    )
    controls = json.loads(prompt.split("downstream_controls: ", 1)[1].split("\n", 1)[0])
    assert controls == STAGED_PRODUCTION_REQUIREMENTS
    assert "reviewed immutable release" in controls["learning_and_release"]
    assert "including when a capability flag needs correction" in prompt
    assert json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0]) == evidence


_PREVIOUS_CAPABILITY_CRITERION = (
    "Classify capabilities from the candidate responsibilities and assumptions: "
    "external_effects means it can mutate an external system; retrieval_or_reuse "
    "means it retrieves or reuses stored artifacts; learning_or_release means "
    "feedback can change a model, prompt, ranking, or live configuration. "
    "Check each flag independently against named component responsibilities "
    "and assumptions, and report every unsupported flag in the same review. "
    "Internal dataset curation or publication and a passive downstream consumer "
    "alone do not imply external_effects or learning_or_release. Require an "
    "owner in this system for the external write or the feedback-driven change "
    "to a model, prompt, ranking, or live configuration, respectively."
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

    assert criterion != _PREVIOUS_CAPABILITY_CRITERION
    assert (
        "Check each flag independently against named component responsibilities "
        "and assumptions, and report every unsupported flag in the same review."
    ) in criterion
    assert (
        "Internal dataset curation or publication and a passive downstream consumer "
        "alone do not imply external_effects or learning_or_release."
    ) in criterion
    assert (
        "Require an owner in this system for the external write or the update or "
        "release, respectively."
    ) in criterion


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_external_effect_classification_requires_an_owned_external_write(maturity):
    criterion = staged_review_requirements("components", maturity)[
        "capability_classification"
    ]
    for obligation in (
        "external_effects means a component owns a declared write to state in an external system",
        "Classify the behavior represented by the diagram",
        "Topic names, recommendations, drafts, internal bookkeeping, and read-only provider calls do not establish an external write",
        "When rejecting external_effects=false, cite the responsible component, its mutation, and the external target",
        "Do not invent an external system or write from an ambiguous description",
        "An explicitly owned external write requires external_effects=true and its applicable controls, including when a human approves the write",
    ):
        assert obligation in criterion


@pytest.mark.parametrize(
    "responsibility,external_effects",
    [
        ("Recommends scheduling and resource allocation options for administrators.", False),
        ("Drafts enrollment plans and records internal review decisions.", False),
        ("Reads a provider API to explain administrative task automation.", False),
        ("Writes human-approved schedules to an external calendar service.", True),
        ("Commits enrollment changes to the external registrar system.", True),
    ],
)
@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_external_write_review_inputs_preserve_applicable_controls(
    responsibility, external_effects, maturity
):
    # These fixtures verify prompt inputs and control applicability, not model judgments.
    records = [{"id": "owner", "responsibility": responsibility}]
    context = generation.AcceptedContext(
        assumptions=(), external_effects=external_effects,
        retrieval_or_reuse=False, learning_or_release=False,
    )
    prompt = gate._prompt(
        gate="components", user_request="Explain this system's responsibilities.",
        evidence_bundle={"candidate_context": context.prompt_value()},
        resolved_maturity=maturity, candidate_records=records,
        required_production_guarantees=(),
    )
    evidence = json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0])
    candidate = json.loads(
        prompt.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0]
    )
    assert evidence["candidate_context"] == context.prompt_value()
    assert candidate == [{"record_index": 0, "record": records[0]}]
    guarantees = production_proofs_for_capabilities(
        context.prompt_value()["capabilities"], maturity=maturity,
    )
    for code in ("authorization_and_compensation", "state_effect_reconciliation"):
        assert (code in guarantees) == (maturity == "production" and external_effects)
    if maturity == "prototype":
        criterion = staged_review_requirements("connections", maturity)["safe_action_boundary"]
        assert "For a concrete declared external mutation, require appropriate authorization" in criterion


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_learning_capability_includes_owned_offline_and_reviewed_changes(maturity):
    criterion = staged_review_requirements("components", maturity)[
        "capability_classification"
    ]
    for obligation in (
        "this system owns an update or release of a model, prompt, ranking, or live configuration",
        "Offline or batch training and human-approved updates or releases count",
        "automatic feedback and immediate live deployment are not required",
        "A no-automatic-loop assumption does not negate an explicitly owned update or release",
        "Frozen inference without an owned update or release does not imply learning_or_release",
    ):
        assert obligation in criterion


# These cases preserve review inputs and downstream obligations. They do not
# assert that an uncalled model has classified the responsibilities correctly.
@pytest.mark.parametrize(
    "responsibility,assumption,learning_or_release",
    [
        pytest.param(
            "Owns offline fine-tuning of a model on reviewed examples and versions the trained weights.",
            "There is no automatic feedback loop or live deployment.",
            True,
            id="owned-offline-fine-tuning",
        ),
        pytest.param(
            "Curates and publishes versioned datasets for a passive downstream consumer.",
            "Training and model release are owned outside this system.",
            False,
            id="passive-dataset-curation",
        ),
        pytest.param(
            "Serves predictions using a frozen model and records request outcomes.",
            "This system neither updates nor releases model or prompt versions.",
            False,
            id="frozen-inference",
        ),
        pytest.param(
            "Owns evaluation and release of revised prompt versions after human approval.",
            "An operator approves every batch release; there is no automatic loop.",
            True,
            id="human-approved-prompt-release",
        ),
        pytest.param(
            "Owns evaluation and release of model versions after human approval.",
            "Model release is an offline operation performed on a scheduled batch.",
            True,
            id="human-approved-model-release",
        ),
    ],
)
@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_owned_learning_review_cases_preserve_responsibilities_and_controls(
    responsibility, assumption, learning_or_release, maturity
):
    records = [{"id": "owner", "responsibility": responsibility}]
    context = generation.AcceptedContext(
        assumptions=(assumption,),
        external_effects=False,
        retrieval_or_reuse=True,
        learning_or_release=learning_or_release,
    )
    capabilities = context.prompt_value()["capabilities"]
    guarantees = production_proofs_for_capabilities(capabilities, maturity=maturity)
    prompt = gate._prompt(
        gate="components",
        user_request="Explain this system's owned responsibilities.",
        evidence_bundle={"candidate_context": context.prompt_value()},
        resolved_maturity=maturity,
        candidate_records=records,
        required_production_guarantees=(),
    )
    evidence = json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0])
    candidate = json.loads(
        prompt.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0]
    )
    assert evidence["candidate_context"] == context.prompt_value()
    assert candidate == [{"record_index": 0, "record": records[0]}]
    assert ("learning_and_release" in guarantees) == (
        maturity == "production" and learning_or_release
    )
    if maturity == "production" and learning_or_release:
        requirements = staged_review_requirements("connections", maturity, guarantees)
        assert (
            requirements["learning_and_release"]
            == (STAGED_PRODUCTION_REQUIREMENTS["learning_and_release"])
        )


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
    brief = generated_criteria["brief_coverage"]
    if maturity == "production":
        for obligation in (
            "before component responsibilities freeze",
            "explicitly assign policy checks and the exact-action approval decision",
            "plus applicable recovery ownership",
            "Executing approved calls consumes approval",
            "Structural validation alone does not establish policy or approval ownership",
            "curated versioned evidence including hostile traces",
            "offline evaluation", "reviewed immutable release", "canary",
            "promotion", "rollback", "recorded outcomes",
            "Compatible controls may share an existing executable owner",
            "explicitly declared external dependency",
            "metrics-only monitor", "passive artifact store", "word 'reviewed' alone",
            "do not require edges or transition proof",
            "Frozen inference without an owned update or release",
            "For every producer of model-proposed actions",
            "deterministic validation of proposal structure and allowed constraints",
            "independently of external_effects and learning_or_release",
            "model-selected read-only tools, internal tools, and code execution",
            "compatible existing owner may perform this validation internally",
            "without requiring edges or transition proof",
            "Answer-only inference without model-proposed actions does not require this per-action validation",
        ):
            assert obligation in brief
    else:
        assert brief == RUBRIC_CRITERIA["brief_coverage"][1]
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
    schema = gate._response_schema(rule_codes=tuple(reviewed_criteria), record_count=0)
    codes = schema["properties"]["rule_reviews"]["items"]["properties"]["rule_code"][
        "enum"
    ]
    assert {"domain_specificity", "succinctness", "selected_depth"}.isdisjoint(codes)
    generated_input = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])
    if maturity == "production":
        assert (
            generated_input["downstream_controls"]["authorization_and_compensation"]
            == STAGED_PRODUCTION_REQUIREMENTS["authorization_and_compensation"]
        )
    else:
        assert "downstream_controls" not in generated_input


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
def test_staged_mece_blocks_material_conflicts_without_requiring_extra_boxes(maturity):
    requirements = staged_review_requirements("components", maturity)
    criterion = requirements["mece_scope"]

    assert "Block conflicting material ownership" in criterion
    assert "required behavior or controls ambiguous" in criterion
    assert "outside the requested subject scope" in criterion
    assert (
        "Redundant decomposition, compatible shared ownership, and naming preferences are advisory"
        in criterion
    )
    assert "concrete behavior or control harm" in criterion
    assert "brief_coverage" in requirements
    assert "objective_fidelity" in requirements
    assert criterion != RUBRIC_CRITERIA["mece_scope"][1]


def test_production_branch_policy_keeps_required_outcomes_and_controls():
    requirements = staged_review_requirements(
        "connections", "production", tuple(TOPOLOGY_PROOF_REQUIREMENTS)
    )
    criterion = requirements["branch_completion"]

    for obligation in (
        "required or declared normal, denial, failure, alternate, and fallback path",
        "typed response carrying the applicable outcomes",
        "same executable owner handling them",
        "without a separate component or edge",
        "optional exception that the request and accepted design do not declare",
        "Block a missing required path",
        "bypasses a required control",
    ):
        assert obligation in criterion
    assert "branch_completion" not in staged_review_requirements(
        "connections", "prototype"
    )
    assert {
        "runtime_completeness",
        "edge_semantics",
        "safe_action_boundary",
        "gate_preserving_reuse",
        "topology_enforced_guarantees",
        "state_effect_reconciliation",
        *TOPOLOGY_PROOF_REQUIREMENTS,
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
        "Before pairing, identify the consumer needing each payload",
        "producing or storing it",
        "the consumer requests the payload and the owner returns it",
        "receiving a request does not give a consumer authority to produce owner-held records",
        "An authoritative owner may deliver directly to multiple compatible consumers",
        "Missing peer names in high-level responsibilities alone do not establish a contradiction",
        "do not invent a mandatory intermediary or relax a declared trust boundary",
        "Feedback and deployment contracts cannot substitute for required runtime or control",
    ):
        assert obligation in criterion
    assert (
        "A redundant intermediate return or duplicate description is advisory unless "
        "it changes execution or violates a required control"
    ) in criterion
    assert "identify that concrete failure when rejecting" in criterion
    reviewed_prompt = gate._prompt(
        gate="connections", user_request="Show evidence delivery",
        evidence_bundle={}, resolved_maturity=maturity, candidate_records=[],
        required_production_guarantees=(),
    )
    reviewed = json.loads(reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0])
    assert reviewed["edge_semantics"] == criterion
    for obligation in (
        "An intermediary may forward already received data without owning its original authority",
        "compatible relay contracts can establish forwarding",
        "does not authorize a consumer to create a policy or approval decision",
        "substitute generated citations for canonical source data",
        "Block an absent producer or delivery path",
    ):
        assert obligation in criterion
        assert obligation in reviewed_prompt
    assert RUBRIC_CRITERIA["edge_semantics"] == (
        "connections",
        "For topic, mechanism, and lifecycle maps, use truthful causal, adaptation, "
        "or lifecycle relationships without inventing requests or replies between abstract topics. "
        "Give each directed edge one distinct necessary contract, consolidate duplicate "
        "interactions, and keep reverse or parallel contracts compatible. Classify each "
        "interaction by its actual behavior; feedback and deployment contracts cannot "
        "substitute for required runtime or control interactions. Each read or request "
        "that expects returned data needs its matching payload from the authoritative "
        "owner back to the requester. An unrelated reverse verdict or acknowledgment "
        "does not supply that payload. Check both directions against declared data and "
        "decision ownership. Data payloads and policy or approval results must originate "
        "at their authoritative owner; pairing cannot assign that authority to a consumer.",
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
    connection_identity = gate.review_identity("connections", maturity)

    def previous_requirements(stage, depth, guarantees=()):
        requirements = staged_review_requirements(stage, depth, guarantees)
        if stage == "components":
            requirements["capability_classification"] = _PREVIOUS_CAPABILITY_CRITERION
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)

    assert gate.review_identity("components", maturity) != current_identity
    assert gate.review_identity("connections", maturity) == connection_identity


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
    for obligation in ("rejected/stale", "abstention", "entailment"):
        assert obligation in retrieval
    assert "invalidation" in requirements["artifact_reuse_lifecycle"]


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
        "Assess each write separately",
        "atomic durable commit of the effect and same-operation deduplication",
        "safe same-key replay",
        "freshness, fencing",
        "read back authoritative status",
    ):
        assert obligation in reconciliation


def test_reconciliation_scope_requires_evidence_for_each_write():
    criterion = staged_review_requirements("connections", "production")[
        "state_effect_reconciliation"
    ]

    assert criterion == STAGED_PRODUCTION_REQUIREMENTS["state_effect_reconciliation"]
    for scope in (
        "Assess each write separately",
        "declared retry, redelivery, competing delivery, or uncertain-commit recovery",
        "A datastore or committed/rejected reply alone does not declare retries",
        "Missing implementation detail is advisory unless it contradicts an explicitly requested guarantee or establishes unsafe behavior",
    ):
        assert scope in criterion
    for control in (
        "atomic durable commit of the effect and same-operation deduplication with safe same-key replay",
        "separate pre-effect reservation and read-back are unnecessary within that boundary",
        "A key alone proves neither atomicity nor safe replay",
        "Effects outside that atomic boundary require durable identity and safe target-side idempotency or reconciliation before retry",
        "For uncertain non-idempotent effects, reserve identity durably before execution",
        "authorization, policy, freshness, fencing",
        "atomic writer deduplication across delivery paths",
        "COMMITTED records success",
        "NOT_FOUND permits safe same-key retry",
        "STILL_UNKNOWN has bounded escalation",
        "bounded compensation for late anomalies",
    ):
        assert control in criterion


def test_shared_compensation_contracts_preserve_the_complete_control_path():
    criterion = staged_review_requirements(
        "connections", "production", ("authorization_and_compensation",)
    )["authorization_and_compensation"]

    assert criterion == STAGED_PRODUCTION_REQUIREMENTS["authorization_and_compensation"]
    assert "request or an explicitly required recovery guarantee" in criterion
    assert "External effects alone do not require compensation behavior" in criterion
    assert "only when required or declared" in criterion
    assert (
        "it must use the same policy, approval, execution, reconciliation, "
        "and audit controls"
    ) in criterion
    for obligation in (
        "each external effect executor, trace the exact approved action payload",
        "stable operation identity from canonical proposal or operation ownership",
        "an executor pull with its authoritative reply",
        "declared same-owner state can supply them",
        "executor may reserve the identity durably with canonical state",
        "authorization verdict or incidental reachability alone supplies neither",
    ):
        assert obligation in criterion
    assert (
        "For applicable compensation, cover it explicitly in the existing validation and approval "
        "invocation and response contracts"
    ) in criterion
    assert (
        "Shared controls suffice when those contracts cover both normal and "
        "compensation actions; duplicate control paths are unnecessary"
    ) in criterion
    for obligation in (
        "Review normal and compensation behavior separately even when one component",
        "its normal input does not establish rollback initiation",
        "initiating operator, incident, event, or explicit autonomous responsibility",
        "original or applied operation reference or recovery input to its proposal producer",
        "Direct, delegated, combined, or declared same-owner internal paths are valid",
        "do not demand duplicate services or edges or an incoming edge for an explicit autonomous action",
    ):
        assert obligation in criterion
    assert (
        "Identify the compensation proposal's producer and follow its direct or "
        "delegated invocation to each shared control"
    ) in criterion
    assert (
        "A validator's broad responsibility or another producer's validation path "
        "does not establish that invocation"
    ) in criterion
    reviewed_prompt = gate._prompt(
        gate="connections",
        user_request="Design human-approved ad changes and rollback.",
        evidence_bundle={},
        resolved_maturity="production",
        candidate_records=[],
        required_production_guarantees=("authorization_and_compensation",),
    )
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )
    assert reviewed_criteria["authorization_and_compensation"] == criterion


def test_shared_owner_initiation_reaches_connection_author_and_gate():
    context = generation.AcceptedContext(
        assumptions=("A human operator may request rollback of an applied change.",),
        external_effects=True,
        retrieval_or_reuse=False,
        learning_or_release=False,
    )
    request = "Draw an approval-based campaign workflow with rollback."
    generated_prompt, _ = generation._attempt_prompt(
        stage="connections",
        request=request,
        resolved_maturity="production",
        write_set=generation.create_write_set(component_limit=4, edge_limit=8),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        accepted_components=[
            {
                "index": 0,
                "label": "Shared proposal service",
                "type": 101,
                "responsibility": "Produces normal and rollback proposals.",
                "primary_flow_member": True,
                "is_root": True,
            }
        ],
        accepted_context=context,
    )
    guarantees = production_proofs_for_capabilities(
        context.prompt_value()["capabilities"], maturity="production"
    )
    reviewed_prompt = gate._prompt(
        gate="connections",
        user_request=request,
        evidence_bundle={"candidate_context": context.prompt_value()},
        resolved_maturity="production",
        candidate_records=[],
        required_production_guarantees=guarantees,
    )
    generated_input = json.loads(generated_prompt.split("\nINPUT\n", 1)[1])
    reviewed_criteria = json.loads(
        reviewed_prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0]
    )

    assert "authorization_and_compensation" in guarantees
    assert generated_input["acceptance_criteria"] == reviewed_criteria
    assert (
        reviewed_criteria["authorization_and_compensation"]
        == (STAGED_PRODUCTION_REQUIREMENTS["authorization_and_compensation"])
    )
    assert "normal input does not initiate rollback" in generated_prompt
    assert "normal input does not initiate rollback" in reviewed_prompt
    assert (
        "exact approved action payload and stable operation identity"
        in generated_prompt
    )
    assert (
        "exact approved action payload and stable operation identity" in reviewed_prompt
    )
    assert "declared metric pull with reply is a valid normal input" in generated_prompt
    assert "declared metric pull with reply is a valid normal input" in reviewed_prompt
    assert (
        "An authorization verdict or incidental reachability alone" in generated_prompt
    )
    assert "An authorization verdict or incidental" in reviewed_prompt


def test_captured_shared_producer_gap_records_engineering_review_evidence():
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "marketing_shared_proposal_rollback_gap.json"
        ).read_text()
    )
    graph = fixture["graph_data"]
    contract = fixture["graph_contract"]
    producer = next(node for node in graph["nodes"] if node["id"] == "n4")
    inbound = [edge for edge in graph["edges"] if edge["target"] == "n4"]

    assert fixture["capture"]["source_edge_count"] == len(graph["edges"]) == 34
    assert contract["maturity"] == "production"
    assert contract["capabilities"]["external_effects"] is True
    assert contract["component_gate"]["approved"] is True
    assert contract["connection_gate"]["approved"] is True
    assert "rollback compensation proposals" in producer["description"]
    assert any("does not act autonomously" in row for row in graph["assumptions"])
    assert {(edge["source"], edge["label"]) for edge in inbound} == {
        ("n2", "Trigger proposal generation for stored snapshot version"),
        (
            "n3",
            "Validated snapshot with provenance, or miss or stale artifact discarded in abstention",
        ),
        (
            "n5",
            "Valid: eligible for approval; invalid: rejected with constraint violations",
        ),
    }
    assert fixture["engineering_annotation"]["finding"] == (
        "missing_shared_owner_compensation_initiation"
    )
    assert fixture["engineering_annotation"]["review_origin"] == (
        "assistant_engineering_review_not_model_gate"
    )
    assert fixture["engineering_annotation"]["non_findings"] == [
        "human approval ownership",
        "primary walkthrough order",
    ]


def test_captured_executor_input_gap_separates_metric_pull_from_effect_payload():
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "marketing_executor_input_gap.json"
        ).read_text()
    )
    graph = fixture["graph_data"]
    contract = fixture["graph_contract"]
    edges = graph["edges"]
    executor_inbound = [edge for edge in edges if edge["target"] == "n8"]
    proposal_inputs = [edge for edge in edges if edge["target"] == "n4"]
    reconciliation_outbound = [edge for edge in edges if edge["source"] == "n9"]

    assert set(fixture) == {
        "capture",
        "graph_data",
        "graph_contract",
        "engineering_annotation",
    }
    assert fixture["capture"]["source_edge_count"] == len(edges) == 37
    assert contract["maturity"] == "production"
    assert contract["capabilities"]["external_effects"] is True
    assert contract["component_gate"]["approved"] is True
    assert contract["connection_gate"]["approved"] is True
    assert {(edge["source"], edge["target"]) for edge in proposal_inputs} >= {
        ("n3", "n4"),
        ("n1", "n4"),
    }
    assert any(
        edge["source"] == "n4"
        and edge["target"] == "n3"
        and "Read scoped snapshots" in edge["label"]
        for edge in edges
    )
    assert {(edge["source"], edge["target"]) for edge in executor_inbound} == {
        ("n6", "n8"),
        ("n9", "n8"),
        ("n11", "n8"),
    }
    assert any(
        edge["source"] == "n6" and edge["label"].startswith("Authorized: execute")
        for edge in executor_inbound
    )
    assert any(
        edge["source"] == "n9" and "same-key retry" in edge["label"]
        for edge in executor_inbound
    )
    assert any(
        edge["source"] == "n11"
        and edge["label"].startswith("Committed: change applied")
        for edge in executor_inbound
    )
    assert any(
        edge["source"] == "n8"
        and edge["target"] == "n11"
        and "approved exact" in edge["label"]
        for edge in edges
    )
    assert any(
        node["id"] == "n7" and "Authoritative owner" in node["description"]
        for node in graph["nodes"]
    )
    assert any(
        node["id"] == "n9" and "STILL_UNKNOWN triggers" in node["description"]
        for node in graph["nodes"]
    )
    assert not {(edge["target"]) for edge in reconciliation_outbound} & {"n1", "n4"}
    assert fixture["engineering_annotation"]["finding"] == (
        "effect_executor_lacks_approved_payload_and_identity_input"
    )
    assert fixture["engineering_annotation"]["secondary_finding"] == (
        "declared_still_unknown_compensation_lacks_initiation_path"
    )
    assert fixture["engineering_annotation"]["review_origin"] == (
        "assistant_engineering_review_not_model_gate"
    )


def test_reuse_control_details_remain_in_connection_review():
    components = staged_review_requirements("components", "production")
    connections = staged_review_requirements(
        "connections", "production", ("retrieval_and_reuse_trust",)
    )
    assert "retrieval_and_reuse_trust" not in components
    trust = connections["retrieval_and_reuse_trust"]
    for obligation in (
        "Apply each obligation to the declared retrieval or reuse path, its artifact, and its consumer",
        "A system-level retrieval_or_reuse capability does not mean every generator performs factual retrieval",
        "Identify the material factual claim or required factual-retrieval dependency",
        "apply this equally to internal and external sources",
        "Outcome-data reads and reuse for evaluation do not establish a factual-retrieval dependency for an unrelated creative generator",
        "Discard rejected/stale artifacts",
        "Failed required factual retrieval must end in clarification, abstention, "
        "or a bounded validated retry",
    ):
        assert obligation in trust
    lifecycle = connections["artifact_reuse_lifecycle"]
    for obligation in (
        "executable check of access identity and scope",
        "version and provenance",
        "invalidation and revalidation ownership",
        "Shortcuts cannot bypass these controls",
    ):
        assert obligation in lifecycle


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
            "Failed required factual retrieval",
            "Discard rejected/stale artifacts",
            "candidate explicitly makes example or creative reuse optional",
            "fresh generation through the same validation and approval controls",
            "Do not infer optionality or allow unsupported facts",
        ):
            assert obligation in trust


@pytest.mark.parametrize(
    "rule_code",
    [
        "audit_and_provenance",
        "retrieval_and_reuse_trust",
        "artifact_reuse_lifecycle",
        "state_effect_reconciliation",
        "authorization_and_compensation",
    ],
)
def test_production_control_change_invalidates_saved_connection_approval(
    monkeypatch, rule_code
):
    guarantees = ("retrieval_and_reuse_trust" if rule_code == "artifact_reuse_lifecycle" else rule_code,)
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
    schema = gate._response_schema(rule_codes=tuple(requirements), record_count=0)
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


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("behavior", [
    "An agent calls a generic search tool for optional brainstorming.",
    "A factual RAG answer requires retrieved private evidence.",
    "A private answer cache reuses validated answers across requests.",
])
def test_retrieval_applicability_is_shared_by_generation_and_review(stage, behavior):
    context = generation.AcceptedContext(
        assumptions=(behavior,), external_effects=False,
        retrieval_or_reuse=True, learning_or_release=False,
    )
    guarantees = ("retrieval_and_reuse_trust",)
    prompt, _ = generation._attempt_prompt(
        stage=stage, request=behavior, resolved_maturity="production",
        write_set=generation.create_write_set(component_limit=4, edge_limit=8),
        upstream_fingerprint="a" * 64, attempt=0,
        prior_prompt_fingerprint=None, prior_write_set_fingerprint=None,
        structural_findings=[], gate_findings=[], base=None,
        rejected_candidate=None, accepted_context=context,
        architecture_context=behavior if stage == "components" else None,
    )
    generated = json.loads(prompt.split("\nINPUT\n", 1)[1])
    reviewed = gate._prompt(
        gate=stage, user_request=behavior,
        evidence_bundle={"candidate_context": context.prompt_value()},
        resolved_maturity="production", candidate_records=[],
        required_production_guarantees=guarantees,
    )
    field = "downstream_controls" if stage == "components" else "acceptance_criteria"
    rule = generated[field]["retrieval_and_reuse_trust"]
    assert rule == STAGED_PRODUCTION_REQUIREMENTS["retrieval_and_reuse_trust"]
    assert json.dumps(rule)[1:-1] in reviewed
    for trust_boundary in (
        "The candidate must explicitly declare that its consuming runtime treats retrieved or recalled bytes as untrusted data",
        "Cite a compatible owning responsibility or input contract",
        "Assumptions alone do not establish that runtime behavior",
        "Access, scope, freshness and factual-claim checks do not themselves establish that input trust boundary",
        "The reviewing model's treatment of supplied source evidence does not establish a control in the candidate runtime",
    ):
        assert trust_boundary in rule
    lifecycle = generated[field]["artifact_reuse_lifecycle"]
    assert lifecycle == STAGED_PRODUCTION_REQUIREMENTS["artifact_reuse_lifecycle"]
    assert json.dumps(lifecycle)[1:-1] in reviewed
    for boundary in (
        "Establish applicability separately for each obligation",
        "generic retriever or tool mention does not establish reusable artifacts or a factual-answer dependency",
        "For a declared path that consumes retrieved bytes",
        "Identify the material factual claim or required factual-retrieval dependency",
        "A factual RAG answer activates claim validation",
        "overview label does not exempt declared behavior",
        "fresh generation through the same validation and approval controls",
    ):
        assert boundary in rule

@pytest.mark.parametrize("ownership", ["missing", "internal", "external", "frozen"])
def test_production_release_review_preserves_control_ownership_evidence(ownership):
    # Prompt evidence and criteria are tested here, not an uncalled model's verdict.
    records = [
        {"id": "serving", "responsibility": "Serves the active model version."},
        {"id": "monitor", "responsibility": "Reports latency and quality metrics."},
        {"id": "artifacts", "responsibility": "Stores reviewed model artifacts."},
    ]
    owns_release = ownership != "frozen"
    if owns_release:
        records.append(
            {
                "id": "release",
                "responsibility": "Owns reviewed immutable model release, canary, promotion, rollback, and recorded outcomes.",
            }
        )
    evidence_responsibility = "Curates versioned evidence including hostile traces and performs offline evaluation."
    if ownership == "internal":
        records[-1]["responsibility"] += " " + evidence_responsibility
    elif ownership == "external":
        records.append(
            {
                "id": "evidence",
                "responsibility": "External upstream dependency: "
                + evidence_responsibility,
            }
        )
    context = generation.AcceptedContext(
        assumptions=(
            () if owns_release else ("Frozen inference; no owned update or release.",)
        ),
        external_effects=False,
        retrieval_or_reuse=True,
        learning_or_release=owns_release,
    )
    prompt = gate._prompt(
        gate="components",
        user_request="Design model serving with the declared release scope.",
        evidence_bundle={"candidate_context": context.prompt_value()},
        resolved_maturity="production",
        candidate_records=records,
        required_production_guarantees=(),
    )
    assert json.loads(
        prompt.split("Immutable candidate records: ")[1].split("\n", 1)[0]
    ) == [
        {"record_index": index, "record": record}
        for index, record in enumerate(records)
    ]
    assert json.loads(prompt.split("Evidence bundle: ")[1].split("\n", 1)[0]) == {
        "candidate_context": context.prompt_value()
    }
    criteria = json.loads(prompt.split("Acceptance criteria: ")[1].split("\n", 1)[0])
    assert criteria == staged_review_requirements("components", "production")
    assert "When this system owns an update or release" in criteria["brief_coverage"]
    guarantees = production_proofs_for_capabilities(
        context.prompt_value()["capabilities"], maturity="production"
    )
    assert ("learning_and_release" in guarantees) is owns_release


def test_production_component_ownership_changes_only_component_review_policy(
    monkeypatch,
):
    guarantees = tuple(TOPOLOGY_PROOF_REQUIREMENTS)
    before = {
        (stage, maturity): gate.review_identity(stage, maturity, guarantees)
        for stage in ("components", "connections")
        for maturity in ("prototype", "production")
    }

    def previous_requirements(stage, maturity, required=()):
        requirements = staged_review_requirements(stage, maturity, required)
        if stage == "components":
            requirements["brief_coverage"] = RUBRIC_CRITERIA["brief_coverage"][1]
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)
    for (stage, maturity), identity in before.items():
        assert (gate.review_identity(stage, maturity, guarantees) != identity) is (
            stage == "components" and maturity == "production"
        )
    for maturity in ("prototype", "production"):
        current = staged_review_requirements("connections", maturity, guarantees)
        assert current == previous_requirements("connections", maturity, guarantees)
    assert set(staged_review_requirements("components", "production")) == set(
        staged_review_requirements("components", "prototype")
    )


@pytest.mark.parametrize(
    "evidence_location", ["responsibility", "contract", "vague_label"]
)
def test_shared_validation_review_preserves_owner_and_contract_evidence(
    evidence_location,
):
    from agent.staged_graph_workflow import _decode_connections

    # Synthetic evidence exercises the wire boundary, not semantic model acceptance.
    control = "For planner and recovery proposals, executor deterministically validates proposal structure and allowed constraints before approval or execution."
    components = [
        {"id": "0", "label": "Planner", "responsibility": "Proposes bounded tool calls."},
        {"id": "1", "label": "Recovery", "responsibility": "Proposes recovery tool calls."},
        {"id": "2", "label": "Executor", "responsibility": "Executes accepted bounded tool calls."},
    ]
    wire = {
        "edges": [
            {
                "source_index": index,
                "target_index": 2,
                "label": "Submit proposed tool call",
                "flow": 400,
                "sync": 500,
            }
            for index in (0, 1)
        ]
    }
    if evidence_location == "responsibility":
        components[-1]["responsibility"] += " " + control
    elif evidence_location == "contract":
        for edge, producer in zip(wire["edges"], ("Planner", "Recovery"), strict=True):
            edge["label"] = (
                f"Executor deterministically checks {producer} call schema and allowed tool args before execution"
            )
    else:
        for edge in wire["edges"]:
            edge["label"] = "Validate"
    accepted = [
        {"index": index, **component} for index, component in enumerate(components)
    ]
    parsed = generation._parse_connection_wire(
        json.dumps(wire),
        accepted_components=accepted,
        edge_limit=2,
    )
    assert parsed == wire
    records = [
        {
            "source": edge["source_id"],
            "target": edge["target_id"],
            "label": edge["label"],
            "flow": edge["flow"],
            "sync": edge["sync"],
        }
        for edge in _decode_connections(parsed)
    ]
    assert [record["label"] for record in records] == [
        edge["label"] for edge in wire["edges"]
    ]
    assert all(
        len(record["label"]) <= generation.CONNECTION_LABEL_MAX_CHARS
        for record in records
    )
    prompt = gate._prompt(
        gate="connections",
        user_request="Review the tool execution contracts.",
        evidence_bundle={"candidate_components": components},
        resolved_maturity="production",
        candidate_records=records,
        required_production_guarantees=("audit_and_provenance",),
    )
    assert json.loads(prompt.split("Evidence bundle: ")[1].split("\n", 1)[0]) == {
        "candidate_components": components
    }
    assert json.loads(
        prompt.split("Immutable candidate records: ")[1].split("\n", 1)[0]
    ) == [
        {"record_index": index, "record": record}
        for index, record in enumerate(records)
    ]
    criterion = json.loads(prompt.split("Acceptance criteria: ")[1].split("\n", 1)[0])[
        "audit_and_provenance"
    ]
    assert criterion == STAGED_PRODUCTION_REQUIREMENTS["audit_and_provenance"]
    for obligation in (
        "named compatible owner may perform this deterministic validation internally",
        "responsibility or a connection contract",
        "covered producer, action path, proposal structure and allowed constraints",
        "validation before approval or execution",
        "does not need duplicate wording in the owner's responsibility",
        "vague 'validate' label without an executable owner, deterministic checks, and pre-execution order is insufficient",
        "Validation of one producer does not establish validation of another",
        "every model-proposed action path, including read-only tools, internal tools, and code execution",
        "as the producer, dispatcher, or executor when it declares that path's checks before approval or execution and preserves validated dispatch to any separate executor",
        "For a separate validator, trace the actual proposal invocation and validated result",
        "write-only validation invocation or broad validator responsibility does not establish validation of another action path from the same producer",
    ):
        assert obligation in criterion


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_action_validation_policy_changes_production_identity_only(
    monkeypatch, stage, maturity
):
    guarantees = ("audit_and_provenance",)
    current = gate.review_identity(stage, maturity, guarantees)

    def previous_requirements(stage, maturity, required=()):
        requirements = staged_review_requirements(stage, maturity, required)
        if stage == "components" and maturity == "production":
            requirements["brief_coverage"] = requirements["brief_coverage"].split(
                " For every producer of model-proposed actions", 1
            )[0]
        if stage == "connections" and "audit_and_provenance" in requirements:
            requirements["audit_and_provenance"] = requirements[
                "audit_and_provenance"
            ].replace(
                "A named compatible owner may perform this deterministic validation internally as the producer, dispatcher, or executor when it declares that path's checks before approval or execution and preserves validated dispatch to any separate executor. ",
                "",
            )
        return requirements

    monkeypatch.setattr(gate, "staged_review_requirements", previous_requirements)
    assert (gate.review_identity(stage, maturity, guarantees) != current) is (
        maturity == "production"
    )


def test_production_claim_checking_requires_component_owner_before_connections():
    prototype = staged_review_requirements("components", "prototype")
    production = staged_review_requirements("components", "production")

    assert prototype.keys() == production.keys()
    ownership = production["mece_scope"]
    for requirement in (
        "When retrieved evidence supports material factual claims in generated answers",
        "explicitly owns checking those claims against the evidence before delivery or reuse",
        "Grounded generation and citations alone do not establish claim checking",
        "A compatible existing owner may perform the check",
        "invocation contracts and failure paths belong to connection review",
        "optional creative examples or evaluation-only reuse",
    ):
        assert requirement in ownership
        assert requirement not in prototype["mece_scope"]
    assert "retrieval_and_reuse_trust" not in production


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_component_generation_declares_factual_check_owner_only_at_production(maturity):
    prompt, _ = generation._attempt_prompt(
        stage="components",
        request="Build a tutor whose factual answers use approved course notes.",
        resolved_maturity=maturity,
        write_set=generation.create_write_set(component_limit=8, edge_limit=16),
        upstream_fingerprint="a" * 64,
        attempt=0,
        prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None,
        structural_findings=[],
        gate_findings=[],
        base=None,
        rejected_candidate=None,
        architecture_context="Approved course notes support the requested tutor.",
    )
    requirement = (
        "explicitly declare the component responsibility that checks those claims "
        "against the evidence before delivery or reuse"
    )
    assert (requirement in prompt) is (maturity == "production")
    if maturity == "production":
        assert "Reuse a compatible existing owner" in prompt
        assert "optional creative examples or evaluation-only reuse" in prompt


def test_claim_entailment_checks_preserve_action_validation_and_failed_retrieval():
    trust = STAGED_PRODUCTION_REQUIREMENTS["retrieval_and_reuse_trust"]
    assert "Check material generated factual claims against the retrieved evidence for entailment" in trust
    assert "Grounded generation and citations alone do not establish this check" in trust
    assert "without requiring proof that the source itself is true" in trust
    assert "Do not require deterministic semantic entailment unless the user requests it" in trust
    assert "mechanically verifiable structure and action-constraint checks retain their deterministic requirements" in trust
    assert "Failed required factual retrieval must end in clarification, abstention, or a bounded validated retry" in trust
    assert "deterministically validates those proposals' structure and allowed constraints" in (
        STAGED_PRODUCTION_REQUIREMENTS["audit_and_provenance"]
    )


@pytest.mark.parametrize("creates_approval", [False, True])
def test_relay_review_preserves_received_evidence_and_decision_ownership(creates_approval):
    records = [
        {"source": "prompt_builder", "target": "model",
         "label": "Augmented prompt with retrieved source passages"},
        {"source": "model", "target": "presenter", "label": (
            "Approve the action" if creates_approval else
            "Forward generated answer with already received source passages"
        )},
    ]
    prompt = gate._prompt(
        gate="connections", user_request="Show the model delivery path",
        evidence_bundle={"candidate_components": [
            {"id": "model", "description": "Generate answers using augmented context"}
        ]}, resolved_maturity="prototype", candidate_records=records,
        required_production_guarantees=(),
    )
    captured = json.loads(prompt.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0])
    assert [row["record"] for row in captured] == records
    assert "An intermediary may forward already received data" in prompt
    assert "does not authorize a consumer to create a policy or approval decision" in prompt
    assert "substitute generated citations for canonical source data" in prompt


@pytest.mark.parametrize("read_path", ["bypass", "separate_validator", "internal_validator", "producer_validator"])
def test_action_path_review_preserves_read_and_write_validation_evidence(read_path):
    components = [
        {"id": "planner", "responsibility": "Proposes read and write tool calls."},
        {"id": "validator", "responsibility": "Deterministically checks proposal structure and allowed constraints."},
        {"id": "executor", "responsibility": "Executes approved calls."},
    ]
    records = [
        {"source": "planner", "target": "validator", "label": "Submit write proposal for checks"},
        {"source": "validator", "target": "planner", "label": "Return validated write proposal"},
        {"source": "planner", "target": "executor", "label": "Execute validated write proposal"},
        {"source": "planner", "target": "executor", "label": "Execute proposed read"},
    ]
    if read_path == "separate_validator":
        records[3:3] = [
            {"source": "planner", "target": "validator", "label": "Submit read proposal for deterministic structure and allowed-constraint checks"},
            {"source": "validator", "target": "planner", "label": "Return validated read proposal before execution"},
        ]
        records[-1]["label"] = "Execute validated read proposal"
    elif read_path == "internal_validator":
        components[-1]["responsibility"] += " Deterministically validates read proposal structure and allowed constraints internally before execution."
    elif read_path == "producer_validator":
        components[0]["responsibility"] += " Deterministically validates read proposal structure and allowed constraints internally before dispatch."
        records[-1]["label"] = "Dispatch validated read proposal to separate executor"
        assert records[-1]["source"] == "planner"
        assert records[-1]["target"] == "executor"
        assert not any(record["source"] == record["target"] for record in records)
    prompt = gate._prompt(
        gate="connections", user_request="Review all tool action paths",
        evidence_bundle={"candidate_components": components},
        resolved_maturity="production", candidate_records=records,
        required_production_guarantees=("audit_and_provenance",),
    )
    captured = json.loads(prompt.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0])
    assert [row["record"] for row in captured] == records
    assert "every model-proposed action path, including read-only tools" in prompt
    assert "write-only validation invocation or broad validator responsibility" in prompt
    assert "as the producer, dispatcher, or executor when it declares that path's checks before approval or execution and preserves validated dispatch to any separate executor" in prompt
    assert "trace the actual proposal invocation and validated result" in prompt


@pytest.mark.parametrize("reversed_owner", [False, True])
def test_lookup_review_identifies_payload_owner_before_request_reply_pairing(reversed_owner):
    consumer, owner = "reviewer", "measurement_recorder"
    requester, recipient = (owner, consumer) if reversed_owner else (consumer, owner)
    records = [
        {"source": requester, "target": recipient, "label": "Request recorded measurements"},
        {"source": recipient, "target": requester, "label": "Return recorded measurements"},
    ]
    evidence = {"candidate_components": [
        {"id": consumer, "responsibility": "Consumes measurements to review evaluation outcomes."},
        {"id": owner, "responsibility": "Produces and stores authoritative measurement records."},
    ], "connection_exchanges": [{"request_record_index": 0, "response_record_index": 1}]}
    prompt = gate._prompt(
        gate="connections", user_request="Review the measurement lookup",
        evidence_bundle=evidence, resolved_maturity="production", candidate_records=records,
        required_production_guarantees=(),
    )
    captured = json.loads(prompt.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0])
    assert [row["record"] for row in captured] == records
    assert json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0]) == evidence
    criteria = json.loads(prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0])
    rule = criteria["edge_semantics"]
    assert "Before pairing, identify the consumer needing each payload" in rule
    assert "receiving a request does not give a consumer authority to produce owner-held records" in rule
    assert "An intermediary may forward already received data without owning its original authority" in rule
    assert "An authoritative owner may deliver directly to multiple compatible consumers" in rule


@pytest.mark.parametrize("path", [
    "write_only", "missing_result", "missing_outcome", "combined", "direct", "delegated", "same_owner",
    "autonomous", "conceptual",
])
def test_operation_coverage_evidence_reaches_connection_author_and_review(path):
    components = [
        {"id": "planner", "responsibility": "Produces task outcomes."},
        {"id": "executor", "responsibility": "Runs search, code, and write operations."},
        {"id": "tools", "responsibility": "Provides search results, code output, and write status."},
        {"id": "memory", "responsibility": "Writes new memories after task outcomes."},
    ]
    records = [
        {"source": "executor", "target": "tools", "label": "Execute approved write"},
        {"source": "tools", "target": "executor", "label": "Return commit status"},
        {"source": "planner", "target": "memory", "label": "Request prior stored context"},
    ]
    if path == "missing_result":
        records[0]["label"] = "Execute approved search, code, or write operation"
    if path in {"missing_outcome", "combined", "direct", "delegated", "same_owner", "autonomous"}:
        records[0]["label"] = "Execute approved search, code, or write operation"
        records[1]["label"] = "Return search results, code output, or write commit status"
    if path in {"combined", "direct"}:
        records[2]["label"] = "Supply new task outcome and request updated context"
    elif path == "delegated":
        records += [
            {"source": "planner", "target": "executor", "label": "Delegate new outcome delivery to memory"},
            {"source": "executor", "target": "memory", "label": "Deliver delegated new outcome"},
        ]
    elif path == "same_owner":
        components[0]["responsibility"] += " Internally writes memories from its newly produced outcomes."
        components.pop()
        records.pop()
    elif path == "autonomous":
        components[-1]["responsibility"] += " Autonomously observes newly completed task outcomes from the authoritative run log."
    elif path == "conceptual":
        components = [{"id": "adaptation", "responsibility": "Offline parameter adaptation"},
                      {"id": "inference", "responsibility": "Live inference using adapted parameters"}]
        records = [{"source": "adaptation", "target": "inference", "label": "Adapted parameters inform inference"}]
    context = generation.AcceptedContext(
        assumptions=("Use the requested overview depth.",), external_effects=False,
        retrieval_or_reuse=False, learning_or_release=False,
    )
    prompt, _ = generation._attempt_prompt(
        stage="connections", request="Show declared operations at overview depth",
        resolved_maturity="production", write_set=generation.create_write_set(component_limit=4, edge_limit=12),
        upstream_fingerprint="a" * 64, attempt=0, prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None, structural_findings=[], gate_findings=[],
        base=None, rejected_candidate=None, accepted_context=context,
    )
    reviewed = gate._prompt(
        gate="connections", user_request="Show declared operations at overview depth",
        evidence_bundle={"candidate_components": components, "candidate_context": context.prompt_value()},
        resolved_maturity="production", candidate_records=records, required_production_guarantees=(),
    )
    author_rule = json.loads(prompt.split("\nINPUT\n", 1)[1])["acceptance_criteria"]["runtime_completeness"]
    review_rule = json.loads(reviewed.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0])["runtime_completeness"]
    assert author_rule == review_rule
    for obligation in (
        "At the selected depth, cover each material requested or declared executable operation",
        "One operation's invocation or status-only reply does not establish another operation",
        "New outcome or update data must reach its update owner",
        "prior stored state may support declared metadata updates but does not supply unrelated new domain or progress data",
        "Direct, delegated, combined-contract, or declared same-owner internal paths",
        "Explicit autonomous observation is valid",
        "Do not require a separate edge or component per operation",
        "Conceptual maps retain truthful one-way causal or lifecycle relationships",
    ):
        assert obligation in review_rule
    captured = json.loads(reviewed.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0])
    assert [row["record"] for row in captured] == records
    assert "runtime_completeness" not in staged_review_requirements("components", "production")


@pytest.mark.parametrize("explicit_consumer_checks", [False, True])
def test_reusable_memory_review_preserves_executable_control_evidence(explicit_consumer_checks):
    components = [
        {"id": "memory_store", "responsibility": "Stores cross-session memories with provenance and version; entries can be invalidated."},
        {"id": "memory_consumer", "responsibility": "Recalls relevant memories to assemble task context."},
    ]
    if explicit_consumer_checks:
        components[-1]["responsibility"] += " Checks applicable access identity, version, provenance and validity internally before reuse; rejects stale or rejected memories, treats recalled bytes as untrusted, and invalidates and revalidates entries when their source changes."
    records = [
        {"source": "memory_consumer", "target": "memory_store", "label": "Request stored memories"},
        {"source": "memory_store", "target": "memory_consumer", "label": "Return memories with provenance and version"},
    ]
    prompt = gate._prompt(
        gate="connections", user_request="Use cross-session memory for task context",
        evidence_bundle={"candidate_components": components}, resolved_maturity="production",
        candidate_records=records, required_production_guarantees=("retrieval_and_reuse_trust",),
    )
    captured = json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0])
    assert captured["candidate_components"] == components
    criteria = json.loads(prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0])
    lifecycle = criteria["artifact_reuse_lifecycle"]
    for obligation in (
        "checks applicable scope and validity before reuse",
        "rejects stale or rejected artifacts",
        "Stored metadata or a capability to invalidate does not establish an invalidation or revalidation operation",
        "A compatible consumer may own these checks internally without a separate service or edge",
    ):
        assert obligation in lifecycle
    assert "its consuming runtime treats retrieved or recalled bytes as untrusted data" in criteria["retrieval_and_reuse_trust"]
    assert "learning_and_release" not in criteria


@pytest.mark.parametrize("input_path", [
    "unrelated_consumer", "onward_relay", "metadata_update", "new_progress_from_metadata",
    "same_owner_produced",
])
def test_write_review_preserves_change_input_origin_before_destination(input_path):
    components = [
        {"id": "executor", "responsibility": "Produces tool results."},
        {"id": "reviewer", "responsibility": "Reviews new task outcomes."},
        {"id": "writer", "responsibility": "Recalls prior entries and records new progress and facts."},
        {"id": "store", "responsibility": "Stores progress, facts, and access metadata."},
    ]
    records = [
        {"source": "executor", "target": "reviewer", "label": "Deliver new task results"},
        {"source": "writer", "target": "store", "label": "Request prior entries"},
        {"source": "store", "target": "writer", "label": "Return prior entries and access metadata"},
        {"source": "writer", "target": "store", "label": "Write new progress notes and facts"},
    ]
    if input_path == "onward_relay":
        records.insert(3, {"source": "reviewer", "target": "writer", "label": "Forward newly reviewed task outcome for memory update"})
    elif input_path == "metadata_update":
        components[2]["responsibility"] = "Recalls prior entries and increments their access count internally from the lookup."
        records[-1]["label"] = "Write updated access count derived from lookup metadata"
    elif input_path == "new_progress_from_metadata":
        components[2]["responsibility"] = "Recalls prior entries and increments their access count internally from the lookup; records new task progress and facts."
        records[-1]["label"] = "Write new task progress notes and facts"
    elif input_path == "same_owner_produced":
        components[2]["responsibility"] += " Internally observes its own task execution and produces new progress facts before writing them."
    prompt = gate._prompt(
        gate="connections", user_request="Review memory writes at overview depth",
        evidence_bundle={"candidate_components": components}, resolved_maturity="production",
        candidate_records=records, required_production_guarantees=(),
    )
    captured = json.loads(prompt.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0])
    assert [row["record"] for row in captured] == records
    evidence = json.loads(prompt.split("Evidence bundle: ", 1)[1].split("\n", 1)[0])
    assert evidence["candidate_components"] == components
    rule = json.loads(prompt.split("Acceptance criteria: ", 1)[1].split("\n", 1)[0])["runtime_completeness"]
    for obligation in (
        "first cite its supplied or explicitly internally produced change input at the writer before execution",
        "An outgoing write contract establishes destination, not data origin",
        "Delivery to another consumer does not supply this writer without an onward contract",
        "prior stored state may support declared metadata updates but does not supply unrelated new domain or progress data",
        "Explicit autonomous observation is valid",
    ):
        assert obligation in rule


@pytest.mark.parametrize("maturity,reuse", [
    ("prototype", False), ("prototype", True), ("production", False), ("production", True),
])
def test_reuse_capability_expands_only_staged_production_review(maturity, reuse):
    selectors = production_proofs_for_capabilities({
        "external_effects": False, "retrieval_or_reuse": reuse, "learning_or_release": False,
    }, maturity=maturity)
    requirements = staged_review_requirements("connections", maturity, selectors)
    expected = maturity == "production" and reuse
    assert ("retrieval_and_reuse_trust" in requirements) == expected
    assert ("artifact_reuse_lifecycle" in requirements) == expected
    assert "artifact_reuse_lifecycle" not in selectors
    assert "artifact_reuse_lifecycle" not in TOPOLOGY_PROOF_REQUIREMENTS
    assert "artifact_reuse_lifecycle" not in RUBRIC_CRITERIA
    if expected:
        codes = list(requirements)
        assert codes.index("artifact_reuse_lifecycle") == codes.index("retrieval_and_reuse_trust") + 1
        assert requirements["artifact_reuse_lifecycle"] == STAGED_PRODUCTION_REQUIREMENTS["artifact_reuse_lifecycle"]


@pytest.mark.parametrize("stage", ["components", "connections"])
@pytest.mark.parametrize("origin", ["missing", "relay", "internal_owner"])
def test_audit_origin_evidence_and_rule_reach_author_and_reviewer(stage, origin):
    # Fixtures test retained evidence and shared criteria, not model judgments.
    components = [
        {"id": "recall", "responsibility": "Invalidates stale memory entries."},
        {"id": "writer", "responsibility": "Persists memory and logs writes and checkpoint outcomes."},
        {"id": "store", "responsibility": "Stores memories and applies invalidation."},
        {"id": "logs", "responsibility": "Stores audit evidence."},
    ]
    records = [
        {"source": "recall", "target": "store", "label": "Invalidate stale entries"},
        {"source": "writer", "target": "logs", "label": "Record memory writes, invalidations, and checkpoint outcomes"},
    ]
    if origin == "relay":
        records.insert(1, {"source": "recall", "target": "writer", "label": "Forward invalidation input and outcome for audit"})
    elif origin == "internal_owner":
        components[1]["responsibility"] += " Internally owns invalidation and its outcomes before producing audit evidence."
    context = generation.AcceptedContext(
        assumptions=(), external_effects=False, retrieval_or_reuse=False, learning_or_release=False,
    )
    author, _ = generation._attempt_prompt(
        stage=stage, request="Audit memory invalidation outcomes.", resolved_maturity="production",
        write_set=generation.create_write_set(component_limit=4, edge_limit=8),
        upstream_fingerprint="a" * 64, attempt=0, prior_prompt_fingerprint=None,
        prior_write_set_fingerprint=None, structural_findings=[], gate_findings=[],
        base=None, rejected_candidate=None, accepted_context=context,
        architecture_context="Audit memory operations." if stage == "components" else None,
    )
    review = gate._prompt(
        gate=stage, user_request="Audit memory invalidation outcomes.",
        evidence_bundle={"candidate_components": components}, resolved_maturity="production",
        candidate_records=components if stage == "components" else records,
        required_production_guarantees=("audit_and_provenance",),
    )
    field = "downstream_controls" if stage == "components" else "acceptance_criteria"
    author_rule = json.loads(author.split("\nINPUT\n", 1)[1])[field]["audit_and_provenance"]
    review_field = "downstream_controls: " if stage == "components" else "Acceptance criteria: "
    review_rule = json.loads(review.split(review_field, 1)[1].split("\n", 1)[0])["audit_and_provenance"]
    assert author_rule == review_rule == STAGED_PRODUCTION_REQUIREMENTS["audit_and_provenance"]
    assert "An audit producer must own the recorded operation or receive its material input or outcome through a declared path" in review_rule
    assert "Naming another owner's event in a log contract does not supply that data" in review_rule
    evidence = json.loads(review.split("Evidence bundle: ", 1)[1].split("\n", 1)[0])
    assert evidence["candidate_components"] == components
    captured = json.loads(review.split("Immutable candidate records: ", 1)[1].split("\n", 1)[0])
    assert [row["record"] for row in captured] == (components if stage == "components" else records)
    if origin == "relay":
        assert records[1]["target"] == records[2]["source"] == "writer"
        assert records[1]["label"] == "Forward invalidation input and outcome for audit"
