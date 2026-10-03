import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from adapters import web_search_adapter as search
from config import settings


@pytest.fixture
def records(monkeypatch):
    telemetry = []
    analytics = []
    metrics = []
    reservations = []
    monkeypatch.setattr(settings, "moonshot_api_key", "offline-key")
    monkeypatch.setattr(
        search, "record_llm_telemetry", lambda **kwargs: telemetry.append(kwargs)
    )
    monkeypatch.setattr(
        search, "enqueue_analytics_event", lambda **kwargs: analytics.append(kwargs)
    )
    monkeypatch.setattr(
        search, "record_llm_metrics", lambda **kwargs: metrics.append(kwargs)
    )
    monkeypatch.setattr(
        search,
        "current_trace_context",
        lambda: {"trace_id": "trace", "span_id": "span"},
    )
    monkeypatch.setattr(
        search,
        "_reserve_evaluation_provider_attempt",
        lambda: reservations.append(True),
    )
    return SimpleNamespace(
        telemetry=telemetry,
        analytics=analytics,
        metrics=metrics,
        reservations=reservations,
    )


@pytest.mark.asyncio
async def test_search_posts_one_normalized_query_and_records_real_results(
    monkeypatch, records
):
    calls = []
    actual = {
        "title": "Actual title",
        "url": "https://source.example",
        "snippet": "Actual snippet",
    }

    async def post(path, **kwargs):
        assert records.reservations == [True]
        calls.append((path, kwargs))
        return httpx.Response(
            200, json={"search_results": [{**actual, "text": "IGNORED_PROVIDER_BODY"}]}
        )

    monkeypatch.setattr(search, "_get_kimi_client", lambda: SimpleNamespace(post=post))
    result = await search.search_sources(
        "  private\n query  ",
        telemetry={
            "user_id": "user",
            "thread_id": "thread",
            "metadata": {
                "request_id": "request",
                "client_request_id": "client",
                "search_api_version": "web_research_v2",
                "query": "private query",
            },
        },
    )
    assert result == [actual]
    assert calls == [
        (
            "/tools/search",
            {
                "cast_to": httpx.Response,
                "body": {
                    "text_query": "private query",
                    "limit": 6,
                    "timeout_seconds": 20,
                    "include_content": False,
                },
                "options": {
                    "timeout": 30.0,
                    "max_retries": 0,
                    "follow_redirects": False,
                },
            },
        )
    ]
    record = records.telemetry[0]
    assert (record["operation"], record["provider"], record["model"]) == (
        "web_research",
        "moonshot",
        "moonshot-web-search-basic",
    )
    assert record["thread_id"] == "thread" and record["user_id"] == "user"
    metadata = record["metadata"]
    assert (
        metadata["web_search_requests"] == 1
        and metadata["web_search_usage_complete"] is True
    )
    assert metadata["attempts"][0]["web_search_requests"] == 1
    assert metadata["provider_attempts"] == len(metadata["attempts"]) == 1
    assert (
        metadata["request_id"] == "request"
        and metadata["client_request_id"] == "client"
    )
    assert metadata["trace_id"] == "trace" and metadata["span_id"] == "span"
    assert metadata["search_api_version"] == "web_research_v2"
    assert all(
        metadata[field] == 0
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )
    assert records.analytics[0]["request_id"] == "request"
    assert len(records.metrics) == len(records.analytics) == 1
    assert "private query" not in json.dumps(
        [records.telemetry, records.analytics, records.metrics]
    )
    assert "IGNORED_PROVIDER_BODY" not in json.dumps(
        [records.telemetry, records.analytics, records.metrics]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,exception,count",
    [
        ({"search_results": []}, None, 0),
        ({"search_results": [{"title": "", "url": "", "snippet": ""}]}, None, 1),
        ({"search_results": [None]}, search.WebSearchProtocolError, 1),
        (
            {"search_results": [{"title": "actual", "url": "url"}]},
            search.WebSearchProtocolError,
            1,
        ),
        (
            {"search_results": [{"title": "actual", "url": "url", "snippet": 3}]},
            search.WebSearchProtocolError,
            1,
        ),
        ({"search_results": {}}, search.WebSearchProtocolError, None),
        ({}, search.WebSearchProtocolError, None),
        ([], search.WebSearchProtocolError, None),
    ],
)
async def test_search_fee_uses_provider_array_before_local_filter(
    monkeypatch, records, body, exception, count
):
    async def post(*_args, **_kwargs):
        return httpx.Response(200, json=body)

    monkeypatch.setattr(search, "_get_kimi_client", lambda: SimpleNamespace(post=post))
    if exception:
        with pytest.raises(exception):
            await search.search_sources("query")
    else:
        await search.search_sources("query")
    metadata = records.telemetry[0]["metadata"]
    assert metadata["web_search_requests"] == count
    assert metadata["web_search_usage_complete"] is (count is not None)
    assert metadata["attempts"][0]["usage_complete"] is (count is not None)
    assert len(records.telemetry) == len(records.reservations) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["missing_key", "missing_client", "setup_error", "quota"]
)
async def test_search_setup_and_quota_fail_before_post(monkeypatch, records, kind):
    from adapters.llm_adapter import EvaluationProviderAttemptLimitExceeded

    async def forbidden(*_args, **_kwargs):
        pytest.fail("preflight failure dispatched provider POST")

    monkeypatch.setattr(
        search, "_get_kimi_client", lambda: SimpleNamespace(post=forbidden)
    )
    expected = search.WebSearchUnavailable
    if kind == "missing_key":
        monkeypatch.setattr(settings, "moonshot_api_key", "")
    elif kind == "missing_client":
        monkeypatch.setattr(search, "_get_kimi_client", lambda: None)
    elif kind == "setup_error":

        def broken():
            raise ValueError("local setup")

        monkeypatch.setattr(search, "_get_kimi_client", broken)
        expected = ValueError
    else:

        def reject():
            raise EvaluationProviderAttemptLimitExceeded("quota exhausted")

        monkeypatch.setattr(search, "_reserve_evaluation_provider_attempt", reject)
        expected = EvaluationProviderAttemptLimitExceeded
    with pytest.raises(expected):
        await search.search_sources("query")
    assert records.reservations == [] and records.telemetry == []


