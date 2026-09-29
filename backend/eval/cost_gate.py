from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Literal


# Basic search costs $0.002 per successful, nonempty response, verified 2026-10-01:
# https://platform.kimi.ai/docs/pricing/websearch
PRICE_RELEASE = "2026-10-01"
WEB_SEARCH_MODEL = "moonshot-web-search-basic"
WEB_SEARCH_PRICE_USD_PER_REQUEST = 0.002
# https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
# Verified 2026-10-01: $10 per 1,000 searches, charged in addition to tokens.
ANTHROPIC_WEB_SEARCH_PRICE_USD = 0.01
APPLICATION_PRICES_USD_PER_MILLION = {
    # Keep prior models so saved captures remain account-able after a model change.
    WEB_SEARCH_MODEL: (0.0, 0.0),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "kimi-k3": (3.00, 15.00),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
}
# Anthropic's default ephemeral cache uses a five-minute lifetime.
CACHE_WRITE_5M_INPUT_PRICE_MULTIPLIER = 1.25
CACHE_READ_INPUT_PRICE_MULTIPLIER = 0.10
CostPolicyMode = Literal["blocking", "report-only"]
_MODEL_VERSION_SUFFIX = re.compile(r"(?:-\d{8}|-\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class CostPolicy:
    mode: CostPolicyMode = "report-only"
    suite_limit_usd: float | None = None
    case_limit_usd: float | None = None
    baseline_min_runs: int = 5

    def __post_init__(self) -> None:
        if self.mode not in {"blocking", "report-only"}:
            raise ValueError(f"unknown cost policy mode: {self.mode}")
        for value in (self.suite_limit_usd, self.case_limit_usd):
            if value is not None and value < 0:
                raise ValueError("cost limits must be non-negative")
        if self.baseline_min_runs <= 0:
            raise ValueError("baseline_min_runs must be positive")


def _price_for_model(model: str) -> tuple[float, float] | None:
    return next(
        (
            price
            for prefix, price in sorted(
                APPLICATION_PRICES_USD_PER_MILLION.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            )
            if model == prefix
            or (
                model.startswith(prefix)
                and _MODEL_VERSION_SUFFIX.fullmatch(model[len(prefix) :]) is not None
            )
        ),
        None,
    )


def _thread_ids(result: dict[str, Any]) -> set[str]:
    values = [result.get("thread_id")]
    values.extend(result.get("thread_ids") or [])
    values.extend(result.get("attempt_thread_ids") or [])
    for attempt in result.get("attempts") or []:
        if isinstance(attempt, dict):
            values.append(attempt.get("thread_id"))
    return {str(value) for value in values if value}


def _usage_attempts(call: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attempts = call.get("attempts")
    if isinstance(raw_attempts, list) and raw_attempts:
        return [attempt for attempt in raw_attempts if isinstance(attempt, dict)]
    return [
        {
            "attempt": 1,
            "provider": call.get("provider"),
            "model": call.get("model"),
            "status": call.get("status"),
            "usage_complete": call.get("usage_complete"),
            "input_tokens": call.get("input_tokens"),
            "cache_creation_input_tokens": call.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": call.get("cache_read_input_tokens"),
            "output_tokens": call.get("output_tokens"),
            "queue_wait_ms": call.get("queue_wait_ms"),
            **{
                key: call[key]
                for key in ("web_search_requests", "web_search_usage_complete")
                if key in call
            },
        }
    ]


def _empty_usage() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
        "queue_wait_ms": 0,
        "estimated_usd": 0.0,
    }


def account_application_cost(
    browser_results: list[dict[str, Any]],
    telemetry: list[dict[str, Any]],
) -> dict[str, Any]:
    """Price normalized eval telemetry with top-level token counters and attempts."""
    case_order = [str(result.get("id") or "unknown") for result in browser_results]
    case_by_thread: dict[str, str] = {}
    errors: list[str] = []
    incomplete_attempts: list[str] = []
    for result, case_id in zip(browser_results, case_order, strict=True):
        for thread_id in _thread_ids(result):
            previous = case_by_thread.setdefault(thread_id, case_id)
            if previous != case_id:
                errors.append(
                    f"thread {thread_id!r} is attributed to both {previous!r} and {case_id!r}"
                )

    per_case: dict[str, dict[str, Any]] = {
        case_id: {**_empty_usage(), "operations": {}} for case_id in case_order
    }
    attributed_calls = {case_id: 0 for case_id in case_order}
    invalid_cases: set[str] = set()
    invalid_operations: set[tuple[str, str]] = set()
    total = _empty_usage()
    for call_index, call in enumerate(telemetry, start=1):
        thread_id = str(call.get("thread_id") or "")
        case_id = case_by_thread.get(thread_id)
        if case_id is None:
            errors.append(
                f"application call {call_index} has no browser-case thread attribution"
            )
            continue
        attributed_calls[case_id] += 1
        operation = str(call.get("operation") or "unknown")
        operation_usage = per_case[case_id]["operations"].setdefault(
            operation,
            {**_empty_usage(), "calls": 0, "provider_attempts": 0},
        )
        operation_usage["calls"] += 1

        native_search = call.get("web_search") is True or (
            isinstance(call.get("metadata"), dict)
            and call["metadata"].get("web_search") is True
        )
        attempts = _usage_attempts(call)
        if not attempts:
            errors.append(
                f"application call {call_index} has no usable provider attempts"
            )
            invalid_cases.add(case_id)
            invalid_operations.add((case_id, operation))
            continue
        aggregate_search_requests = call.get("web_search_requests", 0)
        if type(aggregate_search_requests) is not int or aggregate_search_requests < 0:
            errors.append(f"application call {call_index} has invalid web-search usage")
            invalid_cases.add(case_id)
            invalid_operations.add((case_id, operation))
        elif (
            "web_search_requests" in call
            and call.get("usage_complete") is not False
            and all(
                type(attempt.get("web_search_requests", 0)) is int
                and attempt.get("web_search_requests", 0) >= 0
                for attempt in attempts
            )
            and aggregate_search_requests
            != sum(attempt.get("web_search_requests", 0) for attempt in attempts)
        ):
            errors.append(
                f"application call {call_index} has inconsistent web-search usage"
            )
            invalid_cases.add(case_id)
            invalid_operations.add((case_id, operation))
        if call.get("usage_complete") is False and all(
            attempt.get("usage_complete") is not False
            and "incomplete_usage" not in str(attempt.get("status") or "")
            for attempt in attempts
        ):
            incomplete_attempts.append(
                f"application call {call_index} has incomplete aggregate usage"
            )
            invalid_cases.add(case_id)
            invalid_operations.add((case_id, operation))
        for attempt_index, attempt in enumerate(attempts, start=1):
            model = str(attempt.get("model") or "")
            standalone_search = model == WEB_SEARCH_MODEL
            count = attempt.get("web_search_requests")
            search_incomplete = (
                (
                    standalone_search
                    and not (
                        type(count) is int
                        and count in (0, 1)
                        and attempt.get("web_search_usage_complete") is True
                    )
                )
                or (native_search and count is None)
                or attempt.get("web_search_usage_complete") is False
            )
            if (
                standalone_search
                or native_search
                or "web_search_requests" in attempt
                or "web_search_usage_complete" in attempt
            ):
                for target in (operation_usage, per_case[case_id], total):
                    target.setdefault("web_search_requests", 0)
                    target.setdefault("web_search_estimated_usd", 0.0)
                    target["web_search_usage_complete"] = (
                        target.get("web_search_usage_complete", True)
                        and not search_incomplete
                    )
            if (
                search_incomplete
                or attempt.get("usage_complete") is False
                or "incomplete_usage" in str(attempt.get("status") or "")
            ):
                # No observed acceptance event does not prove the provider did no work.
                incomplete_attempts.append(
                    f"application call {call_index} attempt {attempt_index} has incomplete usage"
                    + (
                        " (native web search usage unavailable)"
                        if search_incomplete
                        else ""
                    )
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
            price = _price_for_model(model)
            if price is None:
                errors.append(
                    f"application call {call_index} attempt {attempt_index} uses unpriced model {model!r}"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            web_search_requests = (
                0
                if standalone_search and search_incomplete
                else attempt.get("web_search_requests", 0)
            )
            if type(web_search_requests) is not int or web_search_requests < 0:
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has invalid web-search usage"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            if (
                standalone_search and attempt.get("provider") not in (None, "moonshot")
            ) or (
                not standalone_search
                and (web_search_requests or native_search)
                and (
                    attempt.get("provider") != "anthropic"
                    or not model.startswith("claude-")
                )
            ):
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has unsupported web-search pricing"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            try:
                input_tokens = int(attempt.get("input_tokens") or 0)
                cache_creation_input_tokens = int(
                    attempt.get("cache_creation_input_tokens") or 0
                )
                cache_read_input_tokens = int(
                    attempt.get("cache_read_input_tokens") or 0
                )
                output_tokens = int(attempt.get("output_tokens") or 0)
                queue_wait_ms = int(attempt.get("queue_wait_ms") or 0)
            except (TypeError, ValueError):
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has invalid usage"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            if (
                min(
                    input_tokens,
                    cache_creation_input_tokens,
                    cache_read_input_tokens,
                    output_tokens,
                    queue_wait_ms,
                )
                < 0
            ):
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has negative usage"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            if model == WEB_SEARCH_MODEL and any(
                (
                    input_tokens,
                    cache_creation_input_tokens,
                    cache_read_input_tokens,
                    output_tokens,
                )
            ):
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has "
                    "token usage for a non-LLM search service"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            if cache_creation_input_tokens and not model.startswith("claude-"):
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has "
                    f"unsupported prompt-cache pricing for model {model!r}"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            if cache_read_input_tokens and not model.startswith(("claude-", "kimi-")):
                errors.append(
                    f"application call {call_index} attempt {attempt_index} has "
                    f"unsupported prompt-cache pricing for model {model!r}"
                )
                invalid_cases.add(case_id)
                invalid_operations.add((case_id, operation))
                continue
            # Opus 5.5 cache reads cost 5% of input; other priced models use 10%.
            cache_read_multiplier = (
                0.05
                if _MODEL_VERSION_SUFFIX.sub("", model) == "claude-opus-5-5"
                else CACHE_READ_INPUT_PRICE_MULTIPLIER
            )
            search_fee = web_search_requests * (
                WEB_SEARCH_PRICE_USD_PER_REQUEST
                if standalone_search
                else ANTHROPIC_WEB_SEARCH_PRICE_USD
            )
            estimated_usd = (
                input_tokens * price[0] / 1_000_000
                + cache_creation_input_tokens
                * price[0]
                * CACHE_WRITE_5M_INPUT_PRICE_MULTIPLIER
                / 1_000_000
                + cache_read_input_tokens * price[0] * cache_read_multiplier / 1_000_000
                + output_tokens * price[1] / 1_000_000
                + search_fee
            )
            operation_usage["provider_attempts"] += 1
            for target in (operation_usage, per_case[case_id], total):
                target["input_tokens"] += input_tokens
                target["cache_creation_input_tokens"] += cache_creation_input_tokens
                target["cache_read_input_tokens"] += cache_read_input_tokens
                target["output_tokens"] += output_tokens
                if "web_search_requests" in target:
                    target["web_search_requests"] += web_search_requests
                    target["web_search_estimated_usd"] += search_fee
                target["queue_wait_ms"] += queue_wait_ms
                target["estimated_usd"] += estimated_usd

    for result, case_id in zip(browser_results, case_order, strict=True):
        if _thread_ids(result) and attributed_calls[case_id] == 0:
            errors.append(
                f"browser case {case_id!r} has thread attribution but no application telemetry"
            )
            invalid_cases.add(case_id)

    for target in (
        total,
        *per_case.values(),
        *(
            operation
            for usage in per_case.values()
            for operation in usage["operations"].values()
        ),
    ):
        if "web_search_requests" in target:
            if not target["web_search_usage_complete"]:
                target["web_search_requests"] = None
                target["web_search_estimated_usd"] = None
            else:
                target["web_search_estimated_usd"] = round(
                    target["web_search_estimated_usd"], 6
                )

    cases = []
    for case_id in case_order:
        usage = per_case[case_id]
        operations = []
        for operation, operation_usage in sorted(usage.pop("operations").items()):
            operation_usage["estimated_usd"] = (
                None
                if (case_id, operation) in invalid_operations
                else round(operation_usage["estimated_usd"], 6)
            )
            operations.append({"operation": operation, **operation_usage})
        usage["estimated_usd"] = (
            None if case_id in invalid_cases else round(usage["estimated_usd"], 6)
        )
        cases.append({"id": case_id, **usage, "operations": operations})
    total["known_subtotal_usd"] = round(total["estimated_usd"], 6)
    total["estimated_usd"] = (
        None if errors or incomplete_attempts else total["known_subtotal_usd"]
    )
    return {
        "status": "infrastructure"
        if errors
        else "incomplete"
        if incomplete_attempts
        else "pass",
        "reason": "; ".join(dict.fromkeys(errors + incomplete_attempts)) or None,
        "usage_complete": not errors and not incomplete_attempts,
        "incomplete_attempt_count": len(incomplete_attempts),
        "price_release": PRICE_RELEASE,
        "total": total,
        "cases": cases,
    }


