"""Read-only order lookup tool; no LLM or agent orchestration."""

from typing import Literal, TypedDict
from uuid import UUID

from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.services import order_service


class GetOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_number: str = Field(description="Customer-provided order number")
    platform: str | None = Field(default=None, description="Known platform; omit if unknown")
    store_key: str | None = Field(default=None, description="Known store key; omit if unknown")

    @field_validator("platform", "store_key", mode="before")
    @classmethod
    def normalize_optional_null(cls, value: object) -> object:
        """Accept narrow model-generated null spellings at the Tool boundary."""
        if isinstance(value, str) and value.strip().casefold() in {"", "null", "none"}:
            return None
        return value


class OrderSummary(TypedDict):
    order_number: str
    platform: str
    store_key: str
    status: str
    payment_status: str
    fulfillment_status: str
    currency: str
    total_amount: str
    ordered_at: str


class GetOrderResult(TypedDict):
    status: Literal["found", "not_found", "ambiguous", "invalid_input"]
    error_code: str | None
    message: str | None
    order: OrderSummary | None


def create_get_order_tool(db: AsyncSession, *, organization_id: UUID) -> StructuredTool:
    """Bind an authorized organization and live session for this execution.

    The caller owns authorization and session lifetime. Do not cache this
    tool globally or invoke it concurrently with the same session.
    """

    @tool("get_order", args_schema=GetOrderInput)
    async def get_order(
        order_number: str,
        platform: str | None = None,
        store_key: str | None = None,
    ) -> GetOrderResult:
        """Look up an order header by order number in the authorized organization.

        Only supply platform/store_key when known. If the result is ambiguous,
        ask for the platform and/or store; do not guess or choose an order.
        Items, refunds and returns are not included.
        """
        try:
            order = await order_service.get_order(
                db,
                organization_id=organization_id,
                order_number=order_number,
                platform=platform,
                store_key=store_key,
            )
        except NotFoundError as exc:
            return {
                "status": "not_found", "error_code": exc.error_code,
                "message": exc.message, "order": None,
            }
        except ValidationAppError as exc:
            return {
                "status": "ambiguous" if exc.error_code == "ambiguous_order" else "invalid_input",
                "error_code": exc.error_code, "message": exc.message, "order": None,
            }

        return {
            "status": "found",
            "error_code": None,
            "message": None,
            "order": {
                "order_number": order.order_number,
                "platform": order.platform,
                "store_key": order.store_key,
                "status": order.status,
                "payment_status": order.payment_status,
                "fulfillment_status": order.fulfillment_status,
                "currency": order.currency,
                "total_amount": str(order.total_amount),
                "ordered_at": order.ordered_at.isoformat(),
            },
        }

    return get_order
