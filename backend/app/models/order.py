"""Organization-owned orders. Services must scope every query by organization_id."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.order_item import OrderItem
    from app.models.organization import Organization
    from app.models.refund import Refund
    from app.models.return_request import ReturnRequest


class OrderStatus(StrEnum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    UNKNOWN = "unknown"
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    FAILED = "failed"


class FulfillmentStatus(StrEnum):
    UNKNOWN = "unknown"
    UNFULFILLED = "unfulfilled"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class Order(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("btrim(platform) <> ''", name="ck_orders_platform_nonempty"),
        CheckConstraint("btrim(store_key) <> ''", name="ck_orders_store_key_nonempty"),
        CheckConstraint("btrim(order_number) <> ''", name="ck_orders_number_nonempty"),
        CheckConstraint("btrim(external_order_id) <> ''", name="ck_orders_external_id_nonempty"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_orders_currency"),
        CheckConstraint(
            "subtotal_amount >= 0 AND discount_amount >= 0 AND shipping_amount >= 0 "
            "AND tax_amount >= 0 AND total_amount >= 0",
            name="ck_orders_amounts_nonnegative",
        ),
        CheckConstraint(
            "status IN ('unknown', 'pending', 'confirmed', 'completed', 'cancelled')",
            name="ck_orders_status",
        ),
        CheckConstraint(
            "payment_status IN ('unknown', 'unpaid', 'partially_paid', 'paid', "
            "'partially_refunded', 'refunded', 'failed')",
            name="ck_orders_payment_status",
        ),
        CheckConstraint(
            "fulfillment_status IN ('unknown', 'unfulfilled', 'partially_fulfilled', "
            "'fulfilled', 'cancelled')",
            name="ck_orders_fulfillment_status",
        ),
        Index(
            "uq_orders_external_id", "organization_id", "platform", "store_key",
            "external_order_id", unique=True,
            postgresql_where=text("external_order_id IS NOT NULL"),
        ),
        Index("ix_orders_org_number", "organization_id", "order_number"),
        Index("ix_orders_org_ordered_at", "organization_id", "ordered_at"),
        Index("ix_orders_org_customer_email", "organization_id", "customer_email"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    store_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_number: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=OrderStatus.UNKNOWN.value, server_default="unknown", nullable=False
    )
    payment_status: Mapped[str] = mapped_column(
        String(32), default=PaymentStatus.UNKNOWN.value, server_default="unknown", nullable=False
    )
    fulfillment_status: Mapped[str] = mapped_column(
        String(32), default=FulfillmentStatus.UNKNOWN.value, server_default="unknown", nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False
    )
    shipping_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    shipping_address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    organization: Mapped["Organization"] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", passive_deletes="all")
    refunds: Mapped[list["Refund"]] = relationship(back_populates="order", passive_deletes="all")
    return_requests: Mapped[list["ReturnRequest"]] = relationship(
        back_populates="order", passive_deletes="all"
    )
