import asyncio
import json

import pytest

import agent.explanation_blocks as explanation_blocks


_OVERVIEW_SENTENCE = (
    "This is an overview of the core workflow, with supporting detail simplified."
)


@pytest.mark.asyncio
async def test_one_provider_call_emits_complete_explanation_blocks(monkeypatch):
    calls = []

    async def fake_stream_response(**kwargs):
        calls.append(kwargs)
        yield (
            "text",
            '{"block_id":"overview","title":"In one minute","content":"Start here.",',
        )
        yield ("text", '"related_node_ids":["input"],"evidence_refs":[]}\n')
        yield (
            "text",
            '{"block_id":"controls","title":"Safety","content":"Approve risky writes.",',
        )
        yield (
            "text",
            '"related_node_ids":["approval","invented"],"evidence_refs":["Chapter 4, p.8"]}',
        )
        yield ("done", "")

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="medium",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"input", "approval"},
        allowed_evidence_refs={"Chapter 4, p.8"},
    )

    assert len(calls) == 1
    assert calls[0]["effort"] == "medium"
    assert calls[0]["max_output_tokens"] == 4500
    assert "<untrusted_context>" in calls[0]["system"]
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert [block["title"] for block in blocks[:2]] == ["In one minute", "Safety"]
    assert len(blocks) == 2
    assert blocks[1]["related_node_ids"] == ["approval"]
    assert "## Safety" in response


@pytest.mark.asyncio
async def test_accepted_overview_prefixes_first_valid_block_once_in_stream_and_result(
    monkeypatch,
):
    calls = []
    original_content = f"{_OVERVIEW_SENTENCE}\n\n" + "A" * (
        4000 - len(_OVERVIEW_SENTENCE) - 2
    )

    async def fake_stream_response(**kwargs):
        calls.append(kwargs)
        yield (
            "text",
            json.dumps(
                {
                    "block_id": "runtime",
                    "title": "Runtime",
                    "content": original_content,
                    "related_node_ids": ["entry"],
                    "evidence_refs": [],
                }
            ),
        )
        yield (
            "text",
            '{"block_id":"controls","title":"Controls","content":"Check approvals.",'
            '"related_node_ids":[],"evidence_refs":[]}',
        )

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"entry"},
        accepted_graph_detail="overview",
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(calls) == 1
    assert len(blocks) == 2
    assert blocks[0]["content"].startswith(_OVERVIEW_SENTENCE + "\n\n")
    assert blocks[0]["content"].count(_OVERVIEW_SENTENCE) == 1
    assert len(blocks[0]["content"]) <= 4000
    assert blocks[1]["content"] == "Check approvals."
    assert response == "\n\n".join(
        f"## {block['title']}\n\n{block['content']}" for block in blocks
    )


@pytest.mark.parametrize("detail_level", ["standard", "overview"])
@pytest.mark.asyncio
async def test_accepted_graph_with_no_valid_blocks_gets_ready_to_inspect_fallback(
    monkeypatch, detail_level
):
    async def fake_stream_response(**_kwargs):
        yield ("text", '{"block_id":"invalid","content":"unsupported"}')

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
        accepted_graph_detail=detail_level,
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    assert blocks[0]["title"] == "Diagram ready"
    assert "The diagram is ready to inspect." in blocks[0]["content"]
    assert "retry" not in blocks[0]["content"].lower()
    assert blocks[0]["content"].count(_OVERVIEW_SENTENCE) == int(
        detail_level == "overview"
    )
    assert response == f"## Diagram ready\n\n{blocks[0]['content']}"
    assert "unsupported" not in response


@pytest.mark.parametrize("accepted_graph_detail", [None, "overview"])
@pytest.mark.asyncio
async def test_stream_timeout_preserves_parsed_block_and_closes_provider_iterator(
    monkeypatch, accepted_graph_detail
):
    closed = False

    async def stalled_stream_response(**_kwargs):
        nonlocal closed
        try:
            yield (
                "text",
                '{"block_id":"overview","title":"Overview","content":"Ready",'
                '"related_node_ids":["input"],"evidence_refs":[]}',
            )
            await asyncio.Future()
        finally:
            closed = True

    monkeypatch.setattr(explanation_blocks, "stream_response", stalled_stream_response)

    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=0.01,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"input"},
        accepted_graph_detail=accepted_graph_detail,
    )

    assert closed is True
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    assert response == f"## Overview\n\n{blocks[0]['content']}"
    assert blocks[0]["content"].endswith("Ready")
    assert blocks[0]["content"].count(_OVERVIEW_SENTENCE) == int(
        accepted_graph_detail == "overview"
    )
    assert [
        event["status"] for event in events if event["type"] == "workflow_progress"
    ] == ["degraded"]


