"""Original native command receipts and once-only local business application."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssistantNativeAction(Base):
    __tablename__ = "assistant_native_actions"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    operator_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    dialog_version: Mapped[int | None] = mapped_column(Integer)
    versions: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    research_key: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(Text)
    grant_id: Mapped[str | None] = mapped_column(Text)
    consume_command_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    active_command_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    result: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    deadline: Mapped[float] = mapped_column(Float, nullable=False)
    due: Mapped[float] = mapped_column(Float, nullable=False)
    lease_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class AssistantNativeCommand(Base):
    __tablename__ = "assistant_native_action_commands"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    action_key: Mapped[str] = mapped_column(
        Text, ForeignKey("assistant_native_actions.key", ondelete="CASCADE"), index=True
    )
    original_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
