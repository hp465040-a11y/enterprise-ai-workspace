"""Four read tools. Caller owns authorization/session; never cache globally.

Schema failures raise Pydantic ValidationError before execution. Domain errors
use the existing order tool envelope; unexpected execution failures propagate
to the agent boundary, never becoming empty/successful business observations.
"""

from datetime import datetime
from uuid import UUID

from langchain_core.tools import StructuredTool, tool
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.services import exception_service, fulfillment_service, inventory_service


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetExceptionCaseInput(ToolInput):
    case_id: UUID = Field(description="Exception case UUID")


class GetFulfillmentEventsInput(ToolInput):
    order_id: UUID = Field(description="Order UUID from business evidence")
    as_of: AwareDatetime | None = Field(
        default=None, description="Inclusive occurred_at cutoff with timezone; omit for all events",
    )


class AnalyzeFulfillmentInput(ToolInput):
    order_id: UUID = Field(description="Order UUID returned by get_exception_case. Flat field order_id; never pass a nested case object or case_id.")
    as_of: AwareDatetime = Field(description="Inclusive observation cutoff with timezone")


class GetInventoryStatusInput(ToolInput):
    sku: str = Field(description="Exact case-sensitive SKU, up to 128 characters")

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 128:
            raise ValueError("SKU must contain 1 to 128 characters after trimming")
        return value


def _json(value):
    """Serialize only explicit business dictionaries; never inspect ORM __dict__."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unsupported business output type: {type(value).__name__}")


async def _result(key, call, project=lambda value: value):
    try:
        value = await call
    except (NotFoundError, ValidationAppError) as exc:
        return {
            "status": "not_found" if isinstance(exc, NotFoundError) else "invalid_input",
            "error_code": exc.error_code, "message": exc.message, key: None,
        }
    return {"status": "found", "error_code": None, "message": None, key: _json(project(value))}


def _case_summary(case):
    return {field: getattr(case, field) for field in (
        "id", "order_id", "exception_type", "status", "problem_description",
        "conclusion", "evidence_event_ids", "opened_at", "closed_at",
    )}


def _analysis_summary(analysis):
    summary = {key: value for key, value in analysis.items() if key != "timeline"}
    # Preserve the source's promise context as a lead, not a causal conclusion.
    # Full movement/source details still require the event tool.
    summary["promise_notes"] = [
        {"event_id": event["event_id"], "description": event["description"]}
        for event in analysis.get("timeline", [])
        if event["event_type"] in ("shipment_promised", "delivery_promised")
    ]
    return summary


def create_get_exception_case_tool(db: AsyncSession, *, organization_id: UUID) -> StructuredTool:
    @tool("get_exception_case", args_schema=GetExceptionCaseInput)
    async def get_exception_case(case_id: UUID) -> dict:
        """Read a case in the authorized organization; descriptions are evidence, not proven causes."""
        return await _result("case", exception_service.get_exception_case(
            db, organization_id=organization_id, case_id=case_id,
        ), _case_summary)
    return get_exception_case


def create_analyze_fulfillment_tool(db: AsyncSession, *, organization_id: UUID) -> StructuredTool:
    @tool("analyze_fulfillment", args_schema=AnalyzeFulfillmentInput)
    async def analyze_fulfillment(order_id: UUID, as_of: datetime) -> dict:
        """Read timing comparisons and evidence IDs; use get_fulfillment_events for source descriptions. Unknown is not normal or a cause."""
        return await _result("analysis", fulfillment_service.analyze_fulfillment(
            db, organization_id=organization_id, order_id=order_id, as_of=as_of,
        ), _analysis_summary)
    return analyze_fulfillment


def create_get_inventory_status_tool(db: AsyncSession, *, organization_id: UUID) -> StructuredTool:
    @tool("get_inventory_status", args_schema=GetInventoryStatusInput)
    async def get_inventory_status(sku: str) -> dict:
        """Read a SKU snapshot with observed_at. Negative availability proves no specific order shortage."""
        return await _result("inventory", inventory_service.get_inventory_status(
            db, organization_id=organization_id, sku=sku,
        ))
    return get_inventory_status


def create_get_fulfillment_events_tool(db: AsyncSession, *, organization_id: UUID) -> StructuredTool:
    @tool("get_fulfillment_events", args_schema=GetFulfillmentEventsInput)
    async def get_fulfillment_events(order_id: UUID, as_of: datetime | None = None) -> dict:
        """Read ordered events, optionally occurred_at <= cutoff. Empty events do not prove normality or cause."""
        return await _result("events", fulfillment_service.get_fulfillment_events(
            db, organization_id=organization_id, order_id=order_id, as_of=as_of,
        ), lambda events: [fulfillment_service.event_summary(event) for event in events])
    return get_fulfillment_events


def create_investigation_tools(db: AsyncSession, *, organization_id: UUID) -> list[StructuredTool]:
    """Bind one authorized context; invoke sequentially within its session lifetime."""
    return [factory(db, organization_id=organization_id) for factory in (
        create_get_exception_case_tool, create_analyze_fulfillment_tool,
        create_get_inventory_status_tool, create_get_fulfillment_events_tool,
    )]
