from types import SimpleNamespace

import pytest

from eval.cost_gate import (
    CostPolicy,
    account_application_cost,
    account_judge_cost,
    evaluate_cost_policy,
)


def test_application_cost_is_attributed_by_attempt_thread_and_operation():
    accounting = account_application_cost(
        [
            {
                "id": "graph-expansion",
                "thread_id": "thread-final",
                "thread_ids": ["thread-first", "thread-final"],
            },
            {"id": "graph-off", "thread_id": "thread-light"},
        ],
        [
            {
                "thread_id": "thread-first",
                "operation": "graph_integration",
                "attempts": [
                    {
                        "provider": "anthropic",
                        "model": "claude-opus-5-20260801",
                        "input_tokens": 1_000,
                        "output_tokens": 100,
                        "queue_wait_ms": 30,
                    },
                    {
                        "provider": "openai",
                        "model": "gpt-5.4",
                        "input_tokens": 500,
                        "output_tokens": 50,
                        "queue_wait_ms": 0,
                    },
                ],
            },
            {
                "thread_id": "thread-light",
                "operation": "synthesis",
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "input_tokens": 100,
                "output_tokens": 10,
                "queue_wait_ms": 5,
            },
        ],
    )

    assert accounting["status"] == "pass"
    assert accounting["total"] == {
        "input_tokens": 1_600,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 160,
        "queue_wait_ms": 35,
        "estimated_usd": 0.0098,
        "known_subtotal_usd": 0.0098,
    }
    graph = accounting["cases"][0]
    assert graph["input_tokens"] == 1_500
    assert graph["operations"][0]["provider_attempts"] == 2
    assert graph["operations"][0]["estimated_usd"] == 0.0095


def test_application_cost_prices_anthropic_cache_writes_and_reads():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "claude-opus-5",
                "input_tokens": 1_000,
                "cache_creation_input_tokens": 1_000,
                "cache_read_input_tokens": 1_000,
                "output_tokens": 100,
            }
        ],
    )

    assert accounting["status"] == "pass"
    assert accounting["total"] == {
        "input_tokens": 1_000,
        "cache_creation_input_tokens": 1_000,
        "cache_read_input_tokens": 1_000,
        "output_tokens": 100,
        "queue_wait_ms": 0,
        "estimated_usd": 0.01425,
        "known_subtotal_usd": 0.01425,
    }


def test_application_cost_prices_kimi_automatic_cache_reads():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [{
            "thread_id": "thread",
            "operation": "graph_worker",
            "provider": "kimi",
            "model": "kimi-k3",
            "input_tokens": 1_000,
            "cache_read_input_tokens": 2_000,
            "output_tokens": 100,
        }],
    )

    assert accounting["status"] == "pass"
    assert accounting["total"]["estimated_usd"] == 0.0051


def test_application_cost_rejects_cache_usage_without_provider_pricing():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "gpt-5.4",
                "cache_read_input_tokens": 1_000,
            }
        ],
    )

    assert accounting["status"] == "infrastructure"
    assert "unsupported prompt-cache pricing" in accounting["reason"]
    assert accounting["total"]["estimated_usd"] is None


def test_unpriced_model_is_infrastructure_and_never_zero_cost():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "new-unpriced-model",
                "input_tokens": 10,
                "output_tokens": 2,
            }
        ],
    )

    assert accounting["status"] == "infrastructure"
    assert "unpriced model" in accounting["reason"]
    assert accounting["total"]["estimated_usd"] is None
    assert accounting["cases"][0]["estimated_usd"] is None
    assert accounting["cases"][0]["operations"][0]["estimated_usd"] is None
    assert evaluate_cost_policy(accounting)["blocking_status"] == "fail"


def test_specific_model_price_wins_over_a_shared_prefix():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "gpt-5.4-mini-2026-07-01",
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
            }
        ],
    )

    assert accounting["total"]["estimated_usd"] == 5.25


