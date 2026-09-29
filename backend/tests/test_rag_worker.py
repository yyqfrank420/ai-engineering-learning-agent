import json

import pytest

from agent.nodes.rag_worker import _assess_retrieval_relevance, _meaningful_terms, rag_worker_node
from config import settings


class _Tool:
    name = "rag_search"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return json.dumps(self.payload)


@pytest.mark.asyncio
async def test_rag_worker_invokes_search_tool_and_returns_chunks(monkeypatch):
    monkeypatch.setattr(settings, "rag_top_k", 7)
    events = []
    chunks = [{"text": "Agents plan and use tools for tasks.", "chapter": 6}]
    tool = _Tool(chunks)

    async def send(event):
        events.append(event)

    result = await rag_worker_node(
        {
            "user_message": "How do agents use tools?",
            "send": send,
        },
        [tool],
    )

    assert events[0] == {"type": "worker_status", "worker": "rag", "status": "Searching book…"}
    assert [(event["phase"], event["status"]) for event in events if event["type"] == "workflow_progress"] == [
        ("book", "active"), ("book", "complete"),
    ]
    assert tool.calls == [{"query": "How do agents use tools?", "k": 7}]
    assert result["rag_chunks"] == chunks
    assert result["retrieval_relevance"] == "strong"
    assert result["retrieval_notice"] == ""


@pytest.mark.asyncio
async def test_rag_worker_searches_the_restored_design_query_for_terse_followups(monkeypatch):
    monkeypatch.setattr(settings, "rag_top_k", 5)
    tool = _Tool([{"text": "Growth measurement and controlled action loop."}])

    async def send(_event):
        return None

    await rag_worker_node(
        {
            "user_message": "expand this",
            "design_query": "growth marketing multi-agent system expand this",
            "send": send,
        },
        [tool],
    )

    assert tool.calls == [{
        "query": "growth marketing multi-agent system expand this",
        "k": 5,
    }]


@pytest.mark.asyncio
async def test_rag_worker_handles_missing_search_tool_as_weak_retrieval():
    events = []

    async def send(event):
        events.append(event)

    result = await rag_worker_node({"user_message": "marketing agents", "send": send}, [])

    assert result["rag_chunks"] == []
    assert result["retrieval_relevance"] == "weak"
    assert "closest book patterns" in result["retrieval_notice"]


@pytest.mark.asyncio
async def test_rag_worker_emits_bounded_source_evidence_for_allowlisted_internal_identity(monkeypatch):
    monkeypatch.setattr(settings, "db_schema", "public")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "eval@example.com")
    events = []
    chunks = [{
        "text": "source text " * 1_000,
        "book": "AI Engineering",
        "chapter": 4,
        "chapter_title": "Evaluate AI Systems",
        "section": "Design Your Evaluation Pipeline",
        "page_number": 224,
        "parent_chunk_id": "ai-engineering:4:224:4",
    }]

    async def send(event):
        events.append(event)

    await rag_worker_node(
        {
            "user_message": "How should evaluation data grow?",
            "user_email": "eval@example.com",
            "send": send,
        },
        [_Tool(chunks)],
    )

    evidence = next(event for event in events if event["type"] == "retrieval_evidence")
    assert evidence["type"] == "retrieval_evidence"
    assert evidence["query"] == "How should evaluation data grow?"
    assert evidence["chunks"][0]["page_number"] == 224
    assert len(evidence["chunks"][0]["text"]) == 4_000


@pytest.mark.asyncio
async def test_rag_worker_does_not_emit_source_evidence_for_non_allowlisted_identity(monkeypatch):
    monkeypatch.setattr(settings, "db_schema", "public")
    monkeypatch.setattr(settings, "internal_test_email_allowlist_raw", "eval@example.com")
    events = []

    async def send(event):
        events.append(event)

    await rag_worker_node(
        {
            "user_message": "How should evaluation data grow?",
            "user_email": "customer@example.com",
            "send": send,
        },
        [_Tool([{"text": "source"}])],
    )

    assert {event["type"] for event in events} == {"worker_status", "workflow_progress"}


def test_retrieval_relevance_flags_indirect_single_hit():
    relevance, notice = _assess_retrieval_relevance(
        "How does this apply to sales operations?",
        [{"text": "Agents plan steps."}],
    )

    assert relevance == "weak"
    assert "nearest book concepts" in notice


def test_retrieval_relevance_flags_low_coverage_even_with_multiple_chunks():
    relevance, notice = _assess_retrieval_relevance(
        "warehouse pricing analytics governance",
        [{"text": "Agents plan steps."}, {"text": "Tools execute actions."}],
    )

    assert relevance == "weak"
    assert "closest book ideas" in notice


def test_retrieval_relevance_treats_stopword_only_query_as_strong_when_chunks_exist():
    assert _assess_retrieval_relevance("how is it and why", [{"text": "anything"}]) == ("strong", "")


def test_meaningful_terms_removes_stop_words_and_short_tokens():
    assert _meaningful_terms("How do AI agents use SQL in ops?") == ["agents", "use", "sql", "ops"]


@pytest.mark.asyncio
async def test_book_search_failure_closes_live_activity():
    events = []

    class BrokenTool:
        name = "rag_search"

        def invoke(self, _args):
            raise RuntimeError("index unavailable")

    async def send(event):
        events.append(event)

    with pytest.raises(RuntimeError, match="index unavailable"):
        await rag_worker_node({"user_message": "agents", "send": send}, [BrokenTool()])
    assert [event["status"] for event in events if event["type"] == "workflow_progress"] == [
        "active", "degraded",
    ]


@pytest.mark.asyncio
async def test_book_and_web_search_can_progress_independently(monkeypatch):
    import asyncio
    import threading

    from agent.pipeline_steps import run_parallel_research_phase

    events = []
    release_book = threading.Event()
    web_finished = asyncio.Event()

    class WaitingTool:
        name = "rag_search"

        def invoke(self, _args):
            if not release_book.wait(timeout=3):
                raise TimeoutError("web search could not progress")
            return json.dumps([{"text": "Agents use tools."}])

    async def send(event):
        events.append(event)
        if event.get("phase") == "web" and event.get("status") == "complete":
            web_finished.set()

    async def search_stream(**_kwargs):
        yield "web_search_sources", json.dumps([{
            "href": "https://example.com/agents", "title": "Agents", "body": "Agents use tools.",
            "query": "agents", "backend": "anthropic_web_search",
        }])

    monkeypatch.setattr("agent.nodes.research_worker.stream_response", search_stream)
    task = asyncio.create_task(run_parallel_research_phase(
        {"user_message": "agents", "send": send}, [WaitingTool()],
    ))
    try:
        await asyncio.wait_for(web_finished.wait(), timeout=2)
        book_events = [event["status"] for event in events if event.get("phase") == "book"]
        assert book_events == ["active"]
    finally:
        release_book.set()
        result = await task
    assert result["research_status"] == "ready"
    assert [event["status"] for event in events if event.get("phase") == "book"] == ["active", "complete"]
