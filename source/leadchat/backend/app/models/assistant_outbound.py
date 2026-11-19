"""Native provenance, immutable send window and one journal row per vendor attempt."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssistantNativeOutbound(Base):
    __tablename__ = "assistant_native_outbound"
    __table_args__ = (
        ForeignKeyConstraint(
            ["message_id", "message_created_at"],
            ["messages.id", "messages.created_at"],
            ondelete="CASCADE",
        ),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    message_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    operator_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    dialog_version: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    root_grant_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    root_reference: Mapped[str] = mapped_column(Text, nullable=False)
    versions: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    body_hash: Mapped[str] = mapped_column(Text, nullable=False)
    dispatch_before: Mapped[float] = mapped_column(Float, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    reason_code: Mapped[str | None] = mapped_column(Text)


class AssistantNativePart(Base):
    __tablename__ = "assistant_native_parts"

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("assistant_native_outbound.message_id", ondelete="CASCADE"),
        primary_key=True,
    )
    part: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[float] = mapped_column(Float, nullable=False)
    finished_at: Mapped[float | None] = mapped_column(Float)
    vendor_id: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