@pytest.mark.asyncio
async def test_stream_timeout_before_complete_block_emits_bounded_fallback(monkeypatch):
    closed = False

    async def stalled_stream_response(**_kwargs):
        nonlocal closed
        try:
            yield ("text", '{"block_id":"overview","content":"partial')
            await asyncio.Future()
        finally:
            closed = True

    monkeypatch.setattr(explanation_blocks, "stream_response", stalled_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=0.01,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids={"input"},
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    fallback = blocks[0]
    assert closed is True
    assert fallback["title"] == "Explanation unavailable"
    assert (
        fallback["content"] == "The explanation response was unavailable. Please retry."
    )
    assert "partial" not in response
    assert fallback["evidence_refs"] == []
    assert any(
        event["type"] == "workflow_progress" and event["status"] == "degraded"
        for event in events
    )


@pytest.mark.asyncio
async def test_accepted_overview_timeout_before_valid_block_keeps_diagram_ready(
    monkeypatch,
):
    async def stalled_stream_response(**_kwargs):
        yield ("text", '{"block_id":"overview","content":"partial')
        await asyncio.Future()

    monkeypatch.setattr(explanation_blocks, "stream_response", stalled_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=0.01,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
        accepted_graph_detail="overview",
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    assert blocks[0]["content"].startswith(_OVERVIEW_SENTENCE)
    assert "The diagram is ready to inspect." in blocks[0]["content"]
    assert "Please retry" not in response
    assert response == f"## Diagram ready\n\n{blocks[0]['content']}"
    assert [
        event["status"] for event in events if event["type"] == "workflow_progress"
    ] == ["degraded"]


@pytest.mark.asyncio
async def test_malformed_model_output_emits_server_authored_fallback(
    monkeypatch, caplog
):
    async def fake_stream_response(**_kwargs):
        yield ("text", '{"block_id":"overview","content":"unsupported claim"}')

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    fallback = blocks[0]
    assert (
        fallback["content"] == "The explanation response was unavailable. Please retry."
    )
    assert fallback["evidence_refs"] == []
    assert "unsupported claim" not in response
    assert [record.getMessage() for record in caplog.records] == [
        "explanation_blocks reason_code=invalid_block_shape",
        "explanation_blocks reason_code=no_valid_blocks",
    ]
    assert "unsupported claim" not in caplog.text
    assert any(
        event["type"] == "workflow_progress" and event["status"] == "degraded"
        for event in events
    )


@pytest.mark.asyncio
async def test_preserved_edit_appends_required_completion_sentence_after_parsing(
    monkeypatch,
):
    async def fake_stream_response(**_kwargs):
        yield (
            "text",
            '{"block_id":"result","title":"Result","content":"The prior graph remains.",'
            '"related_node_ids":[],"evidence_refs":[]}',
        )

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[
            {
                "role": "user",
                "content": (
                    "<trusted_turn_result>\n"
                    "Publication state: preserved.\n"
                    "Required completion sentence: The requested diagram edit was not approved, so "
                    "the prior approved diagram remains unchanged.\n"
                    "</trusted_turn_result>"
                ),
            }
        ],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
    )

    sentence = "The requested diagram edit was not approved, so the prior approved diagram remains unchanged."
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    block = blocks[0]
    assert block["content"].endswith(sentence)
    assert response.endswith(sentence)


def test_block_normalisation_rejects_non_array_evidence_refs():
    block = explanation_blocks._normalise_block(
        {
            "block_id": "   ",
            "title": "   ",
            "content": "Useful detail",
            "related_node_ids": "input",
            "evidence_refs": "Chapter 1",
        },
        {"input"},
    )

    assert block is None


def test_block_normalisation_requires_exact_contract_keys():
    block = explanation_blocks._normalise_block(
        {
            "block_id": "overview",
            "title": "Overview",
            "content": "Useful detail",
            "related_node_ids": [],
            "evidence_refs": [],
            "unexpected": "value",
        },
        set(),
    )

    assert block is None


def test_block_normalisation_rejects_unknown_evidence_references():
    block = explanation_blocks._normalise_block(
        {
            "block_id": "overview",
            "title": "Overview",
            "content": "Useful detail",
            "related_node_ids": [],
            "evidence_refs": ["Chapter 1, p.1"],
        },
        set(),
        {"Chapter 2, p.2"},
    )

    assert block is None


@pytest.mark.asyncio
async def test_stream_limits_blocks_and_rejects_duplicate_ids(monkeypatch):
    async def fake_stream_response(**_kwargs):
        for index in range(8):
            block_id = "block_0" if index == 1 else f"block_{index}"
            yield (
                "text",
                (
                    "{"
                    f'"block_id":"{block_id}",'
                    f'"title":"Block {index}",'
                    f'"content":"Content {index}",'
                    '"related_node_ids":[],"evidence_refs":[]}'
                ),
            )

    monkeypatch.setattr(explanation_blocks, "stream_response", fake_stream_response)
    events = []

    async def send(event):
        events.append(event)

    await explanation_blocks.stream_explanation_blocks(
        model="claude-opus-5",
        system="system",
        messages=[{"role": "user", "content": "explain"}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=40,
        telemetry={"operation": "test"},
        send=send,
        graph_version="v1",
        allowed_node_ids=set(),
    )

    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 6
    assert len({block["block_id"] for block in blocks}) == 6
    assert blocks[1]["block_id"] == "block_2"


def test_fallback_block_is_server_authored_and_has_no_evidence_refs():
    block = explanation_blocks._fallback_block("x" * 5000)

    assert block == {
        "block_id": "architecture_explanation",
        "title": "Explanation unavailable",
        "content": "The explanation response was unavailable. Please retry.",
        "related_node_ids": [],
        "evidence_refs": [],
    }


@pytest.mark.asyncio
async def test_cancellation_preserves_emitted_block_without_supplementing(monkeypatch):
    closed = False
    events = []

    async def provider(**_kwargs):
        nonlocal closed
        try:
            yield (
                "text",
                '{"block_id":"answer","title":"Answer","content":"Bounded answer.",'
                '"related_node_ids":[],"evidence_refs":[]}',
            )
            raise asyncio.CancelledError()
        finally:
            closed = True

    async def send(event):
        events.append(event)

    monkeypatch.setattr(explanation_blocks, "stream_response", provider)
    with pytest.raises(asyncio.CancelledError):
        await explanation_blocks.stream_explanation_blocks(
            model="claude-opus-5",
            system="system",
            messages=[{"role": "user", "content": "One focused answer."}],
            effort="low",
            max_output_tokens=4500,
            timeout_seconds=40,
            telemetry={"operation": "test"},
            send=send,
            graph_version="v1",
            allowed_node_ids=set(),
        )
    assert closed is True
    assert len(events) == 1
    assert events[0]["type"] == "explanation_block"
    assert events[0]["content"] == "Bounded answer."


@pytest.mark.parametrize(
    "content,url",
    [
        ("See [source](https://example.com/report).", "https://example.com/report"),
        ("See <https://example.com/report>.", "https://example.com/report"),
        ("See https://example.com/report, then decide.", "https://example.com/report"),
        ("See (https://example.com/report).", "https://example.com/report"),
        (
            "See [source](https://example.com/report?x=1&y=2#section).",
            "https://example.com/report?x=1&y=2#section",
        ),
        (
            "See [source](https://example.com/a_(b_(c))).",
            "https://example.com/a_(b_(c))",
        ),
        ("See https://example.com/a_(b).", "https://example.com/a_(b)"),
        ("See <https://example.com/a_(b)>.", "https://example.com/a_(b)"),
        (
            "See [source](https://example.com/report 'Title').",
            "https://example.com/report",
        ),
        ("See **https://example.com/report**.", "https://example.com/report"),
        ("See https://example.com/report?x=1.", "https://example.com/report?x=1"),
        ("See <https://example.com/report?x=1.>.", "https://example.com/report?x=1."),
        (
            "See [https://example.com/report](https://example.com/report).",
            "https://example.com/report",
        ),
        (
            "See https://example.com/report?next=https://other.example/path.",
            "https://example.com/report?next=https://other.example/path",
        ),
    ],
)
def test_block_accepts_exact_inline_source_urls_without_rewriting(content, url):
    block = {
        "block_id": "source",
        "title": "Source",
        "content": content,
        "related_node_ids": [],
        "evidence_refs": [],
    }
    result = explanation_blocks._normalise_block(block, set(), {url})
    assert result is not None
    assert result["content"] == content


@pytest.mark.parametrize(
    "format_string",
    ["[source]({})", "<{}>", "{}.", "({})", "[source][ref]\n\n[ref]: {}"],
)
def test_block_rejects_unknown_inline_source_even_with_valid_evidence_refs(
    format_string,
):
    allowed = "https://example.com/source"
    invented = "https://example.com/source-invented"
    block = {
        "block_id": "source",
        "title": "Source",
        "content": "Claim " + format_string.format(invented),
        "related_node_ids": [],
        "evidence_refs": [allowed],
    }
    assert explanation_blocks._normalise_block(block, set(), {allowed}) is None


@pytest.mark.asyncio
async def test_captured_research_url_mismatch_never_emits_or_persists_claim(
    monkeypatch,
):
    correct = "https://blog.triherm.com/en/2026/09/25/ai-agents-vs-workflows/"
    incorrect = "https://blog.triherm.com/en/2026/09/25/ai-agents-vs-agents/"
    unrelated = "https://presenc.ai/research/workflows-vs-agents-capability-matrix-2026"
    calls = []
    block = {
        "block_id": "tradeoffs",
        "title": "Agents vs fixed workflows in production",
        "content": "Current guidance frames the choice around task structure, reliability, cost, latency, and control (<"
        + incorrect
        + ">).",
        "related_node_ids": [],
        "evidence_refs": ["Chapter 6, p.299", unrelated],
    }

    async def provider(**kwargs):
        calls.append(kwargs)
        encoded = json.dumps(block)
        for part in (encoded[:50], encoded[50:]):
            yield "text", part

    monkeypatch.setattr(explanation_blocks, "stream_response", provider)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="test",
        system="system",
        messages=[],
        effort="low",
        max_output_tokens=500,
        timeout_seconds=10,
        telemetry={},
        send=send,
        graph_version="approved",
        allowed_node_ids=set(),
        allowed_evidence_refs={correct, unrelated, "Chapter 6, p.299"},
        accepted_graph_detail="standard",
        provider_attempt_limit=1,
    )
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(calls) == 1
    assert len(blocks) == 1
    assert (
        blocks[0]["content"]
        == "The diagram is ready to inspect. I couldn't finish its explanation."
    )
    assert incorrect not in json.dumps(events)
    assert incorrect not in response
    assert "Current guidance" not in response
    assert "The diagram is ready to inspect." in response


@pytest.mark.parametrize(
    "citation,accepted",
    [
        ("(Chapter 6, p.299)", True),
        ("(chapter 6 , p. 299)", True),
        ("(CHAPTER 6, P.299)", True),
        ("(Chapter 6, p.298)", False),
        ("(Chapter 7, p.299)", False),
        ("(Chapter ?, p.299)", False),
    ],
)
def test_inline_book_citations_require_current_supported_page(citation, accepted):
    content = "Supported claim " + citation + " and <https://example.com/source>."
    block = {
        "block_id": "mixed",
        "title": "Mixed sources",
        "content": content,
        "related_node_ids": [],
        "evidence_refs": ["https://example.com/source"],
    }
    result = explanation_blocks._normalise_block(
        block, set(), {"Chapter 6, p.299", "https://example.com/source"}
    )
    assert (result is not None) is accepted
    if result:
        assert result["content"] == content


def test_shared_source_extraction_preserves_canonical_links_without_admitting_snippet_urls():
    from agent.nodes.orchestrator_node import _evidence_reference_allowlist
    from agent.architecture_playbook import _web_evidence_records
    from agent.source_references import source_urls

    canonical = "https://example.com/a_(b)?q=(c)&other=2#section"
    context = f"[Source]({canonical}) includes bare https://untrusted.example/extra in its snippet.\nA second snippet mentions https://untrusted.example/another."
    assert source_urls(context) == {canonical}
    assert source_urls(context, include_bare=True) == {
        canonical,
        "https://untrusted.example/extra",
        "https://untrusted.example/another",
    }
    assert _evidence_reference_allowlist([], context) == {canonical}
    assert [record["display_ref"] for record in _web_evidence_records(context)] == [
        canonical
    ]


def test_shared_source_extraction_resolves_markdown_escaping_without_altering_identity():
    from agent.source_references import source_urls

    assert source_urls(r"[Source](https://example.com/a_\(b\)?x=1&amp;y=2#part)") == {
        "https://example.com/a_(b)?x=1&y=2#part"
    }
    assert source_urls("[Source](https://example.com/end.)") == {
        "https://example.com/end."
    }
    assert source_urls("<https://example.com/end.>") == {"https://example.com/end."}


def test_source_url_query_preserves_non_entity_parameter_names():
    from agent.source_references import source_urls

    literal = "https://example.com/report?x=1&not=1&copy=2#part"
    assert source_urls(f"[Source]({literal})") == {literal}
    assert source_urls(
        "[Source](https://example.com/report?x=1&amp;not=1&amp;copy=2#part)"
    ) == {literal}


@pytest.mark.parametrize(
    "example",
    [
        "`https://example.com/endpoint`",
        "``https://example.com/endpoint`v2``",
        "```http\nhttps://example.com/endpoint\nChapter 99, p.999\n```",
        "~~~http\nhttps://example.com/endpoint\n~~~",
        "````http\n```\nhttps://example.com/endpoint\n````",
    ],
)
def test_code_examples_do_not_claim_source_identity(example):
    content = (
        f"Example endpoint:\n{example}\nThe source supports this (Chapter 6, p.299)."
    )
    block = {
        "block_id": "example",
        "title": "Example",
        "content": content,
        "related_node_ids": [],
        "evidence_refs": ["Chapter 6, p.299"],
    }
    assert (
        explanation_blocks._normalise_block(block, set(), {"Chapter 6, p.299"})[
            "content"
        ]
        == content
    )
    block["content"] += "\nOutside code: <https://example.com/unsupported>"
    assert (
        explanation_blocks._normalise_block(block, set(), {"Chapter 6, p.299"}) is None
    )


@pytest.mark.parametrize(
    "content",
    [
        r"Claim \`[Source](https://invented.example/false)\`.",
        r"Claim \`Chapter 9, p.999\`.",
    ],
)
def test_escaped_backticks_cannot_hide_unsupported_citations(content):
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": content,
        "related_node_ids": [],
        "evidence_refs": [],
    }
    assert explanation_blocks._normalise_block(block, set(), set()) is None