def account_judge_cost(
    evaluations: list[dict[str, Any]],
    *,
    attempted_calls: int,
    usage_unverified: bool = False,
) -> dict[str, Any]:
    if type(attempted_calls) is not int or attempted_calls < 0:
        raise ValueError("attempted judge calls must be a non-negative integer")

    cases = []
    total = {"input_tokens": 0, "output_tokens": 0, "known_subtotal_usd": 0.0}
    recorded_attempts = 0
    incomplete_recorded_attempts = 0
    for evaluation in evaluations:
        case_usage = {"input_tokens": 0, "output_tokens": 0, "known_subtotal_usd": 0.0}
        for judgment in evaluation.get("judgments") or []:
            recorded_attempts += 1
            input_tokens = judgment.get("input_tokens")
            output_tokens = judgment.get("output_tokens")
            estimated_cost_usd = judgment.get("estimated_cost_usd")
            input_complete = type(input_tokens) is int and input_tokens > 0
            output_complete = type(output_tokens) is int and output_tokens > 0
            try:
                known_cost_usd = (
                    float(estimated_cost_usd)
                    if type(estimated_cost_usd) in {int, float}
                    else None
                )
            except OverflowError:
                known_cost_usd = None
            cost_complete = (
                known_cost_usd is not None
                and math.isfinite(known_cost_usd)
                and known_cost_usd >= 0
            )
            if not (input_complete and output_complete and cost_complete):
                incomplete_recorded_attempts += 1
            if input_complete:
                case_usage["input_tokens"] += input_tokens
            if output_complete:
                case_usage["output_tokens"] += output_tokens
            if cost_complete and known_cost_usd is not None:
                case_usage["known_subtotal_usd"] += known_cost_usd
        case_usage["known_subtotal_usd"] = round(case_usage["known_subtotal_usd"], 6)
        total["input_tokens"] += case_usage["input_tokens"]
        total["output_tokens"] += case_usage["output_tokens"]
        total["known_subtotal_usd"] += case_usage["known_subtotal_usd"]
        cases.append({"id": evaluation["id"], **case_usage})

    if attempted_calls < recorded_attempts:
        raise ValueError(
            "attempted judge calls cannot be fewer than recorded judgments"
        )
    # Resumes lack prior attempt counts; over-limit reservations may not reach a provider.
    usage_complete = (
        attempted_calls == recorded_attempts
        and incomplete_recorded_attempts == 0
        and not usage_unverified
    )
    total["known_subtotal_usd"] = round(total["known_subtotal_usd"], 6)
    # Incomplete run accounting cannot certify per-case totals; missing attempts
    # also lack case attribution.
    return {
        "usage_complete": usage_complete,
        "incomplete_attempt_count": (
            None
            if usage_unverified
            else attempted_calls - recorded_attempts + incomplete_recorded_attempts
        ),
        "total": {
            **total,
            "estimated_usd": total["known_subtotal_usd"] if usage_complete else None,
        },
        "cases": [
            {
                **case,
                "estimated_usd": case["known_subtotal_usd"] if usage_complete else None,
            }
            for case in cases
        ],
    }


