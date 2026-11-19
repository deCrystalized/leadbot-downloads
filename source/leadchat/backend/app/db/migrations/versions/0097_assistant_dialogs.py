"""Explicit browser-assistant enrollment and optimistic takeover version."""

import sqlalchemy as sa
from alembic import op

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_dialogs",
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("principal_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operator_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_assistant_dialogs_principal", "assistant_dialogs", ["principal_id", "updated_at"]
    )


def downgrade() -> None:
    op.drop_table("assistant_dialogs")