def test_model_prices_reject_lookalike_future_skus():
    for model in ("gpt-5.40", "gpt-5.4-turbo", "claude-opus-50"):
        accounting = account_application_cost(
            [{"id": "case", "thread_id": "thread"}],
            [
                {
                    "thread_id": "thread",
                    "operation": "synthesis",
                    "model": model,
                    "input_tokens": 10,
                    "output_tokens": 2,
                }
            ],
        )

        assert accounting["status"] == "infrastructure"
        assert f"unpriced model {model!r}" in accounting["reason"]


def test_case_with_a_thread_but_no_telemetry_is_unknown_not_zero_cost():
    accounting = account_application_cost(
        [
            {"id": "observed", "thread_id": "thread-observed"},
            {"id": "missing", "thread_id": "thread-missing"},
        ],
        [
            {
                "thread_id": "thread-observed",
                "operation": "synthesis",
                "model": "claude-opus-5",
                "input_tokens": 10,
                "output_tokens": 2,
            }
        ],
    )

    assert accounting["status"] == "infrastructure"
    assert "'missing' has thread attribution but no application telemetry" in accounting[
        "reason"
    ]
    assert accounting["cases"][1]["estimated_usd"] is None
    assert accounting["total"]["estimated_usd"] is None


def test_accepted_attempt_with_incomplete_usage_is_unknown():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "attempts": [
                    {
                        "model": "claude-opus-5",
                        "status": "error_incomplete_usage",
                        "input_tokens": 100,
                        "output_tokens": 0,
                    }
                ],
            }
        ],
    )

    assert accounting["status"] == "incomplete"
    assert "incomplete usage" in accounting["reason"]
    assert accounting["usage_complete"] is False
    assert accounting["incomplete_attempt_count"] == 1
    assert accounting["cases"][0]["input_tokens"] == 100
    assert accounting["cases"][0]["estimated_usd"] is None


def test_cost_policy_can_report_before_it_blocks():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [
            {
                "thread_id": "thread",
                "operation": "synthesis",
                "model": "claude-opus-5",
                "input_tokens": 1_000,
                "output_tokens": 100,
            }
        ],
    )

    report_only = evaluate_cost_policy(
        accounting,
        CostPolicy(mode="report-only", suite_limit_usd=0.001),
    )
    blocking = evaluate_cost_policy(
        accounting,
        CostPolicy(mode="blocking", suite_limit_usd=0.001),
    )

    assert report_only["status"] == "over_budget"
    assert report_only["blocking_status"] == "pass"
    assert report_only["baseline_min_runs"] == 5
    assert blocking["blocking_status"] == "fail"


def test_judge_cost_remains_separate_and_per_case():
    accounting = account_judge_cost(
        [
            {
                "id": "case-a",
                "judgments": [
                    {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "estimated_cost_usd": 0.001,
                    }
                ],
            },
            {"id": "case-b", "judgments": []},
        ],
        attempted_calls=1,
    )

    assert accounting["usage_complete"] is True
    assert accounting["incomplete_attempt_count"] == 0
    assert accounting["total"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "known_subtotal_usd": 0.001,
        "estimated_usd": 0.001,
    }
    assert accounting["cases"][0]["known_subtotal_usd"] == 0.001
    assert accounting["cases"][0]["estimated_usd"] == 0.001
    assert accounting["cases"][1]["known_subtotal_usd"] == 0.0
    assert accounting["cases"][1]["estimated_usd"] == 0.0


def test_judge_cost_failed_first_attempt_has_unknown_total():
    accounting = account_judge_cost(
        [{"id": "case", "judgments": []}], attempted_calls=1
    )

    assert accounting["usage_complete"] is False
    assert accounting["incomplete_attempt_count"] == 1
    assert accounting["total"]["known_subtotal_usd"] == 0.0
    assert accounting["total"]["estimated_usd"] is None
    assert accounting["cases"][0]["known_subtotal_usd"] == 0.0
    assert accounting["cases"][0]["estimated_usd"] is None


