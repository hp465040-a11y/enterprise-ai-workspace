"""Authenticated creation and manual review API contracts."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


class ActionReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]


class ActionCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_case_id: UUID
    message: str
    idempotency_key: str


class ActionCreateResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    requested_by_user_id: UUID
    action_type: Literal["notify_case_customer"]
    target_case_id: UUID
    status: Literal["pending_approval", "approved", "rejected", "executed"]
    created_at: AwareDatetime
    review_decision: Literal["approved", "rejected"] | None = None
    reviewed_at: AwareDatetime | None = None
    executed_at: AwareDatetime | None = None


class ActionReviewResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    status: Literal["approved", "rejected"]
    review_decision: Literal["approved", "rejected"]
    reviewed_by_user_id: UUID
    reviewed_at: AwareDatetime


class CustomerNotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    action_request_id: UUID
    target_case_id: UUID
    created_by_user_id: UUID
    content: str
    delivery_status: Literal["not_sent"]
    created_at: AwareDatetime
