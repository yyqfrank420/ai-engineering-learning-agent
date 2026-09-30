"""Retain nullable public activity on canonical assistant messages.

No history backfill is required. Deploy this additive migration before application
code requiring the column. Roll back code while retaining the column; dropping it
loses activity and needs a database backup for restoration. Verify the activity
column and ck_chat_messages_activity constraint before application rollout.
"""

from alembic import op

revision = "20260930_0010"
down_revision = "20260930_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("set local statement_timeout = '60s'")
    op.execute("alter table chat_messages add column activity jsonb")
    # NOT VALID avoids scanning historical NULL rows and constrains new writes.
    op.execute("""
        alter table chat_messages add constraint ck_chat_messages_activity
        check (activity is null or (
            role = 'assistant' and jsonb_typeof(activity) = 'object'
        )) not valid
    """)


def downgrade() -> None:
    op.execute("set local lock_timeout = '5s'")
    op.execute("set local statement_timeout = '60s'")
    op.execute("alter table chat_messages drop column activity")