def test_judge_cost_transport_retry_keeps_known_success_but_not_complete_cost():
    accounting = account_judge_cost(
        [
            {
                "id": "retried",
                "judgments": [
                    {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "estimated_cost_usd": 0.001,
                    }
                ],
            },
            {"id": "other", "judgments": []},
        ],
        attempted_calls=2,
    )

    assert accounting["usage_complete"] is False
    assert accounting["incomplete_attempt_count"] == 1
    assert accounting["total"]["input_tokens"] == 100
    assert accounting["total"]["known_subtotal_usd"] == 0.001
    assert accounting["total"]["estimated_usd"] is None
    assert [case["known_subtotal_usd"] for case in accounting["cases"]] == [
        0.001,
        0.0,
    ]
    assert all(case["estimated_usd"] is None for case in accounting["cases"])


def test_reused_judgment_does_not_prove_prior_attempt_usage_complete():
    accounting = account_judge_cost(
        [
            {
                "id": "resumed",
                "judgments": [
                    {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "estimated_cost_usd": 0.001,
                    }
                ],
            },
            {"id": "current", "judgments": []},
        ],
        attempted_calls=1,
        usage_unverified=True,
    )

    assert accounting["usage_complete"] is False
    assert accounting["incomplete_attempt_count"] is None
    assert accounting["total"]["known_subtotal_usd"] == 0.001
    assert accounting["total"]["estimated_usd"] is None
    assert all(case["estimated_usd"] is None for case in accounting["cases"])


@pytest.mark.asyncio
async def test_live_resume_does_not_claim_complete_historical_judge_cost(monkeypatch):
    import eval.live_runner as live_runner

    judgment = {
        "input_tokens": 100,
        "output_tokens": 20,
        "estimated_cost_usd": 0.001,
    }
    monkeypatch.setattr(
        live_runner,
        "_load_capture",
        lambda _args: {
            "results": [{"id": "memory", "thread_id": "thread", "events": []}],
            "application_telemetry": [
                {
                    "thread_id": "thread",
                    "operation": "synthesis",
                    "model": "claude-opus-5",
                    "input_tokens": 100,
                    "output_tokens": 20,
                }
            ],
        },
    )
    monkeypatch.setattr(
        live_runner,
        "SemanticJudge",
        lambda: SimpleNamespace(provider="anthropic", model="claude-sonnet-5"),
    )
    monkeypatch.setattr(
        live_runner,
        "_load_resume_evaluations",
        lambda *_args, **_kwargs: {
            "memory": {
                "id": "memory",
                "decision": "pass",
                "reason": "prior judgment accepted",
                "deterministic_failures": [],
                "judgments": [judgment],
            }
        },
    )
    args = live_runner.build_parser().parse_args(
        [
            "--suite",
            "diagnostic",
            "--case",
            "memory",
            "--target",
            "https://candidate.example",
            "--capture-replay",
            "--resume-input",
            "prior-report.json",
        ]
    )

    report, exit_code = await live_runner.evaluate(args)

    assert exit_code == 0
    assert report["budget"]["judge_calls"] == 1
    judge_cost = report["cost_accounting"]["judge"]
    assert judge_cost["usage_complete"] is False
    assert judge_cost["incomplete_attempt_count"] is None
    assert judge_cost["total"]["known_subtotal_usd"] == 0.001
    assert judge_cost["total"]["estimated_usd"] is None
    assert judge_cost["cases"][0]["estimated_usd"] is None
    assert report["estimated_cost"]["judge_usd"] is None


