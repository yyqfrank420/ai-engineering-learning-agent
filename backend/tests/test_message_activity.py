import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from adapters.database_adapter import execute, init_db
from storage.message_activity import MessageActivity, decode_message_activity
from storage.message_store import get_history, get_messages
from storage.profile_store import upsert_profile
from storage.thread_store import create_thread, delete_thread, get_completed_turn, persist_turn


def activity(text="I am checking the diagram."):
    return {
        "duration_ms": 1000,
        "steps": [{"sequence": 3, "kind": "update", "phase": "review",
                   "status": "complete", "text": text, "elapsed_ms": 500}],
    }


def setup_thread():
    init_db()
    upsert_profile("owner", "owner@example.com")
    return create_thread("owner")["id"]


def save_turn(thread_id, value=None, request_id="request"):
    return persist_turn(
        "owner", thread_id, title="Diagram", user_content="Draw it",
        assistant_content="Here is the answer.", graph_data=None,
        client_request_id=request_id, activity=value,
    )


def test_activity_roundtrip_preserves_canonical_idempotent_winner_and_ownership(temp_data_dir):
    thread_id = setup_thread()
    value = activity("I checked café 東京.\nEverything requested is present.")
    assert save_turn(thread_id, value)
    assert save_turn(thread_id, activity("Another attempt"))
    messages = get_messages("owner", thread_id)
    assert len(messages) == 2
    assert messages[0]["activity"] is None
    assert messages[1]["activity"] == value
    assert get_completed_turn("owner", thread_id, "request")["activity"] == value
    assert get_completed_turn("other", thread_id, "request") is None
    assert get_messages("other", thread_id) == []
    assert get_history("owner", thread_id) == [
        {"role": "user", "content": "Draw it"},
        {"role": "assistant", "content": "Here is the answer."},
    ]
    delete_thread("owner", thread_id)
    assert get_messages("owner", thread_id) == []


def test_concurrent_retries_preserve_one_complete_activity(temp_data_dir):
    thread_id = setup_thread()
    values = [activity("First run"), activity("Second run")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda value: save_turn(thread_id, value), values))
    messages = get_messages("owner", thread_id)
    assert len(messages) == 2
    assert messages[-1]["activity"] in values
    assert get_completed_turn("owner", thread_id, "request")["activity"] == messages[-1]["activity"]


@pytest.mark.parametrize("value", [
    {"duration_ms": True, "steps": []},
    {"duration_ms": -1, "steps": []},
    {"duration_ms": 86_400_001, "steps": []},
    {"duration_ms": "1000", "steps": []},
    {**activity(), "private_reasoning": "secret"},
    {**activity(), "steps": [{**activity()["steps"][0], "extra": "secret"}]},
    {**activity(), "steps": [{**activity()["steps"][0], "text": ""}]},
    {**activity(), "steps": [{**activity()["steps"][0], "text": "x" * 401}]},
    {**activity(), "steps": [{**activity()["steps"][0], "phase": "unknown"}]},
    {**activity(), "steps": [{**activity()["steps"][0], "sequence": True}]},
    {**activity(), "steps": [{**activity()["steps"][0], "elapsed_ms": 1001}]},
    {**activity(), "steps": [activity()["steps"][0]] * 49},
    {**activity(), "steps": [activity()["steps"][0], activity()["steps"][0]]},
    {**activity(), "steps": [activity()["steps"][0], {**activity()["steps"][0], "sequence": 4, "elapsed_ms": 499}]},
])
def test_invalid_activity_is_rejected_before_any_message_write(temp_data_dir, value):
    thread_id = setup_thread()
    with pytest.raises(ValidationError):
        save_turn(thread_id, value)
    assert get_messages("owner", thread_id) == []


def test_utf8_serialized_byte_limit_and_maximum_duration():
    step = activity()["steps"][0]
    too_large = {"duration_ms": 86_400_000, "steps": [
        {**step, "sequence": index, "text": "界" * 400} for index in range(48)
    ]}
    with pytest.raises(ValidationError, match="serialized byte limit"):
        MessageActivity.model_validate(too_large)
    valid = {**too_large, "steps": [{**step, "sequence": index} for index in range(48)]}
    assert MessageActivity.model_validate(valid).model_dump() == valid
    assert MessageActivity.model_validate({"duration_ms": 0, "steps": []}).steps == []


@pytest.mark.parametrize("value", ["not-json", "[]", '{"secret":"private-data"}', " " * 32769])
def test_corrupt_optional_activity_logs_only_error_type(value, caplog):
    assert decode_message_activity(value) is None
    assert "Ignoring invalid message activity" in caplog.text
    assert "private-data" not in caplog.text
    assert "not-json" not in caplog.text


def test_optional_corrupt_activity_does_not_hide_saved_answer(temp_data_dir, caplog):
    thread_id = setup_thread()
    save_turn(thread_id, activity())
    execute("UPDATE chat_messages SET activity = ? WHERE role = 'assistant'",
            (json.dumps({"secret": "private-data"}),))
    assert get_messages("owner", thread_id)[-1]["activity"] is None
    completed = get_completed_turn("owner", thread_id, "request")
    assert completed["assistant_content"] == "Here is the answer."
    assert "activity" not in completed
    assert "private-data" not in caplog.text


def test_sqlite_additive_upgrade_preserves_legacy_turn_and_assistant_constraint(temp_data_dir):
    thread_id = setup_thread()
    save_turn(thread_id)
    execute("ALTER TABLE chat_messages DROP COLUMN activity")
    init_db()
    assert all(message["activity"] is None for message in get_messages("owner", thread_id))
    assert "activity" not in get_completed_turn("owner", thread_id, "request")
    with pytest.raises(Exception, match="CHECK constraint failed"):
        execute("UPDATE chat_messages SET activity = ? WHERE role = 'user'", (json.dumps(activity()),))
    with pytest.raises(Exception, match="CHECK constraint failed"):
        execute("UPDATE chat_messages SET activity = '[]' WHERE role = 'assistant'")


def test_postgres_activity_migration_is_additive_nullable_and_bounded(monkeypatch):
    path = Path(__file__).parents[1] / "db/migrations/versions/20260930_0010_message_activity.py"
    spec = importlib.util.spec_from_file_location("activity_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    sql = " ".join(statements).lower()
    assert migration.down_revision == "20260930_0009"
    assert "lock_timeout = '5s'" in sql
    assert "statement_timeout = '60s'" in sql
    assert "add column activity jsonb" in sql
    assert "role = 'assistant'" in sql
    assert "jsonb_typeof(activity) = 'object'" in sql
    assert "not valid" in sql
    assert "update " not in sql
    assert "drop " not in sql


def test_postgres_schema_guard_requires_activity():
    from adapters.database_adapter import POSTGRES_REQUIRED_COLUMNS

    assert "activity" in POSTGRES_REQUIRED_COLUMNS["chat_messages"]
