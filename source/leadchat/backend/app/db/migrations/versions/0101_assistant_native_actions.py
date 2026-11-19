"""Native action journal. No Run, call, message or external effect is started."""

import sqlalchemy as sa
from alembic import op

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_native_actions",
        sa.Column("key", sa.Text(), primary_key=True),
        *(
            sa.Column(n, sa.Uuid(), nullable=False)
            for n in ("principal_id", "operator_id", "run_id", "conversation_id")
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("dialog_version", sa.Integer()),
        *(
            sa.Column(n, sa.Text(), nullable=False)
            for n in ("versions", "source_hash", "kind", "stage")
        ),
        *(sa.Column(n, sa.Text()) for n in ("research_key", "reference", "grant_id", "result")),
        *(
            sa.Column(n, sa.Uuid())
            for n in ("consume_command_id", "active_command_id", "message_id", "lease_id")
        ),
        *(sa.Column(n, sa.Float(), nullable=False) for n in ("deadline", "due", "lease_until")),
    )
    op.create_table(
        "assistant_native_action_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "action_key",
            sa.Text(),
            sa.ForeignKey("assistant_native_actions.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_id", sa.Uuid()),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("response", sa.Text()),
        sa.Column("http_status", sa.Integer()),
    )
    op.create_index(
        "ix_assistant_native_action_commands_action_key",
        "assistant_native_action_commands",
        ["action_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_native_action_commands_action_key",
        table_name="assistant_native_action_commands",
    )
    op.drop_table("assistant_native_action_commands")
    op.drop_table("assistant_native_actions")
