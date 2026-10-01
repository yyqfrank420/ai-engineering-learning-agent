"""Policy contracts shared by staged generation and review."""

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


def test_output_delivery_rule_is_shared_by_generic_and_staged_review():
    from agent.architecture_rubric import RUBRIC_CRITERIA

    generic = RUBRIC_CRITERIA["edge_semantics"][1]
    shared = generic[generic.index("When a declared consumer") :]
    for maturity in ("prototype", "production"):
        rule = staged_review_requirements("connections", maturity)["edge_semantics"]
        assert shared in rule
        assert (
            "Every intermediary contract on that output route must carry the actual output"
            in rule
        )
        assert (
            "validation verdict, acknowledgment, or commit status alone is insufficient"
            in rule
        )
        assert (
            "Direct delivery, explicit forwarding, or declared persistence with a consumer read"
            in rule
        )
        assert "Preserve this output route during scoped edits and repairs" in rule
        assert "independent declared route already delivers all required output" in rule
