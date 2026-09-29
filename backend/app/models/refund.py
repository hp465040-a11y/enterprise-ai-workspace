"""Multiple partial refunds per order; amounts use the order's currency."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.organization import Organization
    from app.models.return_request import ReturnRequest


class RefundStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Refund(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
        CheckConstraint("btrim(external_refund_id) <> ''", name="ck_refunds_external_id_nonempty"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'failed', 'cancelled')",
            name="ck_refunds_status",
        ),
        Index(
            "uq_refunds_external_id", "organization_id", "order_id", "external_refund_id",
            unique=True, postgresql_where=text("external_refund_id IS NOT NULL"),
        ),
        Index("ix_refunds_org_status_requested", "organization_id", "status", "requested_at"),
        Index("ix_refunds_org_order_return", "organization_id", "order_id", "return_request_id"),
        Index("ix_refunds_order_id", "order_id"),
        Index("ix_refunds_return_request_id", "return_request_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    return_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("return_requests.id", ondelete="RESTRICT"), nullable=True
    )
    external_refund_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=RefundStatus.PENDING.value, server_default="pending", nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
    order: Mapped["Order"] = relationship(back_populates="refunds")
    return_request: Mapped["ReturnRequest | None"] = relationship(back_populates="refunds")
