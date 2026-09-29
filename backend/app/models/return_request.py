"""One return request covers a quantity of one order item, not an entire basket."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.order_item import OrderItem
    from app.models.organization import Organization
    from app.models.refund import Refund


class ReturnStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReturnRequest(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "return_requests"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_return_requests_quantity_positive"),
        CheckConstraint("btrim(external_return_id) <> ''", name="ck_return_requests_external_id_nonempty"),
        CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'in_transit', 'received', 'completed', 'cancelled')",
            name="ck_return_requests_status",
        ),
        Index(
            "uq_return_requests_external_item", "organization_id", "order_id",
            "external_return_id", "order_item_id", unique=True,
            postgresql_where=text("external_return_id IS NOT NULL"),
        ),
        Index("ix_return_requests_org_status_requested", "organization_id", "status", "requested_at"),
        Index("ix_return_requests_org_order_item", "organization_id", "order_id", "order_item_id"),
        Index("ix_return_requests_order_id", "order_id"),
        Index("ix_return_requests_order_item_id", "order_item_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    external_return_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ReturnStatus.REQUESTED.value, server_default="requested", nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_carrier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    return_tracking_number: Mapped[str | None] = mapped_column(String(255), nullable=True)

    organization: Mapped["Organization"] = relationship()
    order: Mapped["Order"] = relationship(back_populates="return_requests")
    order_item: Mapped["OrderItem"] = relationship(back_populates="return_requests")
    refunds: Mapped[list["Refund"]] = relationship(
        back_populates="return_request", passive_deletes="all"
    )
