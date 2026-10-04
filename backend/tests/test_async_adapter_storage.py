"""Storage waits must preserve provider admission and leave the loop responsive."""

import asyncio
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from adapters import llm_adapter as llm
from adapters import web_search_adapter as search
from config import settings


_trace = ContextVar("adapter_storage_test_trace", default=None)


@pytest.fixture
def adapters(monkeypatch):
    rows = []
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(settings, "moonshot_api_key", "offline")
    monkeypatch.setattr(llm, "_reserve_evaluation_provider_attempt", lambda: None)
    monkeypatch.setattr(search, "_reserve_evaluation_provider_attempt", lambda: None)
    monkeypatch.setattr(
        "storage.telemetry_store.record_llm_telemetry", lambda **row: rows.append(row)
    )
    monkeypatch.setattr(search, "record_llm_telemetry", lambda **row: rows.append(row))
    monkeypatch.setattr("analytics.events.enqueue_analytics_event", lambda **_: None)
    monkeypatch.setattr(search, "enqueue_analytics_event", lambda **_: None)
    monkeypatch.setattr("observability.record_llm_metrics", lambda **_: None)
    monkeypatch.setattr(search, "record_llm_metrics", lambda **_: None)

    def context():
        return {"trace_id": _trace.get(), "span_id": "span"}

    monkeypatch.setattr("observability.current_trace_context", context)
    monkeypatch.setattr(search, "current_trace_context", context)
    return rows


def _provider(
    monkeypatch, route, calls, outcome="success", entered=None, before_result=None
):
    async def started():
        calls.append(_trace.get())
        if entered is not None:
            entered.set()
        if outcome == "cancel":
            await asyncio.Event().wait()
        if outcome == "error":
            raise TypeError("offline provider error")
        if before_result is not None:
            await before_result()

    async def anthropic(_kwargs):
        await started()
        yield SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(
                usage=SimpleNamespace(input_tokens=11, output_tokens=0)
            ),
        )
        yield SimpleNamespace(
            type="message_delta",
            usage=SimpleNamespace(output_tokens=3),
            delta=SimpleNamespace(stop_reason="end_turn"),
        )

    async def kimi(*_args, **_kwargs):
        await started()
        yield ("usage", json.dumps({"input_tokens": 11, "output_tokens": 3}))

    async def post(*_args, **_kwargs):
        await started()
        return httpx.Response(
            200,
            json={
                "search_results": [
                    {
                        "title": "Source",
                        "url": "https://source.example",
                        "snippet": "Evidence",
                    }
                ]
            },
        )

    monkeypatch.setattr(llm, "_anthropic_stream_once", anthropic)
    monkeypatch.setattr(llm, "_kimi_stream", kimi)
    monkeypatch.setattr(search, "_get_kimi_client", lambda: SimpleNamespace(post=post))


