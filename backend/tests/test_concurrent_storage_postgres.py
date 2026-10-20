"""Opt-in storage races in a disposable schema on explicitly configured local Postgres.

Set MESSAGE_SEQUENCE_TEST_DATABASE_URL to a local database with anon and authenticated
roles. The fixture applies the repository migrations and drops only its own schema.
"""

import importlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event
from urllib.parse import urlparse

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from adapters.database_adapter import init_db
from config import settings
from storage import graph_history_store as history
from storage import message_store, runtime_state_store, thread_store
from storage.profile_store import upsert_profile


@pytest.fixture(autouse=True)
def clear_rate_limits():
    # This module creates and drops its own schema. The general suite cleanup
    # must not touch a pre-existing SQLite database before this fixture runs.
    yield


@pytest.fixture
def postgres_storage(monkeypatch, force_sqlite_mode):
    database_url = os.environ.get("MESSAGE_SEQUENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set MESSAGE_SEQUENCE_TEST_DATABASE_URL to disposable local Postgres"
        )
    parsed_url = urlparse(database_url)
    if (
        parsed_url.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed_url.query
        or parsed_url.fragment
    ):
        pytest.fail("Storage concurrency tests require a local disposable database")
    engine = create_engine(
        database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    schema = "storage_concurrency_test_" + uuid.uuid4().hex
    monkeypatch.setenv("DB_SCHEMA", "staging")
    try:
        with engine.connect() as connection:
            roles = set(
                connection.exec_driver_sql("SELECT rolname FROM pg_roles").scalars()
            )
            if not {"anon", "authenticated"} <= roles:
                pytest.fail(
                    "Local migration setup requires anon and authenticated roles"
                )
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.exec_driver_sql(
                "CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"
            )
            connection.commit()
            context = MigrationContext.configure(connection)
            migrations = sorted(
                (Path(__file__).parents[1] / "db/migrations/versions").glob("[0-9]*.py")
            )
            for path in migrations:
                migration = importlib.import_module(
                    "db.migrations.versions." + path.stem
                )
                with context.begin_transaction(), Operations.context(context):
                    migration.upgrade()
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": migration.revision},
            )
            connection.commit()
        monkeypatch.setattr(settings, "supabase_db_url", database_url)
        # The random schema isolates each test; migrations use staging identity
        # rules so no Supabase Auth objects or production schemas are needed.
        monkeypatch.setattr(settings, "db_schema", schema)
        init_db()
        yield
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


def create_owner():
    owner = str(uuid.uuid4())
    upsert_profile(owner, owner + "@postgres.test")
    return owner


def graph(version):
    return {
        "version": version,
        "title": version,
        "nodes": [{"id": "a", "label": version}],
        "edges": [],
    }


def persist(owner, thread, request, value=None, base=(None, None)):
    return thread_store.persist_turn(
        owner,
        thread,
        title=value["title"] if value else "Answer only",
        user_content="user-" + request,
        assistant_content="assistant-" + request,
        graph_data=value,
        expected_graph_version=base[0],
        base_revision_id=base[1],
        client_request_id=request,
    )


def test_parallel_generation_keeps_siblings_canonical_retry_and_latest_layout(
    postgres_storage,
):
    owner = create_owner()
    thread = str(thread_store.create_thread(owner)["id"])
    assert persist(owner, thread, "seed", graph("A"))
    current, _, revision_id = thread_store.get_graph_artifact(owner, thread)
    base = (current["version"], revision_id)
    assert thread_store.save_graph(
        owner,
        thread,
        {
            "version": "A",
            "view_state": {"nodePositions": {"a": {"x": 9, "y": 12}}},
        },
    )
    start = Barrier(2)

    def complete(number):
        value = graph("branch-" + str(number))
        value["view_state"] = {"nodePositions": {"a": {"x": number + 100, "y": 1}}}
        start.wait(timeout=10)
        return persist(owner, thread, value["version"], value, base)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(complete, range(2)))
    state = history.list_history(owner, thread)
    revisions = state["revisions"]
    assert len(revisions) == 3
    assert [
        str(item["parent_revision_id"]) if item["parent_revision_id"] else None
        for item in revisions
    ] == [None, revision_id, revision_id]
    assert state["current_revision_id"] == str(revisions[1]["id"])
    active = thread_store.get_graph(owner, thread)
    assert active["view_state"]["nodePositions"]["a"] == {"x": 9, "y": 12}
    stale = history.get_revision(owner, thread, str(revisions[2]["id"]))["graph_data"]
    assert stale["view_state"]["nodePositions"]["a"]["x"] >= 100
    assert thread_store.get_thread(owner, thread)["title"] == active["title"]
    canonical = thread_store.get_completed_turn(owner, thread, stale["version"])
    assert canonical["graph_revision_id"] == str(revisions[2]["id"])
    assert persist(owner, thread, stale["version"], graph("duplicate"), base)
    assert thread_store.get_completed_turn(owner, thread, stale["version"]) == canonical
    assert len(history.list_history(owner, thread)["revisions"]) == 3
    assert len(message_store.get_messages(owner, thread)) == 6
    assert persist(owner, thread, "old-answer-only", base=base)
    assert thread_store.get_graph(owner, thread) == active
    assert thread_store.get_thread(owner, thread)["title"] == active["title"]


