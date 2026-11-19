"""Serial model admission; no Run, attempt, call or action is started."""

import sqlalchemy as sa
from alembic import op

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "assistant_research_resource",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("work_key", sa.Text(), sa.ForeignKey("assistant_research_work.key")),
    )
    op.bulk_insert(table, [{"name": "model"}])


def downgrade() -> None:
    op.drop_table("assistant_research_resource")
