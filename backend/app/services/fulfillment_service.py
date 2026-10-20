"""Read-only fulfillment evidence and conservative timestamp comparisons.

No cause inference, promise replacement, multi-shipment aggregation or proof of
whole-order completion. A null tracking number means scope is unspecified.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.fulfillment_event import FulfillmentEvent
from app.models.order import Order


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationAppError("Analysis timestamps must include a timezone")
    return value.astimezone(UTC)


def _compare(events: list[FulfillmentEvent], promise_type: str, actual_type: str,
             as_of: datetime) -> dict:
    promises = [e for e in events if e.event_type == promise_type]
    actuals = [e for e in events if e.event_type == actual_type]
    result = {
        "status": "unknown", "reason": None, "scope": "unspecified",
        "tracking_number": None,
        "evidence_event_ids": [e.id for e in events if e.event_type in (promise_type, actual_type)],
        "promise_event_id": None, "actual_event_id": None,
        "expected_at": None, "actual_at": None, "difference_seconds": None,
        "deadline_exceeded": None, "completion_observed": bool(actuals),
    }
    if len(promises) > 1 or len(actuals) > 1:
        result["reason"] = "multiple_candidates"
        return result
    if not promises:
        result["reason"] = "missing_promise"
        return result
    promise = promises[0]
    result.update(promise_event_id=promise.id, expected_at=_utc(promise.expected_at),
                  tracking_number=promise.tracking_number,
                  scope="shipment" if promise.tracking_number else "unspecified")
    if _utc(promise.expected_at) < _utc(promise.occurred_at):
        result["reason"] = "time_conflict"
        return result
    if not actuals:
        result.update(reason="completion_not_observed",
                      deadline_exceeded=as_of > _utc(promise.expected_at))
        return result
    actual = actuals[0]
    result.update(actual_event_id=actual.id, actual_at=_utc(actual.occurred_at))
    if promise.tracking_number != actual.tracking_number:
        result.update(reason="tracking_mismatch", scope="unspecified", tracking_number=None)
        return result
    if not promise.tracking_number or not promise.tracking_number.strip():
        result.update(scope="unspecified", tracking_number=None)
        result["reason"] = "unspecified_scope"
        return result
    if _utc(actual.occurred_at) < _utc(promise.occurred_at):
        result["reason"] = "time_conflict"
        return result
    difference = (_utc(actual.occurred_at) - _utc(promise.expected_at)).total_seconds()
    result.update(status="late" if difference > 0 else "on_time",
                  difference_seconds=difference)
    return result


async def get_fulfillment_events(
    db: AsyncSession, *, organization_id: UUID, order_id: UUID,
    as_of: datetime | None = None,
) -> list[FulfillmentEvent]:
    """Read tenant/order events in occurred_at, created_at, UUID order.

    as_of includes events whose occurred_at <= cutoff, regardless of ingestion
    time; omitted means all recorded events. This is not a historical DB snapshot.
    Missing orders raise NotFoundError; an existing order may have no events.
    """
    if as_of is not None:
        as_of = _utc(as_of)
    with db.no_autoflush:
        return await _read_events(db, organization_id, order_id, as_of)


async def _read_events(db, organization_id, order_id, as_of):
    result = await db.execute(select(Order).where(
        Order.organization_id == organization_id, Order.id == order_id,
    ))
    if result.scalar_one_or_none() is None:
        raise NotFoundError("Order not found")
    query = select(FulfillmentEvent).where(
        FulfillmentEvent.organization_id == organization_id,
        FulfillmentEvent.order_id == order_id,
    )
    if as_of is not None:
        query = query.where(FulfillmentEvent.occurred_at <= as_of)
    result = await db.execute(query.order_by(
        FulfillmentEvent.occurred_at, FulfillmentEvent.created_at, FulfillmentEvent.id,
    ))
    return list(result.scalars().all())


def event_summary(e: FulfillmentEvent) -> dict:
    """Explicit business fields, shared by analysis and event tools."""
    return {
        "event_id": e.id, "event_type": e.event_type,
        "occurred_at": _utc(e.occurred_at),
        "expected_at": _utc(e.expected_at) if e.expected_at is not None else None,
        "source": e.source, "external_event_id": e.external_event_id,
        "tracking_number": e.tracking_number, "description": e.description,
    }


async def analyze_fulfillment(
    db: AsyncSession, *, organization_id: UUID, order_id: UUID, as_of: datetime,
) -> dict:
    """Compare shipment evidence, without inferring cause or order completion."""
    as_of = _utc(as_of)
    events = await get_fulfillment_events(
        db, organization_id=organization_id, order_id=order_id, as_of=as_of,
    )
    return {
        "order_id": order_id, "as_of": as_of, "scope": "order",
        "whole_order_completion": "unknown",
        "timeline": [event_summary(e) for e in events],
        "evidence_event_ids": [e.id for e in events],
        "shipment": _compare(events, "shipment_promised", "shipped", as_of),
        "delivery": _compare(events, "delivery_promised", "delivered", as_of),
    }
