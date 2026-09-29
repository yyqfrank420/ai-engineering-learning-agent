"""Retain graph checkpoints and their active pointer without historical backfill."""

import os

from alembic import op

revision = "20260929_0008"
down_revision = "20260912_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("set local statement_timeout = '60s'")
    op.execute(
        "alter table chat_threads add constraint uq_chat_threads_id_owner unique(id, user_id)"
    )
    op.execute("""
        create table graph_revisions (
            id uuid primary key,
            thread_id uuid not null,
            user_id uuid not null,
            parent_revision_id uuid,
            revision_number bigint not null check (revision_number > 0),
            graph_data jsonb not null check (jsonb_typeof(graph_data) = 'object'),
            graph_contract jsonb,
            label text not null,
            source text not null check (source in ('generation', 'content_edit')),
            created_at timestamptz not null default now(),
            foreign key(thread_id, user_id) references chat_threads(id, user_id) on delete cascade,
            unique(thread_id, revision_number),
            unique(thread_id, id),
            foreign key(thread_id, parent_revision_id)
                references graph_revisions(thread_id, id) deferrable initially deferred,
            check (graph_contract is null or (
                jsonb_typeof(graph_contract) = 'object'
                and graph_contract ? 'graph_version' and graph_data ? 'version'
                and nullif(btrim(graph_contract ->> 'graph_version'), '') is not null
                and graph_contract ->> 'graph_version' = graph_data ->> 'version'
            ))
        )
    """)
    op.execute("alter table chat_threads add column active_graph_revision_id uuid")
    op.execute(
        "alter table chat_threads add constraint fk_thread_active_graph foreign key(id, active_graph_revision_id) references graph_revisions(thread_id, id) deferrable initially deferred"
    )
    op.execute("alter table chat_messages add column graph_revision_id uuid")
    op.execute(
        "alter table chat_messages add constraint fk_message_graph_revision foreign key(thread_id, graph_revision_id) references graph_revisions(thread_id, id) deferrable initially deferred"
    )
    op.execute("alter table graph_revisions enable row level security")
    schema = os.environ.get("DB_SCHEMA", "public").strip().lower()
    if schema not in {"public", "staging"}:
        raise RuntimeError("DB_SCHEMA must be either 'public' or 'staging'")
    identity = (
        "auth.uid()"
        if schema == "public"
        else "nullif(current_setting('request.jwt.claim.sub', true), '')::uuid"
    )
    op.execute(
        f"create policy graph_revisions_own on graph_revisions for all using (user_id = {identity}) with check (user_id = {identity})"
    )
    # Contract snapshots are server-only even when the schema has default grants.
    op.execute("revoke all on graph_revisions from public, anon, authenticated")


def downgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("set local statement_timeout = '60s'")
    op.execute("alter table chat_messages drop column graph_revision_id")
    op.execute("alter table chat_threads drop column active_graph_revision_id")
    op.execute("drop table graph_revisions")
    op.execute("alter table chat_threads drop constraint uq_chat_threads_id_owner")