def evaluate_cost_policy(
    application: dict[str, Any],
    policy: CostPolicy = CostPolicy(),
) -> dict[str, Any]:
    """Apply optional rollout limits without hiding accounting failures."""
    if application.get("status") != "pass":
        incomplete = application.get("status") == "incomplete"
        return {
            "mode": policy.mode,
            "status": "incomplete" if incomplete else "infrastructure",
            "blocking_status": (
                "pass" if incomplete and policy.mode == "report-only" else "fail"
            ),
            "reason": application.get("reason") or "application cost is unavailable",
            "suite_limit_usd": policy.suite_limit_usd,
            "case_limit_usd": policy.case_limit_usd,
            "baseline_min_runs": policy.baseline_min_runs,
        }

    breaches: list[str] = []
    total_usd = float(application["total"]["estimated_usd"])
    if policy.suite_limit_usd is not None and total_usd > policy.suite_limit_usd:
        breaches.append(
            f"suite cost ${total_usd:.6f} exceeds ${policy.suite_limit_usd:.6f}"
        )
    if policy.case_limit_usd is not None:
        breaches.extend(
            f"case {case['id']} cost ${case['estimated_usd']:.6f} exceeds "
            f"${policy.case_limit_usd:.6f}"
            for case in application["cases"]
            if case["estimated_usd"] > policy.case_limit_usd
        )
    return {
        "mode": policy.mode,
        "status": "over_budget" if breaches else "pass",
        "blocking_status": (
            "fail" if breaches and policy.mode == "blocking" else "pass"
        ),
        "reason": "; ".join(breaches) if breaches else None,
        "suite_limit_usd": policy.suite_limit_usd,
        "case_limit_usd": policy.case_limit_usd,
        "baseline_min_runs": policy.baseline_min_runs,
    }