@pytest.mark.asyncio
async def test_over_limit_judge_reservation_has_unverified_attempt_count(monkeypatch):
    import eval.live_runner as live_runner

    budget_class = live_runner.EvaluationBudget
    monkeypatch.setattr(
        live_runner,
        "EvaluationBudget",
        lambda **kwargs: budget_class(
            application_calls=kwargs["application_calls"], judge_calls=1
        ),
    )
    monkeypatch.setattr(
        live_runner,
        "_load_capture",
        lambda _args: {
            "results": [{"id": "memory", "thread_id": "thread", "events": []}],
            "application_telemetry": [
                {
                    "thread_id": "thread",
                    "operation": "synthesis",
                    "model": "claude-opus-5",
                    "input_tokens": 100,
                    "output_tokens": 20,
                }
            ],
        },
    )
    monkeypatch.setattr(
        live_runner,
        "SemanticJudge",
        lambda: SimpleNamespace(provider="anthropic", model="claude-sonnet-5"),
    )

    async def reserve_past_limit(*_args, on_attempt):
        on_attempt()
        on_attempt()

    monkeypatch.setattr(live_runner, "judge_with_transport_retry", reserve_past_limit)
    args = live_runner.build_parser().parse_args(
        [
            "--suite",
            "diagnostic",
            "--case",
            "memory",
            "--target",
            "https://candidate.example",
        ]
    )

    report, exit_code = await live_runner.evaluate(args)

    assert exit_code == 2
    assert report["budget"]["judge_calls"] == 2
    assert report["budget"]["judge_limit"] == 1
    judge_cost = report["cost_accounting"]["judge"]
    assert judge_cost["usage_complete"] is False
    assert judge_cost["incomplete_attempt_count"] is None
    assert judge_cost["total"]["estimated_usd"] is None


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens", "cost_usd", "known_subtotal_usd"),
    [
        (0, 0, 0.0, 0.0),
        (0, 0, 0.001, 0.001),
        (None, None, None, 0.0),
        (True, 20, 0.001, 0.001),
        ("100", 20, 0.001, 0.001),
        (100, 20, float("inf"), 0.0),
        (100, 20, float("nan"), 0.0),
        (100, 20, -0.001, 0.0),
        (100, 20, 10**1000, 0.0),
    ],
)
def test_recorded_judgment_without_complete_usage_is_not_zero_cost_proof(
    input_tokens, output_tokens, cost_usd, known_subtotal_usd
):
    accounting = account_judge_cost(
        [
            {
                "id": "case",
                "judgments": [
                    {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "estimated_cost_usd": cost_usd,
                    }
                ],
            }
        ],
        attempted_calls=1,
    )

    assert accounting["usage_complete"] is False
    assert accounting["incomplete_attempt_count"] == 1
    assert accounting["total"]["known_subtotal_usd"] == known_subtotal_usd
    assert accounting["total"]["estimated_usd"] is None
    assert accounting["cases"][0]["estimated_usd"] is None


def test_judge_cost_zero_attempts_are_complete():
    accounting = account_judge_cost(
        [{"id": "deterministic", "judgments": []}], attempted_calls=0
    )

    assert accounting["usage_complete"] is True
    assert accounting["incomplete_attempt_count"] == 0
    assert accounting["total"]["known_subtotal_usd"] == 0.0
    assert accounting["total"]["estimated_usd"] == 0.0
    assert accounting["cases"][0]["estimated_usd"] == 0.0


@pytest.mark.parametrize("attempted_calls", [-1, 0, True, "1"])
def test_judge_cost_rejects_invalid_attempt_counts(attempted_calls):
    with pytest.raises(ValueError):
        account_judge_cost(
            [{"id": "case", "judgments": [{"estimated_cost_usd": 0.001}]}],
            attempted_calls=attempted_calls,
        )


