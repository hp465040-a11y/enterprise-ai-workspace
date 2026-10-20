"""Organization-scoped lookup of order headers by customer-facing order number."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.order import Order


async def get_order(
    db: AsyncSession,
    *,
    organization_id: UUID,
    order_number: str,
    platform: str | None = None,
    store_key: str | None = None,
) -> Order:
    """Return one order in the organization, or report absence/ambiguity.

    The caller must authorize access to organization_id before calling.
    Related items, refunds and returns are not loaded by this query.
    """
    order_number = order_number.strip()
    if not order_number:
        raise ValidationAppError("Order number must not be empty")

    query = select(Order).where(
        Order.organization_id == organization_id,
        Order.order_number == order_number,
    )
    if platform is not None:
        platform = platform.strip()
        if not platform:
            raise ValidationAppError("Platform must not be empty")
        query = query.where(Order.platform == platform)
    if store_key is not None:
        store_key = store_key.strip()
        if not store_key:
            raise ValidationAppError("Store key must not be empty")
        query = query.where(Order.store_key == store_key)

    result = await db.execute(query)
    orders = list(result.scalars().all())
    if not orders:
        raise NotFoundError("Order not found")
    if len(orders) > 1:
        raise ValidationAppError(
            "Multiple orders match; please clarify the platform and/or store",
            error_code="ambiguous_order",
        )
    return orders[0]
