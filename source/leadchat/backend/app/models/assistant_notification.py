"""One server-owned service notice for the exact original created CRM work."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssistantOfficeNotification(Base):
    __tablename__ = "assistant_native_notifications"

    work_key: Mapped[str] = mapped_column(
        Text, ForeignKey("assistant_native_office.key"), primary_key=True
    )
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[float] = mapped_column(Float, nullable=False)
    due: Mapped[float] = mapped_column(Float, nullable=False)
    command_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    observation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    receipt: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    lease_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[float] = mapped_column(Float, nullable=False, default=0)