@pytest.mark.asyncio
@pytest.mark.parametrize("query,expected", [(" ", ValueError), (None, TypeError)])
async def test_search_invalid_query_fails_before_client_setup(
    monkeypatch, records, query, expected
):
    monkeypatch.setattr(
        search,
        "_get_kimi_client",
        lambda: pytest.fail("invalid query initialized client"),
    )
    with pytest.raises(expected):
        await search.search_sources(query)
    assert records.reservations == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,count",
    [
        (200, 1),
        (201, 0),
        (204, 0),
        (401, 0),
        (429, 0),
        (504, 0),
        ("timeout", None),
        ("connection", None),
        ("malformed", None),
        ("invalid_encoding", None),
    ],
)
async def test_search_real_sdk_post_has_no_retry_or_posthog_content_capture(
    monkeypatch, records, outcome, count
):
    from posthog.ai.openai import AsyncOpenAI

    posts = []
    captures = []
    posthog = SimpleNamespace(
        capture=lambda *args, **kwargs: captures.append((args, kwargs))
    )

    async def handle(request):
        assert records.reservations == [True]
        posts.append(request)
        if outcome == "timeout":
            raise httpx.ReadTimeout("PRIVATE_REQUEST_BODY", request=request)
        if outcome == "connection":
            raise httpx.ConnectError("PRIVATE_REQUEST_BODY", request=request)
        if outcome == "invalid_encoding":
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"\xff"
            )
        if outcome == "malformed":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"PRIVATE_MALFORMED_BODY",
            )
        if outcome != 200:
            return httpx.Response(
                outcome,
                json={
                    "error": {"message": "PRIVATE_ERROR_BODY", "type": "provider_error"}
                },
            )
        return httpx.Response(
            200,
            json={
                "search_results": [
                    {
                        "title": "actual",
                        "url": "https://source.example",
                        "snippet": "snippet",
                    }
                ]
            },
        )

    client = AsyncOpenAI(
        api_key="offline-key",
        base_url="https://api.moonshot.ai/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        posthog_client=posthog,
    )
    monkeypatch.setattr(search, "_get_kimi_client", lambda: client)
    try:
        if outcome == 200:
            assert await search.search_sources("PRIVATE_QUERY") == [
                {
                    "title": "actual",
                    "url": "https://source.example",
                    "snippet": "snippet",
                }
            ]
        else:
            with pytest.raises(search.WebSearchUnavailable) as caught:
                await search.search_sources("PRIVATE_QUERY")
            if isinstance(outcome, int):
                assert caught.value.status_code == outcome
        assert len(posts) == len(records.reservations) == len(records.telemetry) == 1
        assert posts[0].url.path == "/v1/tools/search"
        assert captures == []
        metadata = records.telemetry[0]["metadata"]
        assert metadata["web_search_requests"] == count
        assert metadata["web_search_usage_complete"] is (count is not None)
        assert "PRIVATE_" not in json.dumps(
            [records.telemetry, records.analytics, records.metrics]
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_search_cancellation_records_unknown_fee_and_propagates(
    monkeypatch, records
):
    entered = asyncio.Event()
    closed = []

    async def post(*_args, **_kwargs):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    monkeypatch.setattr(search, "_get_kimi_client", lambda: SimpleNamespace(post=post))
    task = asyncio.create_task(search.search_sources("query"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [True]
    metadata = records.telemetry[0]["metadata"]
    assert (
        metadata["web_search_requests"] is None
        and metadata["web_search_usage_complete"] is False
    )
    assert records.telemetry[0]["error_type"] == "CancelledError"
    assert len(records.reservations) == len(records.telemetry) == 1


@pytest.mark.asyncio
async def test_search_programming_fault_stays_visible(monkeypatch, records):
    async def broken(*_args, **_kwargs):
        raise TypeError("local programming error")

    monkeypatch.setattr(
        search, "_get_kimi_client", lambda: SimpleNamespace(post=broken)
    )
    with pytest.raises(TypeError, match="local programming error"):
        await search.search_sources("query")
    assert records.telemetry[0]["metadata"]["web_search_requests"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "redirect",
    ["https://api.moonshot.ai/v1/redirect", "https://other.invalid/redirect"],
)
async def test_search_disables_default_sdk_redirects_before_another_post(
    monkeypatch, records, redirect
):
    from openai import DefaultAsyncHttpxClient
    from posthog.ai.openai import AsyncOpenAI

    requests = []
    captures = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(
            307, headers={"location": redirect}, content=b"PRIVATE_REDIRECT_BODY"
        )

    http_client = DefaultAsyncHttpxClient(transport=httpx.MockTransport(handle))
    assert http_client.follow_redirects is True
    client = AsyncOpenAI(
        api_key="offline-key",
        base_url="https://api.moonshot.ai/v1",
        max_retries=0,
        http_client=http_client,
        posthog_client=SimpleNamespace(
            capture=lambda *args, **kwargs: captures.append((args, kwargs))
        ),
    )
    monkeypatch.setattr(search, "_get_kimi_client", lambda: client)
    try:
        with pytest.raises(search.WebSearchUnavailable) as caught:
            await search.search_sources("PRIVATE_QUERY")
        assert caught.value.status_code == 307
        assert len(requests) == len(records.reservations) == len(records.telemetry) == 1
        assert str(requests[0].url) == "https://api.moonshot.ai/v1/tools/search"
        assert records.telemetry[0]["metadata"]["web_search_requests"] == 0
        assert records.telemetry[0]["metadata"]["web_search_usage_complete"] is True
        assert captures == []
        assert "PRIVATE_" not in json.dumps(
            [records.telemetry, records.analytics, records.metrics]
        )
    finally:
        await client.close()
