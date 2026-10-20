"""Append-only fulfillment facts. This model does not enforce immutability by itself."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.organization import Organization


class FulfillmentEventType(StrEnum):
    SHIPMENT_PROMISED = "shipment_promised"
    DELIVERY_PROMISED = "delivery_promised"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"


class FulfillmentEvent(Base, UUIDPKMixin):
    __tablename__ = "fulfillment_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('shipment_promised', 'delivery_promised', 'shipped', "
            "'in_transit', 'delivered', 'delivery_failed')", name="ck_fulfillment_events_type",
        ),
        CheckConstraint(
            "(event_type IN ('shipment_promised', 'delivery_promised') AND expected_at IS NOT NULL) "
            "OR (event_type NOT IN ('shipment_promised', 'delivery_promised') AND expected_at IS NULL)",
            name="ck_fulfillment_events_expected_at",
        ),
        CheckConstraint("btrim(source) <> ''", name="ck_fulfillment_events_source_nonempty"),
        CheckConstraint("btrim(description) <> ''", name="ck_fulfillment_events_description_nonempty"),
        CheckConstraint("btrim(external_event_id) <> ''", name="ck_fulfillment_events_external_id_nonempty"),
        Index(
            "uq_fulfillment_events_external_id", "organization_id", "order_id", "source",
            "external_event_id", unique=True,
            postgresql_where=text("external_event_id IS NOT NULL"),
        ),
        Index("ix_fulfillment_events_org_order_occurred", "organization_id", "order_id", "occurred_at"),
        Index("ix_fulfillment_events_order_id", "order_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship()
    order: Mapped["Order"] = relationship(back_populates="fulfillment_events")
