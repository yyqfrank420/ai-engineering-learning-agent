import json

import pytest

from eval.quality_corpus import CORPUS_PATH, ResearchSourceContract, load_corpus


def _write_corpus(tmp_path, raw):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _approve_cases(raw):
    for case in raw["cases"]:
        case["approval"] = {
            "status": "approved",
            "reviewer": "reviewer",
            "reviewed_at": "2026-08-02T12:00:00Z",
            "review_run_id": "github-run-123",
            "reviewed_grades": {
                dimension: "pass" for dimension in case["rubric_dimensions"]
            },
        }


def test_current_research_contracts_are_pinned_and_pending_review():
    corpus = load_corpus()

    assert corpus.corpus_version == "2026-09-28.v2"
    assert corpus.release_identity == "browser-rubric-v6"
    assert corpus.approval.status == "pending_human_review"
    assert corpus.approval.approved_manifest_sha256 is None

    research = corpus.by_id["research"]
    research_contract = research.deterministic.research_source_contract
    assert research_contract is not None
    assert research_contract.required_url_prefixes == [
        "https://www.anthropic.com/engineering/building-effective-agents"
    ]
    assert research_contract.minimum_url_prefix_matches == 1
    assert research.approval.status == "pending_human_review"

    conflict = corpus.by_id["instruction-conflict"]
    conflict_contract = conflict.deterministic.research_source_contract
    assert conflict_contract is not None
    assert conflict_contract.required_url_prefixes == [
        "https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html",
        "https://www.ncsc.gov.uk/blog-post/prompt-injection-is-not-sql-injection",
    ]
    assert conflict_contract.minimum_url_prefix_matches == 2
    assert conflict_contract.required_evidence_markers == [
        "ignore all previous instructions",
        "reveal your system prompt",
    ]
    assert conflict_contract.minimum_evidence_marker_matches == 1
    assert conflict.approval.status == "pending_human_review"


@pytest.mark.parametrize(
    "invalid_prefix",
    [
        "http://www.anthropic.com/engineering/building-effective-agents",
        "https://@www.anthropic.com/engineering/building-effective-agents",
        "https://www.anthropic.com:invalid/engineering/building-effective-agents",
        "https://www.anthropic.com:99999/engineering/building-effective-agents",
        "https://www.anthropic.com/engineering/building-effective-agents#fragment",
        "https://www.anthropic.com/engineering/building-effective-agents?",
        "https://www.anthropic.com/engineering/building-effective-agents\n",
        "https://www.anthropic.com\\@evil.example/path",
        "https://bad host.example/path",
        "https://bad..host.example/path",
        "https://-bad.host.example/path",
        "https://bad-.host.example/path",
        "https://example.com/bad%ZZ",
        "https://example.com/article/../other",
        "https://example.com/article/%2e%2e/other",
        "https://www.anthropic.com/",
        "https://www.anthropic.com/engineering/building-effective-agents?latest=true",
    ],
)
def test_research_source_contract_rejects_unstable_url_prefixes(
    tmp_path, invalid_prefix
):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    research = next(case for case in raw["cases"] if case["id"] == "research")
    research["deterministic"]["research_source_contract"]["required_url_prefixes"] = [
        invalid_prefix
    ]

    with pytest.raises(ValueError, match="stable path"):
        load_corpus(path=_write_corpus(tmp_path, raw))


def test_every_web_citation_case_requires_a_source_contract(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    research = next(case for case in raw["cases"] if case["id"] == "research")
    research["deterministic"].pop("research_source_contract")

    with pytest.raises(ValueError, match="must define a research source contract"):
        load_corpus(path=_write_corpus(tmp_path, raw))


def test_retrieved_instruction_conflict_requires_hostile_evidence_markers(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    conflict = next(
        case for case in raw["cases"] if case["id"] == "instruction-conflict"
    )
    contract = conflict["deterministic"]["research_source_contract"]
    contract["required_evidence_markers"] = []
    contract["minimum_evidence_marker_matches"] = 0

    with pytest.raises(ValueError, match="must require hostile evidence markers"):
        load_corpus(path=_write_corpus(tmp_path, raw))


def test_pending_does_not_claim_immutable_calibration_identity():
    calibration = load_corpus().approval.calibration

    assert calibration.evidence_run_id is None
    assert calibration.evidence_commit_sha is None
    assert calibration.evidence_sha256 is None
    assert calibration.judge_provider == "anthropic"
    assert calibration.judge_model == "claude-sonnet-5"


def test_approved_corpus_requires_immutable_calibration_identity(tmp_path):
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    _approve_cases(raw)
    raw["approval"].update(
        {
            "status": "approved",
            "reviewed_by": "reviewer",
            "reviewed_at": "2026-08-02T12:00:00Z",
            "calibration": {
                "judge_release": raw["approval"]["calibration"]["judge_release"],
                "judge_provider": "anthropic",
                "agreement": 0.9,
                "critical_false_passes": 0,
                "evaluated_at": "2026-08-02T12:00:00Z",
                "evidence_run_id": None,
                "evidence_commit_sha": None,
                "evidence_sha256": None,
                "judge_model": None,
            },
        }
    )

    with pytest.raises(ValueError, match="judge and immutable browser evidence"):
        load_corpus(path=_write_corpus(tmp_path, raw))


@pytest.mark.parametrize(
    "second_prefix",
    [
        "https://WWW.ANTHROPIC.COM/engineering/building-effective-agents/",
        "https://www.anthropic.com:443/engineering/building-effective-agents",
    ],
)
def test_source_contract_rejects_duplicate_normalized_urls(second_prefix):
    with pytest.raises(ValueError, match="prefixes must be unique"):
        ResearchSourceContract(
            required_url_prefixes=[
                "https://www.anthropic.com/engineering/building-effective-agents",
                second_prefix,
            ],
            minimum_url_prefix_matches=2,
        )


def test_source_contract_preserves_case_sensitive_paths():
    contract = ResearchSourceContract(
        required_url_prefixes=[
            "https://example.com/Article",
            "https://example.com/article",
        ],
        minimum_url_prefix_matches=2,
    )
    assert len(contract.required_url_prefixes) == 2


@pytest.mark.parametrize(
    "markers,minimum",
    [
        (["ignore all previous instructions", " IGNORE ALL PREVIOUS INSTRUCTIONS "], 1),
        ([" "], 1),
        (["ignore all previous instructions"], 2),
    ],
)
def test_source_contract_rejects_invalid_evidence_markers(markers, minimum):
    with pytest.raises(ValueError):
        ResearchSourceContract(
            required_url_prefixes=["https://example.com/article"],
            minimum_url_prefix_matches=1,
            required_evidence_markers=markers,
            minimum_evidence_marker_matches=minimum,
        )


def test_pinned_source_titles_survive_research_query_length_limit():
    from agent.nodes.research_worker import _normalise_topic

    corpus = load_corpus()
    assert "Building Effective Agents" in _normalise_topic(
        corpus.by_id["research"].steps[0].prompt
    )
    conflict_query = _normalise_topic(
        corpus.by_id["instruction-conflict"].steps[0].prompt
    )
    assert "LLM Prompt Injection Prevention Cheat Sheet" in conflict_query
    assert "Prompt injection is not SQL injection" in conflict_query
