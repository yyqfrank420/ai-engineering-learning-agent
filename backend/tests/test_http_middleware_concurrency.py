"""HTTP observability must not block the request event loop or response body."""

import asyncio
import threading

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

import main


@pytest.fixture
def http_app(monkeypatch):
    logs = []
    monkeypatch.setattr(main, "enqueue_analytics_event", lambda **_fields: None)
    monkeypatch.setattr(
        main, "record_http_request_log", lambda **fields: logs.append(fields)
    )
    monkeypatch.setattr(
        main, "verify_access_token", lambda _token: {"sub": "test-user"}
    )
    app = main.create_app(load_resources=False)

    @app.get("/test/cheap")
    async def cheap():
        return {"ok": True}

    return app, logs


def start_request(app, path="/test/cheap", *, authenticated=False):
    messages = []
    body_delivered = asyncio.Event()
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get(
            "more_body", False
        ):
            body_delivered.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("test", 80),
        "client": ("test", 1234),
        "headers": [(b"authorization", b"Bearer synthetic")] if authenticated else [],
    }
    return asyncio.create_task(app(scope, receive, send)), messages, body_delivered


async def wait_entered(event):
    async def poll():
        while not event.is_set():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=1)


@pytest.mark.asyncio
async def test_blocked_token_verification_leaves_other_requests_responsive(
    http_app, monkeypatch
):
    app, logs = http_app
    entered, release = threading.Event(), threading.Event()
    verifier_threads = []

    def verify(_token):
        verifier_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(2), "test must release verifier"
        return {"sub": "test-user"}

    monkeypatch.setattr(main, "verify_access_token", verify)
    pending, messages, _body = start_request(app, authenticated=True)
    try:
        await wait_entered(entered)
        cheap, _messages, delivered = start_request(app)
        await asyncio.wait_for(delivered.wait(), timeout=1)
        await asyncio.wait_for(cheap, timeout=1)
        assert not pending.done()
        assert len(verifier_threads) == 1
        assert verifier_threads[0] != threading.get_ident()
    finally:
        release.set()
        await asyncio.wait_for(pending, timeout=2)
    assert messages[0]["status"] == 200
    assert [row["user_id"] for row in logs] == [None, "test-user"]


@pytest.mark.asyncio
async def test_blocked_log_writer_runs_after_body_and_leaves_loop_responsive(
    http_app, monkeypatch
):
    app, logs = http_app
    entered, release = threading.Event(), threading.Event()
    writer_threads = []

    def write(**fields):
        writer_threads.append(threading.get_ident())
        if fields["path"] == "/test/blocked":
            entered.set()
            assert release.wait(2), "test must release log writer"
        logs.append(fields)

    @app.get("/test/blocked")
    async def blocked():
        return {"ok": True}

    monkeypatch.setattr(main, "record_http_request_log", write)
    pending, messages, delivered = start_request(app, "/test/blocked")
    try:
        await wait_entered(entered)
        assert delivered.is_set()
        assert messages[0]["status"] == 200
        assert not pending.done()
        cheap, _messages, cheap_delivered = start_request(app)
        await asyncio.wait_for(cheap_delivered.wait(), timeout=1)
        await asyncio.wait_for(cheap, timeout=1)
        assert all(thread != threading.get_ident() for thread in writer_threads)
    finally:
        release.set()
        await asyncio.wait_for(pending, timeout=2)
    assert len(logs) == 2
    assert len([row for row in logs if row["path"] == "/test/blocked"]) == 1


@pytest.mark.asyncio
async def test_status_headers_metadata_metrics_and_existing_background_preserved(
    http_app, monkeypatch
):
    app, logs = http_app
    background = []
    metrics = []
    monkeypatch.setattr(
        main, "record_request_metrics", lambda **fields: metrics.append(fields)
    )

    @app.get("/test/metadata")
    async def metadata(request: Request):
        request.state.thread_id = "thread-1"
        request.state.client_request_id = "client-1"
        return JSONResponse(
            {"accepted": True},
            status_code=202,
            background=BackgroundTask(background.append, "original"),
        )

    task, messages, delivered = start_request(app, "/test/metadata", authenticated=True)
    await asyncio.wait_for(task, timeout=2)
    assert delivered.is_set()
    assert background == ["original"]
    assert messages[0]["status"] == 202
    headers = dict(messages[0]["headers"])
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert len(logs) == 1
    row = logs[0]
    assert row["status_code"] == 202 and row["user_id"] == "test-user"
    assert row["metadata"]["thread_id"] == "thread-1"
    assert row["metadata"]["client_request_id"] == "client-1"
    assert row["metadata"]["request_id"].encode() == headers[b"x-request-id"]
    assert metrics[0]["status_code"] == 202


@pytest.mark.asyncio
async def test_optional_log_failure_warns_without_changing_response(
    http_app, monkeypatch, caplog
):
    app, _logs = http_app

    def failed_write(**_fields):
        raise RuntimeError("synthetic log failure")

    monkeypatch.setattr(main, "record_http_request_log", failed_write)
    task, messages, delivered = start_request(app)
    await asyncio.wait_for(task, timeout=2)
    assert delivered.is_set() and messages[0]["status"] == 200
    assert "HTTP request telemetry write failed: RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_response_less_exception_logs_in_worker_and_preserves_error(
    http_app, monkeypatch
):
    app, logs = http_app
    writer_threads = []

    def write(**fields):
        writer_threads.append(threading.get_ident())
        logs.append(fields)

    @app.get("/test/raised")
    async def raised():
        raise ValueError("synthetic endpoint failure")

    monkeypatch.setattr(main, "record_http_request_log", write)
    task, messages, delivered = start_request(app, "/test/raised")
    with pytest.raises(ValueError, match="synthetic endpoint failure"):
        await asyncio.wait_for(task, timeout=2)
    assert delivered.is_set() and messages[0]["status"] == 500
    assert len(logs) == 1 and logs[0]["status_code"] == 500
    assert writer_threads[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_existing_background_exception_still_propagates(http_app):
    app, logs = http_app

    def failed_background():
        raise ValueError("synthetic background failure")

    @app.get("/test/background-failure")
    async def background_failure():
        return JSONResponse({"ok": True}, background=BackgroundTask(failed_background))

    task, messages, delivered = start_request(app, "/test/background-failure")
    with pytest.raises(ValueError, match="synthetic background failure"):
        await asyncio.wait_for(task, timeout=2)
    assert delivered.is_set() and messages[0]["status"] == 200
    assert len(logs) == 1