@pytest.mark.parametrize(
    "citation",
    [
        "[source]()",
        "[source](/invented/relative)",
        "[source](https&#58;//invented.example/source)",
        r"[source](https\://invented.example/source)",
        "[source][ref]\n\n[ref]: https://invented.example/source",
        "www.invented.example/source",
    ],
)
def test_markdown_destinations_cannot_bypass_source_identity(citation):
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": "Claim " + citation,
        "related_node_ids": [],
        "evidence_refs": [],
    }
    assert explanation_blocks._normalise_block(block, set(), set()) is None


def test_oversized_model_block_is_rejected_instead_of_truncating_a_citation():
    url = "https://example.com/source"
    content = "x" * 4000 + f" <{url}>"
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": content,
        "related_node_ids": [],
        "evidence_refs": [url],
    }
    assert explanation_blocks._normalise_block(block, set(), {url}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("augmentation", ["overview", "completion", "both"])
async def test_server_augmentation_preserves_boundary_citation(
    monkeypatch, augmentation
):
    url = "https://example.com/source"
    citation = f" <{url}>"
    content = "x" * (4000 - len(citation)) + citation
    sentence = explanation_blocks._PRESERVED_EDIT_COMPLETION_SENTENCE
    message = (
        f"<trusted_turn_result>Publication state: preserved. {sentence}</trusted_turn_result>"
        if augmentation in {"completion", "both"}
        else "explain"
    )

    async def provider(**kwargs):
        yield (
            "text",
            json.dumps(
                {
                    "block_id": "claim",
                    "title": "Claim",
                    "content": content,
                    "related_node_ids": [],
                    "evidence_refs": [url],
                }
            ),
        )

    monkeypatch.setattr(explanation_blocks, "stream_response", provider)
    events = []

    async def send(event):
        events.append(event)

    response = await explanation_blocks.stream_explanation_blocks(
        model="test",
        system="system",
        messages=[{"role": "user", "content": message}],
        effort="low",
        max_output_tokens=4500,
        timeout_seconds=10,
        telemetry={},
        send=send,
        graph_version="approved",
        allowed_node_ids=set(),
        allowed_evidence_refs={url},
        accepted_graph_detail="overview"
        if augmentation in {"overview", "both"}
        else "standard",
    )
    blocks = [event for event in events if event["type"] == "explanation_block"]
    assert len(blocks) == 1
    assert content in blocks[0]["content"]
    assert citation in response
    assert len(blocks[0]["content"]) > 4000
    if augmentation in {"completion", "both"}:
        assert blocks[0]["content"].endswith(sentence)
    if augmentation in {"overview", "both"}:
        assert blocks[0]["content"].startswith(_OVERVIEW_SENTENCE)


@pytest.mark.parametrize("allow_raw", [False, True])
@pytest.mark.parametrize("metadata_raw", [False, True])
def test_unicode_source_identity_is_shared_by_content_allowlist_and_metadata(
    allow_raw, metadata_raw
):
    raw = "https://example.com/étude?q=café#résumé"
    canonical = "https://example.com/%C3%A9tude?q=caf%C3%A9#r%C3%A9sum%C3%A9"
    content = f"Supported claim (<{raw}>)."
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": content,
        "related_node_ids": [],
        "evidence_refs": [raw if metadata_raw else canonical],
    }
    result = explanation_blocks._normalise_block(
        block, set(), {raw if allow_raw else canonical}
    )
    assert result is not None
    assert result["content"] == content
    assert result["evidence_refs"] == [canonical]


