"""Policy contracts shared by staged generation and review."""

import pytest

from agent.architecture_rubric import staged_review_requirements


def test_retry_policy_accepts_atomic_effect_and_dedup_without_separate_protocol():
    rule = staged_review_requirements("connections", "production", ())[
        "state_effect_reconciliation"
    ]
    assert "atomic durable commit of the effect and same-operation deduplication" in rule
    assert "with safe same-key replay" in rule
    assert "separate pre-effect reservation and read-back are unnecessary" in rule
    assert "Missing implementation detail is advisory" in rule
    assert "explicitly requested guarantee or establishes unsafe behavior" in rule


def test_retry_policy_retains_unsafe_boundary_and_external_effect_requirements():
    rule = staged_review_requirements("connections", "production", ())[
        "state_effect_reconciliation"
    ]
    assert "A key alone proves neither atomicity nor safe replay" in rule
    assert "Check-before-write without race protection" in rule
    assert "dedup marker committed separately before or after the effect" in rule
    assert "Effects outside that atomic boundary require durable identity" in rule
    assert "safe target-side idempotency or reconciliation before retry" in rule
    assert "For uncertain non-idempotent effects, reserve identity durably" in rule
    assert "COMMITTED records success" in rule
    assert "NOT_FOUND permits safe same-key retry" in rule
    assert "STILL_UNKNOWN has bounded escalation" in rule
    assert "authorization, policy, freshness, fencing" in rule
    assert "bounded compensation for late anomalies" in rule


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_topic_map_semantics_preserve_real_interactions_and_runtime_rules(maturity):
    components = staged_review_requirements("components", maturity)["objective_fidelity"]
    connections = staged_review_requirements("connections", maturity)["edge_semantics"]
    assert "Abstract topics such as Prompt engineering, Fine-tuning" in components
    assert "For applied system designs, select the initiating primary runtime actor as the root" in components
    assert "Every primary member must be naturally reachable outward from that root" in components
    assert "preserve retained group names" in components
    assert "concrete lifecycle responsibilities or domain decisions" in components
    assert "depict the subject's mechanisms or decision process" in components
    assert "do not create a learner session, comparison or tutoring service" in components
    assert "evidence-retrieval architecture unless explicitly requested as product or system features" in components
    assert "both topic or lifecycle maps and applied system designs" in components
    assert "service nodes must own real computation" in components
    assert "One-way relationships need no reverse reply" in connections
    assert "requests expecting returned data still require their authoritative payload" in connections
    assert "Distinguish offline parameter adaptation from live inference" in connections
    assert "a path that bypasses a required control" in connections
    assert "declared trust boundary" in connections


@pytest.mark.parametrize("maturity", ["prototype", "production"])
def test_staged_component_objective_preserves_source_status_and_scope(maturity):
    rule = staged_review_requirements("components", maturity)["objective_fidelity"]
    assert "status, jurisdiction, timing, and scope of factual claims" in rule
    assert "drawn from supplied sources" in rule
    assert "A proposal, recommendation, or suggested safeguard" in rule
    assert "does not establish an adopted or enacted obligation" in rule
    assert "Qualify uncertain source claims or omit them" in rule
    assert "Distinguish proposed design choices from source-established requirements" in rule


def test_output_delivery_rule_is_shared_by_generic_and_staged_review():
    from agent.architecture_rubric import RUBRIC_CRITERIA

    generic = RUBRIC_CRITERIA["edge_semantics"][1]
    shared = generic[generic.index("When a declared consumer") :]
    for maturity in ("prototype", "production"):
        rule = staged_review_requirements("connections", maturity)["edge_semantics"]
        assert shared in rule
        assert "Trace required input data and execution output to each declared consumer" in rule
        assert "Every intermediary contract must name the actual required payload" in rule
        assert (
            "validation verdict, acknowledgment, or commit status alone is insufficient"
            in rule
        )
        assert (
            "Direct delivery, explicit forwarding, or declared persistence with a consumer read"
            in rule
        )
        assert "Declared same-owner handling can also satisfy output delivery without extra edges" in rule
        assert "Preserve this output route during scoped edits and repairs" in rule
        assert "independent declared route already delivers all required output" in rule


def test_output_delivery_names_payload_and_preserves_status_only_consumers():
    rule = staged_review_requirements("connections", "prototype")["edge_semantics"]
    assert "Name the actual needed output data in each forwarding connection" in rule
    assert (
        "Generic 'success', 'failure', or 'outcome' does not imply a result payload"
        in rule
    )
    assert "planner must receive tool observations or result content" in rule
    assert "execution status as accompanying data" in rule
    assert (
        "A commit/status-only contract is valid when its consumer needs only commit information"
        in rule
    )
