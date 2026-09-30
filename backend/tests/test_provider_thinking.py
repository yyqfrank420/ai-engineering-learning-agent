"""Provider reasoning stays internal across every shared streaming boundary."""

import asyncio
import json

import pytest

from agent import explanation_blocks, stream_utils


async def _call(boundary, send):
    common = {
        "model": "test-model",
        "system": "system",
        "messages": [],
        "effort": "low",
    }
    if boundary == "plain":
        return await stream_utils.stream_llm(
            **common, send=send, temperature=0, stream_deltas=True
        )
    if boundary == "structured":
        return (
            await stream_utils.stream_structured_llm(
                **common,
                response_schema={"type": "object"},
                temperature=0,
            )
        ).text
    return await explanation_blocks.stream_explanation_blocks(
        **common,
        send=send,
        max_output_tokens=1000,
        timeout_seconds=30,
        telemetry={},
        graph_version="v1",
        allowed_node_ids=set(),
    )


def _text(boundary):
    return (
        "{}"
        if boundary == "structured"
        else json.dumps(
            {
                "block_id": "answer",
                "title": "Answer",
                "content": "Final answer.",
                "related_node_ids": [],
                "evidence_refs": [],
            }
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["structured", "explanation", "plain"])
async def test_reasoning_and_signature_never_enter_public_events_or_answer(
    monkeypatch, boundary
):
    events = []
    calls = []

    async def send(event):
        events.append(event)

    async def response(**kwargs):
        calls.append(kwargs)
        for _ in range(2700):
            yield "thinking", "PRIVATE_CAPABILITY_DELIBERATION"
        yield "text", _text(boundary)
        yield "signature", "SECRET_SIGNATURE"
        yield "response_metadata", '{"model":"test-model","finish_reason":"stop"}'

    module = stream_utils if boundary in {"structured", "plain"} else explanation_blocks
    monkeypatch.setattr(module, "stream_response", response)
    result = await _call(boundary, send)
    assert len(calls) == 1
    assert "PRIVATE_CAPABILITY_DELIBERATION" not in result + repr(events)
    assert "SECRET_SIGNATURE" not in result + repr(events)
    assert not any(event["type"] == "thinking_delta" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["structured", "explanation", "plain"])
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_reasoning_does_not_change_provider_failure_or_cancellation(
    monkeypatch, boundary, failure
):
    events = []
    started = asyncio.Event()
    original = RuntimeError("provider failed")

    async def send(event):
        events.append(event)

    async def response(**_kwargs):
        yield "thinking", "PRIVATE_THOUGHT"
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
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["structured", "explanation", "plain"])
async def test_provider_switch_retains_answer_behavior_without_reasoning(
    monkeypatch, boundary
):
    events = []

    async def send(event):
        events.append(event)

    async def response(**_kwargs):
        yield "thinking", "PRIVATE_FIRST"
        yield "provider_switch", "second"
        yield "thinking", "PRIVATE_SECOND"
        yield "text", _text(boundary)

    module = stream_utils if boundary in {"structured", "plain"} else explanation_blocks
    monkeypatch.setattr(module, "stream_response", response)
    result = await _call(boundary, send)
    assert "PRIVATE_" not in result + repr(events)
    assert not any(event["type"] == "thinking_delta" for event in events)
    assert any(event["type"] == "provider_switch" for event in events) == (
        boundary != "structured"
    )