@pytest.mark.parametrize(
    "reference",
    [
        "https://example.com/étude-autre",
        "<https://example.com/étude>",
        "[source](https://example.com/étude)",
        "https://example.com/étude trailing text",
        "https://example.com/étude?invented=1",
        "Chapter 6, p. 299",
    ],
)
def test_reference_canonicalization_does_not_accept_partial_or_altered_identity(
    reference,
):
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": "Supported claim.",
        "related_node_ids": [],
        "evidence_refs": [reference],
    }
    assert (
        explanation_blocks._normalise_block(
            block, set(), {"https://example.com/%C3%A9tude", "Chapter 6, p.299"}
        )
        is None
    )


@pytest.mark.parametrize(
    "chapter,page,expected",
    [
        (6, 299, "Chapter 6, p.299"),
        (None, 1, "Book, p.1"),
        (6, None, "Chapter 6"),
        (None, None, "Book excerpt"),
    ],
)
def test_book_reference_owners_share_known_location_labels(chapter, page, expected):
    from agent.source_references import book_references, format_book_reference
    from agent.architecture_playbook import _book_evidence_records
    from agent.nodes.orchestrator_node import (
        _format_chunks,
        _evidence_reference_allowlist,
    )
    from graph.runtime import _book_refs

    chunk = {"chapter": chapter, "page_number": page, "text": "Source text"}
    assert format_book_reference(chapter, page) == expected
    assert _format_chunks([chunk]) == f"[1] {expected}\nSource text"
    assert _evidence_reference_allowlist([chunk], "") == {expected}
    assert _book_evidence_records([chunk])[0][0]["display_ref"] == expected
    assert _book_refs([chunk]) == [expected]
    assert book_references(f"Claim ({expected}).") == {expected}
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": f"Claim ({expected}).",
        "related_node_ids": [],
        "evidence_refs": [expected],
    }
    assert explanation_blocks._normalise_block(block, set(), {expected}) is not None


