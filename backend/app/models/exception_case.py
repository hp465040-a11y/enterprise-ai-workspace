"""Organization-scoped order investigations; event references require service validation."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.organization import Organization


class ExceptionType(StrEnum):
    SHIPMENT_DELAY = "shipment_delay"
    DELIVERY_DELAY = "delivery_delay"
    DELIVERY_FAILED = "delivery_failed"
    OTHER = "other"


class ExceptionCaseStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    CLOSED = "closed"


class ExceptionCase(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "exception_cases"
    __table_args__ = (
        CheckConstraint(
            "exception_type IN ('shipment_delay', 'delivery_delay', 'delivery_failed', 'other')",
            name="ck_exception_cases_type",
        ),
        CheckConstraint("status IN ('open', 'investigating', 'closed')", name="ck_exception_cases_status"),
        CheckConstraint("btrim(problem_description) <> ''", name="ck_exception_cases_problem_nonempty"),
        CheckConstraint(
            "status <> 'closed' OR (closed_at IS NOT NULL AND conclusion IS NOT NULL "
            "AND btrim(conclusion) <> '')", name="ck_exception_cases_closed_details",
        ),
        Index("ix_exception_cases_org_order", "organization_id", "order_id"),
        Index("ix_exception_cases_org_status_opened", "organization_id", "status", "opened_at"),
        Index("ix_exception_cases_order_id", "order_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    exception_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ExceptionCaseStatus.OPEN.value, server_default="open", nullable=False
    )
    problem_description: Mapped[str] = mapped_column(Text, nullable=False)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_event_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, server_default=text("'{}'::uuid[]"), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
    order: Mapped["Order"] = relationship(back_populates="exception_cases")
