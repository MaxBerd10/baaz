from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


async def log(
    session: AsyncSession,
    *,
    actor: User | None,
    action: str,
    product_id: int | None = None,
    stage_run_id: int | None = None,
    details: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=getattr(actor, "id", None),
            actor_name=getattr(actor, "full_name", None),
            action=action,
            product_id=product_id,
            stage_run_id=stage_run_id,
            details=details,
        )
    )
