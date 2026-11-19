"""Private native research metadata and command receipts, never action receipts."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssistantResearchWork(Base):
    __tablename__ = "assistant_research_work"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    operator_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    dialog_version: Mapped[int] = mapped_column(Integer, nullable=False)
    versions: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False, default="prepare")
    binding: Mapped[str | None] = mapped_column(Text)
    active_command_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    result: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[float] = mapped_column(Float, nullable=False)
    due: Mapped[float] = mapped_column(Float, nullable=False)
    lease_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class AssistantResearchCommand(Base):
    __tablename__ = "assistant_research_commands"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    work_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("assistant_research_work.key", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)


class AssistantResearchResource(Base):
    """Global model admission only; never a provider grant or action permit."""

    __tablename__ = "assistant_research_resource"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    work_key: Mapped[str | None] = mapped_column(Text, ForeignKey("assistant_research_work.key"))
