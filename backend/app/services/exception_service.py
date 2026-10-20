"""Read-only, organization-scoped exception case lookup."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.exception_case import ExceptionCase


async def get_exception_case(
    db: AsyncSession, *, organization_id: UUID, case_id: UUID,
) -> ExceptionCase:
    """Caller owns authorization and session lifetime; no relationships are loaded."""
    with db.no_autoflush:
        result = await db.execute(select(ExceptionCase).where(
            ExceptionCase.organization_id == organization_id,
            ExceptionCase.id == case_id,
        ))
    case = result.scalar_one_or_none()
    if case is None:
        raise NotFoundError("Exception case not found")
    return case