def test_blocking_cost_breach_is_visible_in_junit_and_summary(
    tmp_path, monkeypatch
):
    from eval.live_runner import _exit_code_for_statuses, _write_outputs

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    report = {
        "status": "fail",
        "blocking_status": "fail",
        "manual_review_policy": "blocking",
        "reason": "suite cost exceeds limit",
        "evaluations": [
            {"id": "case", "decision": "pass", "reason": "passed", "judgments": []}
        ],
        "cost_accounting": {
            "policy": {
                "mode": "blocking",
                "status": "over_budget",
                "blocking_status": "fail",
                "reason": "suite cost exceeds limit",
            },
            "application": {"total": {"estimated_usd": 1.25}},
            "judge": {
                "usage_complete": False,
                "incomplete_attempt_count": 1,
                "total": {"known_subtotal_usd": 0.001, "estimated_usd": None},
            },
        },
    }

    _write_outputs(tmp_path / "live-results.json", report)

    junit = (tmp_path / "live-junit.xml").read_text(encoding="utf-8")
    assert 'tests="2"' in junit
    assert 'failures="1"' in junit
    assert 'name="application-cost-policy"' in junit
    assert "suite cost exceeds limit" in junit
    summary_text = summary.read_text(encoding="utf-8")
    assert "Cost policy: `over_budget` (blocking)" in summary_text
    assert "Application cost: `$1.250000`" in summary_text
    assert "Judge cost: `unknown`" in summary_text
    assert "Known judge subtotal: `$0.001000` (total unavailable)" in summary_text
    assert _exit_code_for_statuses({"fail", "infrastructure"}, "blocking") == 1


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("mode", ["report-only", "blocking"])
@pytest.mark.parametrize("limit", [0.0001, 100.0])
def test_recovered_timeout_preserves_known_subtotal_but_total_remains_unknown(
    accepted, mode, limit
):
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [{
            "thread_id": "thread",
            "operation": "orchestrator_route",
            "status": "success",
            "attempts": [
                {
                    "model": "claude-opus-5", "status": "error",
                    "accepted": accepted, "usage_complete": False,
                    "error_type": "APITimeoutError", "input_tokens": 100,
                },
                {
                    "model": "claude-opus-5", "status": "success",
                    "accepted": True, "usage_complete": True,
                    "input_tokens": 1_000, "output_tokens": 100,
                },
            ],
        }],
    )

    assert accounting["status"] == "incomplete"
    assert accounting["usage_complete"] is False
    assert accounting["incomplete_attempt_count"] == 1
    assert accounting["total"]["known_subtotal_usd"] == 0.008
    assert accounting["total"]["estimated_usd"] is None
    assert accounting["cases"][0]["estimated_usd"] is None
    operation = accounting["cases"][0]["operations"][0]
    assert operation["estimated_usd"] is None
    assert operation["provider_attempts"] == 2
    policy = evaluate_cost_policy(accounting, CostPolicy(
        mode=mode, suite_limit_usd=limit, case_limit_usd=limit,
    ))
    assert policy["status"] == "incomplete"
    assert policy["blocking_status"] == ("pass" if mode == "report-only" else "fail")


def test_incomplete_attempt_count_includes_recovered_zero_usage_timeouts():
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [{
            "thread_id": "thread", "operation": "orchestrator_route", "status": "success",
            "attempts": [
                {"model": "claude-opus-5", "status": "error", "usage_complete": False, "accepted": False},
                {"model": "claude-opus-5", "status": "error", "usage_complete": False, "accepted": False},
                {"model": "claude-opus-5", "status": "success", "usage_complete": True, "input_tokens": 100},
            ],
        }],
    )
    assert accounting["incomplete_attempt_count"] == 2
    assert accounting["total"]["known_subtotal_usd"] == 0.0005
    assert accounting["total"]["estimated_usd"] is None


@pytest.mark.parametrize("complete", [True, False])
def test_flat_usage_completeness_is_preserved(complete):
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [{
            "thread_id": "thread", "operation": "synthesis", "model": "claude-opus-5",
            "input_tokens": 100, "usage_complete": complete,
        }],
    )
    assert accounting["usage_complete"] is complete
    assert accounting["incomplete_attempt_count"] == (0 if complete else 1)
    assert accounting["status"] == ("pass" if complete else "incomplete")
    assert accounting["total"]["estimated_usd"] == (0.0005 if complete else None)
    assert accounting["total"]["known_subtotal_usd"] == 0.0005


@pytest.mark.parametrize("mode", ["report-only", "blocking"])
@pytest.mark.parametrize("invalid", ["negative", "unpriced", "malformed"])
def test_incomplete_usage_does_not_hide_malformed_accounting(mode, invalid):
    attempt = {"model": "claude-opus-5", "usage_complete": False, "input_tokens": 100}
    if invalid == "unpriced":
        attempt["model"] = "unpriced-model"
    else:
        attempt["input_tokens"] = -1 if invalid == "negative" else "invalid"
    accounting = account_application_cost(
        [{"id": "case", "thread_id": "thread"}],
        [{"thread_id": "thread", "operation": "synthesis", "attempts": [attempt]}],
    )
    assert accounting["status"] == "infrastructure"
    assert accounting["usage_complete"] is False
    assert accounting["incomplete_attempt_count"] == 1
    policy = evaluate_cost_policy(accounting, CostPolicy(mode=mode))
    assert policy["status"] == "infrastructure"
    assert policy["blocking_status"] == "fail"