async def _run(route):
    telemetry = {
        "operation": "offline",
        "user_id": "user",
        "thread_id": "thread",
        "metadata": {"request_id": "request", "client_request_id": "client"},
    }
    if route == "search":
        return await search.search_sources("offline query", telemetry=telemetry)
    return [
        event
        async for event in llm.stream_response(
            "kimi-k3" if route == "kimi" else "claude-opus-5",
            "system",
            [],
            telemetry=telemetry,
            allow_fallback=False,
            provider_attempt_limit=1,
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["anthropic", "kimi", "search"])
@pytest.mark.parametrize("outcome", ["allow", "exhausted", "cancel"])
async def test_reservation_wait_keeps_loop_responsive_and_gates_dispatch(
    monkeypatch, adapters, route, outcome
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    calls = []
    contexts = []
    _provider(monkeypatch, route, calls)

    def reserve():
        contexts.append(_trace.get())
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(3), "test did not release storage wait"
            if outcome == "exhausted":
                raise llm.EvaluationProviderAttemptLimitExceeded(
                    "offline budget exhausted"
                )
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr(
        search if route == "search" else llm,
        "_reserve_evaluation_provider_attempt",
        reserve,
    )
    token = _trace.set("trace")
    task = asyncio.create_task(_run(route))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        # This cheap coroutine completes while the storage worker is still blocked.
        assert (
            await asyncio.wait_for(asyncio.sleep(0, result="responsive"), 1)
            == "responsive"
        )
        assert calls == []
        assert not task.done()
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        release.set()
        await asyncio.wait_for(finished.wait(), 2)
        if outcome == "exhausted":
            with pytest.raises(llm.EvaluationProviderAttemptLimitExceeded):
                await task
        elif outcome == "allow":
            await task
        assert contexts == ["trace"]
        assert calls == (["trace"] if outcome == "allow" else [])
        assert len(adapters) == (1 if outcome == "allow" else 0)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        _trace.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["anthropic", "kimi", "search"])
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_telemetry_wait_keeps_loop_responsive_and_preserves_rows(
    monkeypatch, adapters, route, outcome
):
    loop = asyncio.get_running_loop()
    provider_entered = asyncio.Event()
    writer_entered = asyncio.Event()
    release = threading.Event()
    rows = []
    calls = []
    _provider(monkeypatch, route, calls, outcome, provider_entered)

    def write(**row):
        assert _trace.get() == "trace"
        loop.call_soon_threadsafe(writer_entered.set)
        assert release.wait(3), "test did not release storage wait"
        rows.append(row)

    monkeypatch.setattr("storage.telemetry_store.record_llm_telemetry", write)
    monkeypatch.setattr(search, "record_llm_telemetry", write)
    token = _trace.set("trace")
    task = asyncio.create_task(_run(route))
    try:
        if outcome == "cancel":
            await asyncio.wait_for(provider_entered.wait(), 2)
            task.cancel()
        await asyncio.wait_for(writer_entered.wait(), 2)
        assert (
            await asyncio.wait_for(asyncio.sleep(0, result="responsive"), 1)
            == "responsive"
        )
        assert not task.done()
        release.set()
        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await task
        elif outcome == "error":
            with pytest.raises(TypeError, match="offline provider error"):
                await task
        else:
            await task
        assert calls == ["trace"]
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == ("success" if outcome == "success" else "error")
        assert (
            row["error_type"]
            == {"success": None, "error": "TypeError", "cancel": "CancelledError"}[
                outcome
            ]
        )
        assert row["user_id"] == "user" and row["thread_id"] == "thread"
        metadata = row["metadata"]
        assert metadata["trace_id"] == "trace"
        assert (
            metadata["request_id"] == "request"
            and metadata["client_request_id"] == "client"
        )
        assert metadata["provider_attempts"] == 1
        if route == "search":
            assert metadata["web_search_requests"] == (
                1 if outcome == "success" else None
            )
            assert metadata["web_search_usage_complete"] is (outcome == "success")
        else:
            assert metadata["input_tokens"] == (11 if outcome == "success" else 0)
            assert metadata["output_tokens"] == (3 if outcome == "success" else 0)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        _trace.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["anthropic", "kimi", "search"])
