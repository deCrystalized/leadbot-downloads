"""Durable service receipt only; creates no launch, order or Telegram job."""

import sqlalchemy as sa
from alembic import op

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_native_notifications",
        sa.Column(
            "work_key", sa.Text(), sa.ForeignKey("assistant_native_office.key"), primary_key=True
        ),
        sa.Column("intent_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("deadline", sa.Float(), nullable=False),
        sa.Column("due", sa.Float(), nullable=False),
        sa.Column("command_id", sa.Uuid()),
        sa.Column("observation_id", sa.Uuid()),
        sa.Column("observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("receipt", sa.Text()),
        sa.Column("reason_code", sa.Text()),
        sa.Column("lease_id", sa.Uuid()),
        sa.Column("lease_until", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("assistant_native_notifications")
