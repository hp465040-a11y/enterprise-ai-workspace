"""Organization-owned SKU catalog; prices here never rewrite order snapshots."""

import uuid
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.order_item import OrderItem
    from app.models.organization import Organization


class ProductStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class Product(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_products_org_sku"),
        CheckConstraint("btrim(sku) <> ''", name="ck_products_sku_nonempty"),
        CheckConstraint("price >= 0", name="ck_products_price_nonnegative"),
        CheckConstraint(
            "(price IS NULL AND currency IS NULL) OR (price IS NOT NULL AND currency IS NOT NULL)",
            name="ck_products_price_currency_pair",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_products_currency"),
        CheckConstraint("status IN ('active', 'inactive', 'archived')", name="ck_products_status"),
        Index("ix_products_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=ProductStatus.ACTIVE.value, server_default="active", nullable=False
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    attributes: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )

    organization: Mapped["Organization"] = relationship()
    order_items: Mapped[list["OrderItem"]] = relationship(
        back_populates="product", passive_deletes="all"
    )
