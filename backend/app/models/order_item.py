"""Historical item snapshots; currency is inherited from the order."""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.organization import Organization
    from app.models.product import Product
    from app.models.return_request import ReturnRequest


class OrderItem(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "order_id", "line_number", name="uq_order_items_line"),
        CheckConstraint("line_number > 0", name="ck_order_items_line_positive"),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("btrim(external_item_id) <> ''", name="ck_order_items_external_id_nonempty"),
        CheckConstraint(
            "unit_price >= 0 AND discount_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0",
            name="ck_order_items_amounts_nonnegative",
        ),
        Index(
            "uq_order_items_external_id", "organization_id", "order_id", "external_item_id",
            unique=True, postgresql_where=text("external_item_id IS NOT NULL"),
        ),
        Index("ix_order_items_org_product", "organization_id", "product_id"),
        Index("ix_order_items_order_id", "order_id"),
        Index("ix_order_items_product_id", "product_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    external_item_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0"), server_default="0", nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    organization: Mapped["Organization"] = relationship()
    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product | None"] = relationship(back_populates="order_items")
    return_requests: Mapped[list["ReturnRequest"]] = relationship(
        back_populates="order_item", passive_deletes="all"
    )