@pytest.mark.parametrize("field", ["chapter", "page_number"])
@pytest.mark.parametrize("bad", [True, "6", 1.5, 0, -1])
def test_book_reference_formatter_rejects_malformed_location_without_guessing(
    field, bad
):
    from agent.source_references import format_book_reference

    values = {"chapter": 6, "page_number": 299, field: bad}
    with pytest.raises(ValueError, match=field):
        format_book_reference(**values)


@pytest.mark.parametrize(
    "citation",
    [
        "Chapter None, p.1",
        "Chapter ?, p.1",
        "Chapter 6, p.None",
        "Chapter 6, p.?",
        "Book, p.None",
        "Book, p.?",
        "Chapter None",
        "Chapter ?",
    ],
)
def test_placeholder_book_citations_are_rejected_even_without_metadata(citation):
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": f"Claim ({citation}).",
        "related_node_ids": [],
        "evidence_refs": [],
    }
    assert (
        explanation_blocks._normalise_block(
            block, set(), {"Book, p.1", "Chapter 6", "Book excerpt"}
        )
        is None
    )


def test_reference_parser_does_not_treat_chapter_discussion_as_location_citation():
    from agent.source_references import book_references

    assert (
        book_references("Chapter 6 discusses agents. The book excerpt explains it.")
        == set()
    )


