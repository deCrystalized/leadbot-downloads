"""Native CRM resource and original work only; no Run or customer action starts."""

import sqlalchemy as sa
from alembic import op

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_native_office",
        sa.Column("key", sa.Text(), primary_key=True),
        *(
            sa.Column(n, sa.Uuid(), nullable=False)
            for n in ("principal_id", "operator_id", "run_id", "conversation_id")
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("dialog_version", sa.Integer(), nullable=False),
        *(sa.Column(n, sa.Text(), nullable=False) for n in ("versions", "source_hash", "stage")),
        sa.Column("deadline", sa.Float(), nullable=False),
        sa.Column("research_key", sa.Text(), sa.ForeignKey("assistant_research_work.key")),
        sa.Column("screen_key", sa.Text(), sa.ForeignKey("assistant_native_actions.key")),
        sa.Column(
            "action_key", sa.Text(), sa.ForeignKey("assistant_native_actions.key"), unique=True
        ),
        *(
            sa.Column(n, sa.Text())
            for n in (
                "form_hash",
                "screen_hash",
                "required_fields",
                "proposal",
                "snapshot_hash",
                "created_id",
                "created_report",
                "card_receipt",
                "followup_issued",
                "reason_code",
            )
        ),
        sa.Column("executor_id", sa.Uuid()),
        sa.Column("client_lease_id", sa.Uuid()),
        sa.Column("client_lease_until", sa.Float(), nullable=False, server_default="0"),
        sa.Column("create_issued_at", sa.Float()),
    )
    op.create_index(
        "ix_assistant_native_office_conversation_id", "assistant_native_office", ["conversation_id"]
    )
    table = op.create_table(
        "assistant_native_office_resource",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("work_key", sa.Text(), sa.ForeignKey("assistant_native_office.key")),
    )
    op.bulk_insert(table, [{"name": "crm"}])


def downgrade() -> None:
    op.drop_table("assistant_native_office_resource")
    op.drop_index(
        "ix_assistant_native_office_conversation_id", table_name="assistant_native_office"
    )
    op.drop_table("assistant_native_office")