def test_completed_turn_and_standalone_append_keep_fk_reads_compatible(
    postgres_storage, monkeypatch
):
    owner = create_owner()
    thread = str(thread_store.create_thread(owner)["id"])
    owner_locked = Event()
    thread_locked = Event()
    original_connect = thread_store._connect

    class PausedConnection:
        def __init__(self, connection, completed_turn):
            self.connection = connection
            self.completed_turn = completed_turn

        def execute(self, query, params=()):
            result = self.connection.execute(query, params)
            if self.completed_turn and query.startswith("SELECT id FROM profiles"):
                owner_locked.set()
                assert thread_locked.wait(timeout=5)
            elif not self.completed_turn and query.startswith(
                "SELECT id FROM chat_threads"
            ):
                thread_locked.set()
                assert owner_locked.wait(timeout=5)
            return result

    @contextmanager
    def connect(completed_turn):
        with original_connect() as connection:
            connection.execute("SET LOCAL lock_timeout = '3s'")
            connection.execute("SET LOCAL statement_timeout = '6s'")
            yield PausedConnection(connection, completed_turn)

    monkeypatch.setattr(thread_store, "_connect", lambda: connect(True))
    monkeypatch.setattr(message_store, "_connect", lambda: connect(False))
    with ThreadPoolExecutor(max_workers=2) as pool:
        completion = pool.submit(persist, owner, thread, "turn")
        try:
            assert owner_locked.wait(timeout=5)
            append = pool.submit(
                message_store.append, owner, thread, "user", "standalone"
            )
            append.result(timeout=10)
            assert completion.result(timeout=10)
        finally:
            # Release instrumentation waits even when an assertion fails.
            owner_locked.set()
            thread_locked.set()
    contents = [item["content"] for item in message_store.get_messages(owner, thread)]
    index = contents.index("user-turn")
    assert contents[index + 1] == "assistant-turn"
    assert len(contents) == 3


def test_parallel_identical_retries_keep_one_canonical_pair(postgres_storage):
    owner = create_owner()
    thread = str(thread_store.create_thread(owner)["id"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda _: persist(owner, thread, "same-key"), range(4)))
    assert [item["content"] for item in message_store.get_messages(owner, thread)] == [
        "user-same-key",
        "assistant-same-key",
    ]


def test_multiple_activity_registrations_protect_history_until_next_completion(
    postgres_storage, monkeypatch
):
    monkeypatch.setattr(settings, "max_threads_per_user", 1)
    owner = create_owner()
    thread = str(thread_store.create_thread(owner)["id"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        activities = list(
            pool.map(
                lambda _: runtime_state_store.register_active_stream(
                    owner,
                    "chat-thread",
                    ttl_s=60,
                    scope_id=thread,
                ),
                range(4),
            )
        )
    assert len(set(activities)) == 4
    for activity in activities[:3]:
        runtime_state_store.release_active_stream(activity)
    newest = str(thread_store.create_thread(owner)["id"])
    assert thread_store.get_thread(owner, thread)
    assert persist(owner, thread, "protected")
    assert persist(owner, newest, "newest")
    assert thread_store.get_thread(owner, thread)
    runtime_state_store.release_active_stream(activities[3])
    assert persist(owner, newest, "next-completion")
    assert thread_store.get_thread(owner, thread) is None


def test_uncommitted_activity_registration_serializes_draft_retention(
    postgres_storage, monkeypatch
):
    monkeypatch.setattr(settings, "max_threads_per_user", 1)
    owner = create_owner()
    thread = str(thread_store.create_thread(owner)["id"])
    inserted = Event()
    finish_registration = Event()
    original_connect = runtime_state_store._connect

    class PausedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params=()):
            result = self.connection.execute(query, params)
            if "INSERT INTO active_streams" in query:
                inserted.set()
                assert finish_registration.wait(timeout=5)
            return result

    @contextmanager
    def connect():
        with original_connect() as connection:
            connection.execute("SET LOCAL lock_timeout = '3s'")
            yield PausedConnection(connection)

    monkeypatch.setattr(runtime_state_store, "_connect", connect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        registration = pool.submit(
            runtime_state_store.register_active_stream,
            owner,
            "chat-thread",
            ttl_s=60,
            scope_id=thread,
        )
        try:
            assert inserted.wait(timeout=5)
            creation = pool.submit(thread_store.create_thread, owner)
            with pytest.raises(TimeoutError):
                creation.result(timeout=0.1)
        finally:
            finish_registration.set()
        activity = registration.result(timeout=10)
        creation.result(timeout=10)
    assert thread_store.get_thread(owner, thread)
    runtime_state_store.release_active_stream(activity)
