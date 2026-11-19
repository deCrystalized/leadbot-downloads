"""A server-owned assistant launch; observing it never renews its authority."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssistantRun(Base):
    __tablename__ = "assistant_runs"
    __table_args__ = (
        CheckConstraint("mode IN ('rehearsal','auto')", name="mode"),
        CheckConstraint("state IN ('running','stopped','blocked')", name="state"),
        CheckConstraint("generation >= 1", name="generation"),
    )

    principal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    operator_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    mode: Mapped[str] = mapped_column(
        Text, nullable=False, default="rehearsal", server_default="rehearsal"
    )
    state: Mapped[str] = mapped_column(
        Text, nullable=False, default="stopped", server_default="stopped"
    )
    policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_version: Mapped[str] = mapped_column(Text, nullable=False)
    map_version: Mapped[str] = mapped_column(Text, nullable=False)
    memory_version: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
