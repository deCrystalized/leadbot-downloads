"""Native dispatch provenance only. No Run, message or worker is activated."""

import sqlalchemy as sa
from alembic import op

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_native_outbound",
        sa.Column(
            "message_id",
            sa.Uuid(),
            primary_key=True,
        ),
        sa.Column("message_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id", "message_created_at"],
            ["messages.id", "messages.created_at"],
            ondelete="CASCADE",
        ),
        *(
            sa.Column(n, sa.Uuid(), nullable=False)
            for n in ("principal_id", "operator_id", "run_id", "conversation_id")
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("dialog_version", sa.Integer(), nullable=False),
        sa.Column("root_grant_id", sa.Text(), nullable=False, unique=True),
        *(
            sa.Column(n, sa.Text(), nullable=False)
            for n in ("root_reference", "versions", "source_hash", "body_hash", "state")
        ),
        sa.Column("dispatch_before", sa.Float(), nullable=False),
        sa.Column("reason_code", sa.Text()),
    )
    op.create_index(
        "ix_assistant_native_outbound_conversation_id",
        "assistant_native_outbound",
        ["conversation_id"],
    )
    op.create_table(
        "assistant_native_parts",
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("assistant_native_outbound.message_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("part", sa.Integer(), primary_key=True),
        sa.Column("attempt", sa.Integer(), primary_key=True),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("finished_at", sa.Float()),
        sa.Column("vendor_id", sa.Text()),
        sa.Column("reason_code", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("assistant_native_parts")
    op.drop_index(
        "ix_assistant_native_outbound_conversation_id", table_name="assistant_native_outbound"
    )
    op.drop_table("assistant_native_outbound")
