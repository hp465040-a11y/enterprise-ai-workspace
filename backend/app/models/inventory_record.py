"""One organization/SKU inventory snapshot, without order allocation."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class InventoryRecord(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "inventory_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_inventory_records_org_sku"),
        # Persist canonical, case-sensitive keys; the query service trims input.
        CheckConstraint(
            "btrim(sku) <> '' AND sku !~ '^[[:space:]]|[[:space:]]$'",
            name="ck_inventory_records_sku",
        ),
        CheckConstraint(
            "on_hand_quantity >= 0 AND reserved_quantity >= 0",
            name="ck_inventory_records_quantities_nonnegative",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    on_hand_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    organization: Mapped["Organization"] = relationship()
