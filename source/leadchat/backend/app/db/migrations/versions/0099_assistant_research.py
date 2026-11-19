"""Durable private research steps. No run, worker or business action activated."""

import sqlalchemy as sa
from alembic import op

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_research_work",
        sa.Column("key", sa.Text(), primary_key=True),
        *(
            sa.Column(n, sa.Uuid(), nullable=False)
            for n in ("principal_id", "operator_id", "conversation_id", "run_id")
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("dialog_version", sa.Integer(), nullable=False),
        *(
            sa.Column(n, sa.Text(), nullable=False)
            for n in ("versions", "source_hash", "purpose", "stage")
        ),
        sa.Column("binding", sa.Text()),
        sa.Column("active_command_id", sa.Uuid()),
        sa.Column("result", sa.Text()),
        sa.Column("deadline", sa.Float(), nullable=False),
        sa.Column("due", sa.Float(), nullable=False),
        sa.Column("lease_id", sa.Uuid()),
        sa.Column("lease_until", sa.Float(), nullable=False),
    )
    op.create_table(
        "assistant_research_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "work_key",
            sa.Text(),
            sa.ForeignKey("assistant_research_work.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_id", sa.Uuid()),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("response", sa.Text()),
        sa.Column("http_status", sa.Integer()),
    )
    op.create_index(
        "ix_assistant_research_commands_work_key", "assistant_research_commands", ["work_key"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_research_commands_work_key", table_name="assistant_research_commands"
    )
    op.drop_table("assistant_research_commands")
    op.drop_table("assistant_research_work")
