"""Read-only organization/SKU snapshot lookup; no order shortage inference."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.inventory_record import InventoryRecord


async def get_inventory_status(
    db: AsyncSession, *, organization_id: UUID, sku: str,
) -> dict:
    """Caller owns authorization; missing snapshots never mean zero inventory."""
    if not isinstance(sku, str) or not sku.strip():
        raise ValidationAppError("SKU must be a nonempty string")
    sku = sku.strip()
    if len(sku) > 128:
        raise ValidationAppError("SKU must not exceed 128 characters")
    with db.no_autoflush:
        result = await db.execute(select(InventoryRecord).where(
            InventoryRecord.organization_id == organization_id,
            InventoryRecord.sku == sku,
        ))
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("Inventory record not found")
    available_quantity = record.on_hand_quantity - record.reserved_quantity
    return {
        "scope": "organization_sku", "organization_id": record.organization_id,
        "sku": record.sku, "on_hand_quantity": record.on_hand_quantity,
        "reserved_quantity": record.reserved_quantity,
        "available_quantity": available_quantity,
        "observed_at": record.observed_at,
    }
