"""Add optional failed-generation request metadata without backfilling history.

Roll back application code while retaining this nullable column. Dropping the
column discards retry metadata and requires a backup to recover those requests.
Verify with information_schema.columns and pg_constraint before app rollout.
"""

from alembic import op

revision = "20260930_0009"
down_revision = "20260929_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("set local statement_timeout = '60s'")
    op.execute("alter table chat_messages add column retry_request jsonb")
    # Existing rows have NULL metadata. NOT VALID avoids a historical table scan
    # while enforcing the constraint on every subsequent insert or update.
    op.execute("""
        alter table chat_messages add constraint ck_chat_messages_retry_request
        check (retry_request is null or (
            role = 'assistant' and jsonb_typeof(retry_request) = 'object'
        )) not valid
    """)


def downgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("set local statement_timeout = '60s'")
    op.execute("alter table chat_messages drop column retry_request")
