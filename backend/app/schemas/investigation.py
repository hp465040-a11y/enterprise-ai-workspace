"""Public read-only investigation contract; internal traces are not exposed."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.ai.agents.investigation_report import EvidenceReport


class TimingObservation(BaseModel):
    """Display-only copy of a verified fulfillment comparison."""

    status: str | None = None
    scope: str | None = None
    tracking_number: str | None = None
    expected_at: AwareDatetime | None = None
    actual_at: AwareDatetime | None = None
    difference_seconds: float | None = None
    reason: str | None = None


class AllocationObservation(BaseModel):
    status: Literal["blocked", "not_observed"]
    causal_status: Literal["linked_to_shipment_delay", "unknown"]
    failure_event_ids: list[UUID]
    attribution_event_id: UUID | None = None
    linked_failure_event_id: UUID | None = None


class InvestigationObservations(BaseModel):
    whole_order_completion: str | None = None
    shipment: TimingObservation | None = None
    delivery: TimingObservation | None = None
    allocation: AllocationObservation | None = None


def observations_from_trace(trace: list[dict]) -> InvestigationObservations | None:
    """Expose the last successful analysis without parsing or changing the handoff."""
    analyses = [step["result"]["analysis"] for step in trace
                if step["tool"] == "analyze_fulfillment" and step["result"]["status"] == "found"]
    if not analyses:
        return None
    analysis = analyses[-1]
    return InvestigationObservations.model_validate({
        "whole_order_completion": analysis.get("whole_order_completion"),
        "shipment": analysis.get("shipment"),
        "delivery": analysis.get("delivery"),
        "allocation": analysis.get("allocation"),
    })


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: UUID
    as_of: AwareDatetime | None = None
    workspace_id: UUID | None = None
    require_knowledge: StrictBool = Field(
        default=False, description="Explicitly require a SOP/rule lookup in the selected authorized workspace",
    )

    @model_validator(mode="after")
    def require_knowledge_scope(self):
        if self.require_knowledge and self.workspace_id is None:
            raise ValueError("Required knowledge lookup needs a workspace")
        return self


class InvestigationResponse(BaseModel):
    run_id: UUID | None = None
    request_id: str
    organization_id: UUID
    case_id: UUID
    as_of: AwareDatetime
    report: EvidenceReport
    handoff: str
    observations: InvestigationObservations | None = None


class InvestigationRunRead(BaseModel):
    id: UUID
    organization_id: UUID
    case_id: UUID
    workspace_id: UUID | None
    as_of: datetime
    status: Literal["running", "succeeded", "failed", "interrupted"]
    deadline_at: datetime
    created_at: datetime
    finished_at: datetime | None
    error_code: str | None
    result: InvestigationResponse | None = None
