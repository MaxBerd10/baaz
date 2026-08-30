from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums import ProductStatus, StageRunStatus
from app.models import Product, StageRun, StageRunCheck, User


async def get_by_code(session: AsyncSession, code: str) -> Product | None:
    return await session.scalar(
        select(Product)
        .where(Product.code == code)
        .options(
            selectinload(Product.created_by),
            selectinload(Product.stage_runs).selectinload(StageRun.media),
        )
    )


async def get_by_id(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


# --------------------------------------------------------------------------- #
# Ishchi ko'rinishlari — faqat o'z bosqichi
# --------------------------------------------------------------------------- #
async def worker_active(session: AsyncSession, worker: User) -> list[Product]:
    if not worker.stage:
        return []
    order = worker.stage.order_no
    return list(
        (
            await session.scalars(
                select(Product)
                .where(
                    Product.current_stage_order == order,
                    Product.status == ProductStatus.in_production,
                )
                .order_by(Product.created_at)
            )
        ).all()
    )


async def worker_returned(session: AsyncSession, worker: User) -> list[Product]:
    if not worker.stage:
        return []
    order = worker.stage.order_no
    return list(
        (
            await session.scalars(
                select(Product)
                .where(
                    Product.current_stage_order == order,
                    Product.status == ProductStatus.returned,
                )
                .order_by(Product.created_at)
            )
        ).all()
    )


async def worker_done(session: AsyncSession, worker: User, limit: int = 30) -> list[Product]:
    """Ishchi o'zi tasdiqdan o'tkazgan bosqichlarga ega mahsulotlar."""
    subq = (
        select(StageRun.product_id)
        .where(StageRun.worker_id == worker.id, StageRun.status == StageRunStatus.approved)
        .distinct()
    )
    return list(
        (
            await session.scalars(
                select(Product)
                .where(Product.id.in_(subq))
                .order_by(Product.id.desc())
                .limit(limit)
            )
        ).all()
    )


# --------------------------------------------------------------------------- #
# Sifat nazorati ko'rinishlari
# --------------------------------------------------------------------------- #
async def qc_queue(session: AsyncSession) -> list[StageRun]:
    return list(
        (
            await session.scalars(
                select(StageRun)
                .where(StageRun.status == StageRunStatus.qc_pending)
                .order_by(StageRun.submitted_at)
                .options(
                    selectinload(StageRun.product),
                    selectinload(StageRun.stage),
                    selectinload(StageRun.worker),
                    selectinload(StageRun.media),
                )
            )
        ).all()
    )


async def qc_recent(session: AsyncSession, limit: int = 20) -> list[StageRun]:
    return list(
        (
            await session.scalars(
                select(StageRun)
                .where(StageRun.status.in_([StageRunStatus.approved, StageRunStatus.returned]))
                .where(StageRun.decided_at.is_not(None))
                .order_by(StageRun.decided_at.desc())
                .limit(limit)
                .options(
                    selectinload(StageRun.product),
                    selectinload(StageRun.stage),
                    selectinload(StageRun.worker),
                    selectinload(StageRun.qc),
                )
            )
        ).all()
    )


# --------------------------------------------------------------------------- #
# Rahbar ko'rinishlari
# --------------------------------------------------------------------------- #
async def list_products(
    session: AsyncSession,
    *,
    status: ProductStatus | None = None,
    stage_order: int | None = None,
    limit: int = 200,
) -> list[Product]:
    q = select(Product).order_by(Product.id.desc()).limit(limit)
    if status is not None:
        q = q.where(Product.status == status)
    if stage_order is not None:
        q = q.where(Product.current_stage_order == stage_order)
    return list((await session.scalars(q)).all())


async def timeline(session: AsyncSession, product: Product) -> list[StageRun]:
    return list(
        (
            await session.scalars(
                select(StageRun)
                .where(StageRun.product_id == product.id)
                .order_by(StageRun.stage_order, StageRun.attempt_no, StageRun.id)
                .options(
                    selectinload(StageRun.media),
                    selectinload(StageRun.stage),
                    selectinload(StageRun.worker),
                    selectinload(StageRun.qc),
                    selectinload(StageRun.checks).selectinload(StageRunCheck.check_item),
                )
            )
        ).all()
    )