@pytest.mark.parametrize(
    "location", ["299.5", "-299", "+299", "299-300", "299e2", "299abc", "299,5"]
)
@pytest.mark.parametrize(
    "shape", ["Chapter 6, p.{}", "Book, p.{}", "Chapter {}, p.299", "Chapter {}"]
)
def test_entire_book_location_token_must_match_source_identity(location, shape):
    from agent.source_references import book_references

    citation = shape.format(location)
    content = f"Claim ({citation})."
    assert book_references(content) == {citation}
    assert book_references(content, include_malformed=False) == set()
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": content,
        "related_node_ids": [],
        "evidence_refs": [],
    }
    assert (
        explanation_blocks._normalise_block(
            block,
            set(),
            {"Chapter 6, p.299", "Book, p.299", "Chapter 299, p.299", "Chapter 299"},
        )
        is None
    )


@pytest.mark.parametrize(
    "content,expected",
    [
        ("Claim (Chapter 6, p.299).", "Chapter 6, p.299"),
        ("Claim [Chapter 6, p.299].", "Chapter 6, p.299"),
        ("Claim Chapter 6, p.299.", "Chapter 6, p.299"),
        ("Claim (Book, p.299).", "Book, p.299"),
        ("Claim [Book, p.299].", "Book, p.299"),
        ("Claim [Chapter 6].", "Chapter 6"),
        ("Claim (Chapter 6.)", "Chapter 6"),
        ("Claim [Book excerpt].", "Book excerpt"),
    ],
)
def test_book_location_boundaries_preserve_valid_citations(content, expected):
    from agent.source_references import book_references

    assert book_references(content) == {expected}
    assert book_references(content, include_malformed=False) == {expected}
    block = {
        "block_id": "claim",
        "title": "Claim",
        "content": content,
        "related_node_ids": [],
        "evidence_refs": [],
    }
    assert explanation_blocks._normalise_block(block, set(), {expected}) is not None


