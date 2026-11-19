"""Persistent native assistant launches, initially stopped; no worker activation."""

import sqlalchemy as sa
from alembic import op

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_runs",
        sa.Column(
            "principal_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("operator_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("mode", sa.Text(), nullable=False, server_default="rehearsal"),
        sa.Column("state", sa.Text(), nullable=False, server_default="stopped"),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("runtime_version", sa.Text(), nullable=False),
        sa.Column("map_version", sa.Text(), nullable=False),
        sa.Column("memory_version", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("mode IN ('rehearsal','auto')", name=op.f("ck_assistant_runs_mode")),
        sa.CheckConstraint(
            "state IN ('running','stopped','blocked')", name=op.f("ck_assistant_runs_state")
        ),
        sa.CheckConstraint("generation >= 1", name=op.f("ck_assistant_runs_generation")),
    )


def downgrade() -> None:
    op.drop_table("assistant_runs")
