"""Offline checks for bounded gate-only evaluation setup and reporting."""

import json
from pathlib import Path

import pytest

from adapters.llm_adapter import _reserve_evaluation_provider_attempt
from api import chat_guards
from config import settings
from eval import input_gate_runner as runner
from eval.input_gate_cases import InputGateCase


def _case(case_id, expected="ACCEPT"):
    return InputGateCase(
        id=case_id,
        description=f"Case {case_id}",
        message=f"Message {case_id}",
        history=(),
        expected_verdict=expected,
    )


@pytest.fixture
def corpus(monkeypatch):
    cases = (_case("accept"), _case("topic", "OFF_TOPIC"), _case("unsafe", "UNSAFE"))
    monkeypatch.setattr(runner, "INPUT_GATE_CASES", cases)
    monkeypatch.setattr(settings, "orchestrator_model", "claude-opus-5")
    return cases


def test_parser_requires_explicit_report_path():
    with pytest.raises(SystemExit) as exc:
        runner.build_parser().parse_args([])
    assert exc.value.code == 2


@pytest.mark.parametrize("ids", [["missing"], ["accept", "accept"]])
def test_invalid_case_selection_fails_before_provider_calls(
    corpus, monkeypatch, tmp_path, ids
):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Invalid selection attempted provider work")

    monkeypatch.setattr(chat_guards, "chat_input_error", forbidden)
    args = ["--output", str(tmp_path / "report.json")]
    for case_id in ids:
        args += ["--case", case_id]
    with pytest.raises(SystemExit) as exc:
        runner.main(args)
    assert exc.value.code == 2
    assert not (tmp_path / "report.json").exists()


def test_selection_preserves_explicit_order_and_caps_calls(corpus, monkeypatch):
    assert runner.select_cases(["unsafe", "accept"]) == (corpus[2], corpus[0])
    assert runner.select_cases([]) == corpus
    monkeypatch.setattr(
        runner, "INPUT_GATE_CASES", tuple(_case(str(number)) for number in range(11))
    )
    with pytest.raises(ValueError, match="between 1 and 10"):
        runner.select_cases([])


@pytest.mark.parametrize(
    "model,key_name",
    [
        ("claude-opus-5", "anthropic_api_key"),
        ("gpt-5.4", "openai_api_key"),
        ("kimi-k2", "moonshot_api_key"),
    ],
)
def test_requires_the_configured_provider_key(monkeypatch, model, key_name):
    monkeypatch.setattr(settings, "orchestrator_model", model)
    monkeypatch.setattr(settings, key_name, "")
    with pytest.raises(ValueError, match="provider key is missing"):
        runner.validate_provider_configuration()


@pytest.mark.asyncio
async def test_report_separates_validation_failure_and_restores_scratch_settings(
    corpus, monkeypatch
):
    cases = (*corpus, _case("malformed", "UNSAFE"))
    monkeypatch.setattr(runner, "INPUT_GATE_CASES", cases)
    monkeypatch.setattr(settings, "supabase_db_url", "postgresql://must-not-be-used")
    preserved_names = (
        "data_dir",
        "supabase_db_url",
        "evaluation_run_id",
        "evaluation_provider_attempt_limit",
        "otel_environment",
    )
    before = {name: getattr(settings, name) for name in preserved_names}
    observed = []
    scratch_paths = []
    errors = [
        None,
        chat_guards._INPUT_TOPIC_ERROR,
        chat_guards._INPUT_SECURITY_ERROR,
        "malformed response",
    ]

    async def fake_gate(text, history, **telemetry):
        assert settings.supabase_db_url == ""
        assert settings.evaluation_provider_attempt_limit == 4
        assert settings.evaluation_run_id
        assert settings.otel_environment == "evaluation"
        assert settings.sqlite_path.exists()
        scratch_paths.append(settings.data_dir)
        observed.append(telemetry["request_id"])
        _reserve_evaluation_provider_attempt()
        return errors[len(observed) - 1]

    monkeypatch.setattr(chat_guards, "chat_input_error", fake_gate)
    report = await runner.run_evaluation(cases)
    assert report["totals"] == {"cases": 4, "passed": 3, "failed": 1}
    assert [result["actual"] for result in report["results"]] == [
        "accept",
        "off_topic",
        "unsafe",
        "validation_error",
    ]
    assert report["results"][-1]["passed"] is False
    assert report["provider_attempt_limit"] == report["provider_attempts"] == 4
    assert report["scope"] == "input_gate_only"
    assert len(report["corpus_sha256"]) == 64
    assert report["prompt_sha256"] == chat_guards._INPUT_SANITATION_SHA256
    assert all(
        request_id.startswith(report["evaluation_run_id"]) for request_id in observed
    )
    assert {name: getattr(settings, name) for name in preserved_names} == before
    assert not Path(scratch_paths[0]).exists()


@pytest.mark.asyncio
async def test_unexpected_gate_exception_is_failed_without_sensitive_error_text(
    corpus, monkeypatch
):
    async def fake_gate(*args, **kwargs):
        raise RuntimeError("sensitive-secret-value")

    monkeypatch.setattr(chat_guards, "chat_input_error", fake_gate)
    report = await runner.run_evaluation((corpus[2],))
    assert report["totals"]["failed"] == 1
    assert report["results"][0]["actual"] == "validation_error"
    assert report["results"][0]["exception_type"] == "RuntimeError"
    assert "sensitive-secret-value" not in json.dumps(report)


@pytest.mark.asyncio
async def test_scratch_settings_restore_when_database_initialization_fails(
    corpus, monkeypatch
):
    before = (
        settings.data_dir,
        settings.evaluation_run_id,
        settings.evaluation_provider_attempt_limit,
    )

    def failed_init():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(runner, "init_db", failed_init)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await runner.run_evaluation(corpus)
    assert (
        settings.data_dir,
        settings.evaluation_run_id,
        settings.evaluation_provider_attempt_limit,
    ) == before


def test_cli_writes_only_requested_report_and_returns_failure(
    corpus, monkeypatch, tmp_path
):
    async def fake_run(cases):
        assert cases == (corpus[0],)
        return {"totals": {"cases": 1, "passed": 0, "failed": 1}}

    monkeypatch.setattr(runner, "run_evaluation", fake_run)
    output = tmp_path / "requested.json"
    assert runner.main(["--case", "accept", "--output", str(output)]) == 1
    assert json.loads(output.read_text())["totals"]["failed"] == 1
    assert list(tmp_path.iterdir()) == [output]
