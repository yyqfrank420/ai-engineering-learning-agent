"""Provider thinking stays bounded, ephemeral, and separate from answer data."""

import asyncio
import json
from uuid import UUID

import pytest

from agent import explanation_blocks, stream_utils


async def _call(boundary, send, *, enabled=True):
    common = {
        "model": "test-model", "system": "system", "messages": [], "effort": "low",
        "send": send, "thinking_phase": ("review" if boundary == "structured" else "explain") if enabled else None,
    }
    if boundary == "plain":
        common.pop("thinking_phase")
        return await stream_utils.stream_llm(**common, temperature=0, stream_thinking=enabled)
    if boundary == "structured":
        return (await stream_utils.stream_structured_llm(
            **common, response_schema={"type": "object"}, temperature=0,
        )).text
    return await explanation_blocks.stream_explanation_blocks(
        **common, max_output_tokens=1000, timeout_seconds=30, telemetry={},
        graph_version="v1", allowed_node_ids=set(),
    )


def _text(boundary):
    return '{}' if boundary == "structured" else json.dumps({
        "block_id": "answer", "title": "Answer", "content": "Final answer.",
        "related_node_ids": [], "evidence_refs": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["structured", "explanation", "plain"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_thinking_fragments_are_opt_in_bounded_and_separate(monkeypatch, boundary, enabled):
    events = []
    calls = []

    async def send(event):
        events.append(event)

    async def response(**kwargs):
        calls.append(kwargs)
        for _ in range(2700):
            yield "thinking", "abc"
        yield "text", _text(boundary)
        yield "signature", "SECRET_SIGNATURE"
        yield "response_metadata", '{"model":"test-model","finish_reason":"stop"}'

    module = stream_utils if boundary in {"structured", "plain"} else explanation_blocks
    monkeypatch.setattr(module, "stream_response", response)
    result = await _call(boundary, send, enabled=enabled)
    thinking = [e for e in events if e["type"] == "thinking_delta"]
    assert len(calls) == 1
    assert "send" not in calls[0]
    assert "thinking_phase" not in calls[0]
    assert "abc" not in result
    assert "SECRET_SIGNATURE" not in repr(events)
    if enabled:
        assert "".join(e["content"] for e in thinking) == ("abc" * 2700)[:8000]
        assert len(thinking) == 2667
        assert thinking[0]["content"] == "abc"
        assert thinking[-1]["content"] == "ab"
        assert thinking[0]["reset"] is True
        assert all("reset" not in e for e in thinking[1:])
        assert len({e["operation_id"] for e in thinking}) == 1
        UUID(thinking[0]["operation_id"])
        assert all(set(e) <= {"type", "operation_id", "phase", "content", "reset"} for e in thinking)
    else:
        assert thinking == []


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["structured", "explanation", "plain"])
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_thinking_tail_flushes_without_replacing_provider_failure(monkeypatch, boundary, failure):
    events = []
    started = asyncio.Event()
    original = RuntimeError("provider failed")

    async def send(event):
        events.append(event)

    async def response(**_kwargs):
        yield "thinking", "Short tail"
        assert [e["content"] for e in events if e["type"] == "thinking_delta"] == ["Short tail"]
        started.set()
        if failure == "error":
            raise original
        await asyncio.Future()

    module = stream_utils if boundary in {"structured", "plain"} else explanation_blocks
    monkeypatch.setattr(module, "stream_response", response)
    task = asyncio.create_task(_call(boundary, send))
    await started.wait()
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError) as error:
            await task
        assert error.value is original
    assert [e["content"] for e in events if e["type"] == "thinking_delta"] == ["Short tail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["structured", "explanation", "plain"])
async def test_provider_switch_flushes_and_starts_a_separate_operation(monkeypatch, boundary):
    events = []

    async def send(event):
        events.append(event)

    async def response(**_kwargs):
        yield "thinking", "First provider"
        yield "provider_switch", "second"
        yield "thinking", "Second provider"
        yield "text", _text(boundary)

    module = stream_utils if boundary in {"structured", "plain"} else explanation_blocks
    monkeypatch.setattr(module, "stream_response", response)
    await _call(boundary, send)
    thinking = [e for e in events if e["type"] == "thinking_delta"]
    assert [e["content"] for e in thinking] == ["First provider", "Second provider"]
    assert thinking[0]["operation_id"] != thinking[1]["operation_id"]
    assert all(e["reset"] is True for e in thinking)


@pytest.mark.asyncio
async def test_no_send_retains_only_structured_text(monkeypatch):
    async def response(**_kwargs):
        yield "thinking", "Discard me"
        yield "text", '{}'

    monkeypatch.setattr(stream_utils, "stream_response", response)
    assert await _call("structured", None) == '{}'


@pytest.mark.asyncio
async def test_thinking_delivery_failure_does_not_mask_provider_error(monkeypatch):
    original = ValueError("provider error")

    async def send(_event):
        raise RuntimeError("closed transport")

    async def response(**_kwargs):
        yield "thinking", "Tail"
        raise original

    monkeypatch.setattr(stream_utils, "stream_response", response)
    with pytest.raises(ValueError) as error:
        await _call("structured", send)
    assert error.value is original