async def test_cancelling_dispatched_telemetry_write_preserves_one_billing_row(
    monkeypatch, adapters, route
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()
    rows = []
    calls = []
    _provider(monkeypatch, route, calls)

    def write(**row):
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(3), "test did not release storage wait"
            rows.append(row)
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr("storage.telemetry_store.record_llm_telemetry", write)
    monkeypatch.setattr(search, "record_llm_telemetry", write)
    task = asyncio.create_task(_run(route))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        await asyncio.wait_for(finished.wait(), 2)
        assert len(rows) == 1
        assert rows[0]["status"] == "success"
        metadata = rows[0]["metadata"]
        assert metadata["provider_attempts"] == 1
        assert metadata["attempts"][0]["status"] == "success"
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["anthropic", "kimi", "search"])
async def test_queued_telemetry_survives_cancellation_before_worker_starts(
    monkeypatch, adapters, route
):
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    release = threading.Event()
    occupied = asyncio.Event()
    queued = asyncio.Event()
    rows = []
    calls = []
    original_run = loop.run_in_executor
    original_to_thread = asyncio.to_thread

    def run_in_executor(selected_executor, func, *args):
        return original_run(
            executor if selected_executor is None else selected_executor, func, *args
        )

    def occupy():
        loop.call_soon_threadsafe(occupied.set)
        assert release.wait(3), "test did not release executor"

    async def saturate():
        executor.submit(occupy)
        await occupied.wait()

    def write(**row):
        rows.append(row)

    async def to_thread(func, *args, **kwargs):
        if func is write:
            queued.set()
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(loop, "run_in_executor", run_in_executor)
    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    monkeypatch.setattr("storage.telemetry_store.record_llm_telemetry", write)
    monkeypatch.setattr(search, "record_llm_telemetry", write)
    _provider(monkeypatch, route, calls, before_result=saturate)
    task = asyncio.create_task(_run(route))
    try:
        await asyncio.wait_for(queued.wait(), 2)
        assert rows == []
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert len(rows) == 1
        assert rows[0]["status"] == "success"
        assert rows[0]["metadata"]["provider_attempts"] == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["anthropic", "kimi", "search"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_writer_failure_is_logged_without_retry_or_losing_cancellation(
    monkeypatch, adapters, caplog, route, cancel
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    writes = []
    calls = []
    _provider(monkeypatch, route, calls)

    def write(**row):
        writes.append(row)
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(3), "test did not release storage wait"
        raise RuntimeError("offline write error")

    monkeypatch.setattr("storage.telemetry_store.record_llm_telemetry", write)
    monkeypatch.setattr(search, "record_llm_telemetry", write)
    task = asyncio.create_task(_run(route))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if cancel:
            task.cancel()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        else:
            await task
        assert len(calls) == len(writes) == 1
        assert "telemetry write failed: RuntimeError" in caplog.text
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["anthropic", "kimi", "search"])
async def test_anyio_cancelled_scope_drains_one_row_without_shield_spin(
    monkeypatch, adapters, route
):
    import anyio

    loop = asyncio.get_running_loop()
    provider_entered = asyncio.Event()
    writer_entered = asyncio.Event()
    release = threading.Event()
    rows = []
    calls = []
    cancellations = []
    shield_calls = []
    original_shield = asyncio.shield
    _provider(monkeypatch, route, calls, outcome="cancel", entered=provider_entered)

    def shield(future):
        shield_calls.append(True)
        return original_shield(future)

    def write(**row):
        loop.call_soon_threadsafe(writer_entered.set)
        assert release.wait(3), "test did not release storage wait"
        rows.append(row)

    async def run():
        try:
            await _run(route)
        except asyncio.CancelledError:
            cancellations.append(True)
            raise

    monkeypatch.setattr(asyncio, "shield", shield)
    monkeypatch.setattr("storage.telemetry_store.record_llm_telemetry", write)
    monkeypatch.setattr(search, "record_llm_telemetry", write)
    try:
        async with anyio.create_task_group() as group:
            group.start_soon(run)
            await asyncio.wait_for(provider_entered.wait(), 2)
            # Finalization starts inside the already-cancelled provider scope.
            with anyio.CancelScope(shield=True):
                group.cancel_scope.cancel()
                await asyncio.wait_for(writer_entered.wait(), 2)
                await asyncio.sleep(0.05)
                assert rows == []
                assert cancellations == []
                assert len(shield_calls) <= 2
                release.set()
        assert cancellations == [True]
        assert len(rows) == len(calls) == 1
        assert rows[0]["error_type"] == "CancelledError"
        assert rows[0]["metadata"]["provider_attempts"] == 1
        assert len(shield_calls) <= 2
    finally:
        release.set()