@pytest.mark.parametrize(
    ("changes", "reason_code"),
    [
        ({"unexpected": "private-sentinel"}, "invalid_block_shape"),
        ({"content": "   "}, "empty_content"),
        ({"content": "private-sentinel" * 300}, "overlong_content"),
        (
            {"content": "[Evidence](https://private-sentinel.example/source)"},
            "unsupported_inline_references",
        ),
        ({"evidence_refs": "private-sentinel"}, "invalid_metadata_evidence_refs"),
        (
            {"evidence_refs": ["https://private-sentinel.example/source"]},
            "invalid_metadata_evidence_refs",
        ),
    ],
)
def test_block_rejection_logs_only_fixed_reason_code(changes, reason_code, caplog):
    block = {
        "block_id": "private-sentinel",
        "title": "private-sentinel",
        "content": "private-sentinel",
        "related_node_ids": [],
        "evidence_refs": [],
        **changes,
    }
    assert explanation_blocks._normalise_block(block, set(), set()) is None
    assert [record.getMessage() for record in caplog.records] == [
        f"explanation_blocks reason_code={reason_code}"
    ]
    assert "private-sentinel" not in caplog.text


def test_valid_block_logs_no_rejection(caplog):
    block = {
        "block_id": "overview",
        "title": "Overview",
        "content": "A supported claim (Chapter 6, p.299).",
        "related_node_ids": [],
        "evidence_refs": ["Chapter 6, p.299"],
    }
    assert (
        explanation_blocks._normalise_block(block, set(), {"Chapter 6, p.299"}) == block
    )
    assert not caplog.records
