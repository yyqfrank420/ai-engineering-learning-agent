"""Run a bounded evaluation of input sanitation without the core workflow.

Usage: python -m eval.input_gate_runner --output /explicit/path/report.json
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import uuid

from adapters.database_adapter import fetchone, init_db
from adapters.llm_adapter import _is_kimi_model, _is_openai_model
from api import chat_guards
from config import settings
from eval.input_gate_cases import INPUT_GATE_CASES, InputGateCase


_MAX_CASES = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the real input gate only (at most 10 provider attempts)."
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Case ID; repeat to select several cases",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Explicit JSON report path; its parent must exist",
    )
    return parser


def select_cases(case_ids: list[str]) -> tuple[InputGateCase, ...]:
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Duplicate case IDs are not allowed")
    by_id = {case.id: case for case in INPUT_GATE_CASES}
    unknown = set(case_ids) - by_id.keys()
    if unknown:
        raise ValueError("Unknown case IDs: " + ", ".join(sorted(unknown)))
    selected = (
        tuple(by_id[case_id] for case_id in case_ids)
        if case_ids
        else tuple(INPUT_GATE_CASES)
    )
    if not selected or len(selected) > _MAX_CASES:
        raise ValueError("Select between 1 and 10 cases")
    return selected


def validate_provider_configuration() -> None:
    model = settings.orchestrator_model
    if _is_openai_model(model):
        configured = bool(settings.openai_api_key.strip())
        provider = "OpenAI"
    elif _is_kimi_model(model):
        configured = bool(settings.moonshot_api_key.strip())
        provider = "Moonshot"
    else:
        configured = bool(settings.anthropic_api_key.strip())
        provider = "Anthropic"
    if not configured:
        raise ValueError(f"The configured {provider} provider key is missing")


def _actual_result(error: str | None) -> tuple[str, str | None]:
    if error is None:
        return "accept", None
    if error == chat_guards._INPUT_TOPIC_ERROR:
        return "off_topic", error
    if error == chat_guards._INPUT_SECURITY_ERROR:
        return "unsafe", error
    return "validation_error", chat_guards._INPUT_VALIDATION_ERROR


async def run_evaluation(cases: tuple[InputGateCase, ...]) -> dict:
    if (
        not cases
        or len(cases) > _MAX_CASES
        or len({case.id for case in cases}) != len(cases)
    ):
        raise ValueError("Select 1 to 10 distinct cases")
    validate_provider_configuration()
    model = settings.orchestrator_model
    run_id = str(uuid.uuid4())
    started_at = time.perf_counter()
    preserved = {
        name: getattr(settings, name)
        for name in (
            "data_dir",
            "supabase_db_url",
            "evaluation_run_id",
            "evaluation_provider_attempt_limit",
            "otel_environment",
        )
    }
    results = []
    provider_attempts = 0
    try:
        with TemporaryDirectory(prefix="input-gate-eval-") as scratch:
            settings.data_dir = Path(scratch)
            settings.supabase_db_url = ""
            settings.evaluation_run_id = run_id
            settings.evaluation_provider_attempt_limit = len(cases)
            settings.otel_environment = "evaluation"
            init_db()
            for case in cases:
                case_started_at = time.perf_counter()
                exception_type = None
                try:
                    error = await chat_guards.chat_input_error(
                        case.message,
                        [
                            {"role": role, "content": content}
                            for role, content in case.history
                        ],
                        request_id=f"{run_id}:{case.id}",
                    )
                    actual, public_error = _actual_result(error)
                except Exception as exc:
                    actual = "validation_error"
                    public_error = chat_guards._INPUT_VALIDATION_ERROR
                    exception_type = type(exc).__name__
                results.append(
                    {
                        "id": case.id,
                        "description": case.description,
                        "expected": case.expected_verdict.lower(),
                        "actual": actual,
                        "error": public_error,
                        "exception_type": exception_type,
                        "passed": actual != "validation_error"
                        and actual.upper() == case.expected_verdict,
                        "duration_ms": int(
                            (time.perf_counter() - case_started_at) * 1000
                        ),
                    }
                )
            reservation_count = fetchone(
                "SELECT COUNT(*) AS n FROM rate_limit_events WHERE event_type = ?",
                ("llm_provider_attempt",),
            )
            provider_attempts = reservation_count["n"]
    finally:
        for name, value in preserved.items():
            setattr(settings, name, value)
    passed = sum(result["passed"] for result in results)
    corpus_json = json.dumps(
        [asdict(case) for case in INPUT_GATE_CASES],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "schema_version": "input-gate-evaluation-v1",
        "corpus_sha256": hashlib.sha256(corpus_json.encode("utf-8")).hexdigest(),
        "selected_case_ids": [case.id for case in cases],
        "prompt_version": chat_guards._INPUT_SANITATION_VERSION,
        "prompt_sha256": chat_guards._INPUT_SANITATION_SHA256,
        "model": model,
        "evaluation_run_id": run_id,
        "scope": "input_gate_only",
        "provider_attempt_limit": len(cases),
        "provider_attempts": provider_attempts,
        "results": results,
        "totals": {
            "cases": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
        "limitations": "No core workflow, transport, authentication, tools, judges, or browser validation.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        cases = select_cases(args.case)
        if not args.output.parent.is_dir() or args.output.is_dir():
            raise ValueError("The output must be a file in an existing directory")
        validate_provider_configuration()
    except ValueError as exc:
        parser.error(str(exc))
    report = asyncio.run(run_evaluation(cases))
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    totals = report["totals"]
    print(
        f"Input gate: {totals['passed']}/{totals['cases']} passed; report: {args.output}"
    )
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
