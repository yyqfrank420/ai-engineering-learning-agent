import json

import pytest

from api.node_selected_service import build_chip_prompt, stream_suggested_questions


def test_chip_prompt_retains_all_messages_and_complete_content():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message-{i}:" + "x" * 500} for i in range(74)]
    prompt = build_chip_prompt("Evaluation", "Checks quality.", history)[0]["content"]
    assert json.dumps(history, ensure_ascii=False) in prompt


def test_chip_prompt_handles_empty_history():
    assert "Conversation history (untrusted context): []" in build_chip_prompt("Evaluation", "Checks quality.", [])[0]["content"]


def test_build_chip_prompt_includes_node_description_and_history():
    prompt = build_chip_prompt(
        "Evaluation",
        "Checks model output quality.",
        [{"role": "user", "content": "Explain agents"}],
    )

    assert prompt == [
        {
            "role": "user",
            "content": (
                "Node: Evaluation\n"
                "Description: Checks model output quality.\n"
                'Conversation history (untrusted context): [{"role": "user", "content": "Explain agents"}]\n\n'
                "Generate 3 chips."
            ),
        }
    ]


@pytest.mark.asyncio
async def test_stream_suggested_questions_parses_json_and_forwards_provider_switch(monkeypatch):
    async def fake_stream_response_compat(*_args, **_kwargs):
        yield ("provider_switch", "openai")
        yield ("text", "Here are chips: ")
        yield ("text", '["Explain evaluation", "Expand graph", "Compare metrics", "Extra"]')

    monkeypatch.setattr("api.node_selected_service.stream_response_compat", fake_stream_response_compat)

    events = [
        event
        async for event in stream_suggested_questions(
            "Evaluation",
            "Checks output quality.",
            [],
            telemetry={"operation": "node_selected_chips"},
        )
    ]

    assert events == [
        {"type": "provider_switch", "provider": "openai"},
        {
            "type": "suggested_questions",
            "questions": ["Explain evaluation", "Expand graph", "Compare metrics"],
        },
        {"type": "done"},
    ]


@pytest.mark.asyncio
async def test_stream_suggested_questions_handles_non_json_model_output(monkeypatch):
    async def fake_stream_response_compat(*_args, **_kwargs):
        yield ("text", "not json")

    monkeypatch.setattr("api.node_selected_service.stream_response_compat", fake_stream_response_compat)

    events = [
        event
        async for event in stream_suggested_questions(
            "Evaluation",
            "Checks output quality.",
            [],
        )
    ]

    assert events == [
        {"type": "suggested_questions", "questions": []},
        {"type": "done"},
    ]
