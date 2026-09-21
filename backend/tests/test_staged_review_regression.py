"""Offline boundaries using retained evidence, not proof of model acceptance."""

import json
from pathlib import Path

import pytest

from agent.nodes import staged_graph_gate as gate
from agent.stream_utils import StructuredLLMResponse


@pytest.fixture(scope="module")
def marketing_review():
    return json.loads(
        (Path(__file__).parent / "fixtures/staged_review_35636149205.json").read_text()
    )


@pytest.mark.parametrize("candidate", ["initial_candidate", "corrected_candidate"])
def test_review_prompt_preserves_real_records_and_retry_response_index(
    marketing_review, candidate
):
    records = marketing_review[candidate]
    evidence = {
        "candidate_components": marketing_review["accepted_components"],
        "candidate_context": marketing_review["candidate_context"],
    }
    prompt = gate._prompt(
        gate="connections",
        user_request=marketing_review["request"],
        evidence_bundle=evidence,
        resolved_maturity="production",
        candidate_records=records,
        required_production_guarantees=(),
    )
    decoder = json.JSONDecoder()
    numbered, _ = decoder.raw_decode(prompt.split("Immutable candidate records: ")[1])
    captured_evidence, _ = decoder.raw_decode(prompt.split("Evidence bundle: ")[1])

    assert captured_evidence == evidence
    assert len(numbered) == 78
    assert [row["record_index"] for row in numbered] == list(range(len(records)))
    assert [row["record"] for row in numbered] == records
    retry_rows = [row for row in numbered if "NOT_FOUND" in row["record"]["label"]]
    assert len(retry_rows) == 1
    assert retry_rows[0]["record_index"] == 52
    assert retry_rows[0]["record"] == records[52]
    assert retry_rows[0]["record"] not in [records[i] for i in (55, 56, 58)]


def test_review_parser_retains_both_blockers_in_synthetic_combined_response(
    marketing_review,
):
    rules = marketing_review["first_review"]["checked_rules"]
    rows = {
        code: {
            "satisfied": True,
            "reason": "Synthetic satisfied row for parser coverage.",
            "record_indexes": [],
        }
        for code in rules
    }
    first = marketing_review["first_review"]["findings"][0]
    late = marketing_review["second_review"]["findings"][0]
    # Combine historical reasons with the verified retry-response index. This
    # response is synthesized locally and does not represent a live model review.
    blockers = [first, {**late, "record_indexes": [52]}]
    for finding in blockers:
        rows[finding["rule_code"]] = {
            "satisfied": False,
            "reason": finding["reason"],
            "record_indexes": finding["record_indexes"],
        }
    result = gate._review_result(
        StructuredLLMResponse(
            text=json.dumps(
                {
                    "rule_reviews": [
                        {"rule_code": code, **row} for code, row in rows.items()
                    ]
                }
            ),
            finish_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
            provider="test",
            model="test",
        ),
        schema=gate._response_schema(rule_codes=rules),
        rule_codes=rules,
        records=marketing_review["initial_candidate"],
    )

    assert result["approved"] is False
    assert result["terminal"] is False
    assert result["diagnostics"] == []
    assert result["findings"] == blockers
    assert result["rule_reviews"] == rows


def test_historical_correction_left_late_review_contracts_unchanged(marketing_review):
    initial = marketing_review["initial_candidate"]
    corrected = marketing_review["corrected_candidate"]
    first = marketing_review["first_review"]
    late = marketing_review["second_review"]
    changed = {
        index
        for index, (before, after) in enumerate(zip(initial, corrected, strict=True))
        if before != after
    }

    assert changed == set(first["findings"][0]["record_indexes"]) == {59, 60, 61}
    assert first["review_identity"] == late["review_identity"]
    assert first["checked_rules"] == late["checked_rules"]
    assert first["findings"][0]["rule_code"] != late["findings"][0]["rule_code"]
    assert not changed.intersection(late["findings"][0]["record_indexes"])
    assert initial[52] == corrected[52]
