"""Durable native CRM work. A lease or a reported ID is not a completed order."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssistantOfficeWork(Base):
    __tablename__ = "assistant_native_office"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    operator_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    dialog_version: Mapped[int] = mapped_column(Integer, nullable=False)
    versions: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[float] = mapped_column(Float, nullable=False)
    research_key: Mapped[str | None] = mapped_column(
        Text, ForeignKey("assistant_research_work.key")
    )
    screen_key: Mapped[str | None] = mapped_column(Text, ForeignKey("assistant_native_actions.key"))
    action_key: Mapped[str | None] = mapped_column(
        Text, ForeignKey("assistant_native_actions.key"), unique=True
    )
    form_hash: Mapped[str | None] = mapped_column(Text)
    screen_hash: Mapped[str | None] = mapped_column(Text)
    required_fields: Mapped[str | None] = mapped_column(Text)
    proposal: Mapped[str | None] = mapped_column(Text)
    snapshot_hash: Mapped[str | None] = mapped_column(Text)
    executor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    client_lease_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    client_lease_until: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    create_issued_at: Mapped[float | None] = mapped_column(Float)
    created_id: Mapped[str | None] = mapped_column(Text)
    created_report: Mapped[str | None] = mapped_column(Text)
    card_receipt: Mapped[str | None] = mapped_column(Text)
    followup_issued: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)


class AssistantOfficeResource(Base):
    __tablename__ = "assistant_native_office_resource"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    work_key: Mapped[str | None] = mapped_column(Text, ForeignKey("assistant_native_office.key"))
