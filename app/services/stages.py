from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.foodtruck import STAGES as FT_STAGES
from app.models import Stage, StageCheckItem


async def list_stages(session: AsyncSession, only_active: bool = True) -> list[Stage]:
    q = select(Stage).order_by(Stage.order_no)
    if only_active:
        q = q.where(Stage.is_active.is_(True))
    return list((await session.scalars(q)).all())


async def get_by_order(session: AsyncSession, order_no: int) -> Stage | None:
    return await session.scalar(select(Stage).where(Stage.order_no == order_no))


async def active_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Stage).where(Stage.is_active.is_(True))
        )
        or 0
    )


async def last_order(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.max(Stage.order_no))) or 0)


async def ensure_seeded(session: AsyncSession) -> int:
    """Bosqichlar bo'lmasa — food truck bosqichlarini yaratadi.
    Placeholder ('N-bosqich') nomlar bo'lsa — haqiqiy nomga yangilaydi.
    Har ikki holatda ham QC tekshiruv punktlarini to'ldiradi."""
    existing = list((await session.scalars(select(Stage).order_by(Stage.order_no))).all())
    by_order = {s.order_no: s for s in existing}

    for order_no, name, desc, _ in FT_STAGES:
        st = by_order.get(order_no)
        if st is None:
            session.add(Stage(order_no=order_no, name=name, description=desc, is_active=True))
        elif st.name.strip() in (f"{order_no}-bosqich", f"{order_no}- bosqich", ""):
            st.name = name
            st.description = desc
    await session.flush()

    await seed_check_items(session)

    return await active_count(session)


async def seed_check_items(session: AsyncSession) -> int:
    """Tekshiruv punkti yo'q bosqichlarga standart ro'yxatni qo'shadi."""
    added = 0
    stages = await list_stages(session)
    ft_by_order = {o: items for o, _, _, items in FT_STAGES}
    for st in stages:
        have = int(
            await session.scalar(
                select(func.count())
                .select_from(StageCheckItem)
                .where(StageCheckItem.stage_id == st.id, StageCheckItem.is_active.is_(True))
            )
            or 0
        )
        if have:
            continue
        for i, text in enumerate(ft_by_order.get(st.order_no, []), start=1):
            session.add(
                StageCheckItem(stage_id=st.id, order_no=i, text=text, is_active=True)
            )
            added += 1
    await session.flush()
    return added


async def add_stage(session: AsyncSession, name: str, description: str | None = None) -> Stage:
    order_no = (await last_order(session)) + 1
    stage = Stage(order_no=order_no, name=name.strip(), description=description, is_active=True)
    session.add(stage)
    await session.flush()
    return stage


async def rename_stage(session: AsyncSession, stage: Stage, name: str) -> None:
    stage.name = name.strip()


async def set_description(session: AsyncSession, stage: Stage, description: str) -> None:
    stage.description = description.strip() or None


# --------------------------------------------------------------------------- #
# QC tekshiruv ro'yxati (checklist)
# --------------------------------------------------------------------------- #
async def list_check_items(
    session: AsyncSession, stage_id: int, only_active: bool = True
) -> list[StageCheckItem]:
    q = (
        select(StageCheckItem)
        .where(StageCheckItem.stage_id == stage_id)
        .order_by(StageCheckItem.order_no, StageCheckItem.id)
    )
    if only_active:
        q = q.where(StageCheckItem.is_active.is_(True))
    return list((await session.scalars(q)).all())


async def add_check_items(session: AsyncSession, stage_id: int, lines: str) -> int:
    base = int(
        await session.scalar(
            select(func.coalesce(func.max(StageCheckItem.order_no), 0)).where(
                StageCheckItem.stage_id == stage_id
            )
        )
        or 0
    )
    n = 0
    for line in lines.splitlines():
        line = line.strip().lstrip("-•*0123456789. ").strip()
        if not line:
            continue
        n += 1
        session.add(
            StageCheckItem(stage_id=stage_id, order_no=base + n, text=line[:500], is_active=True)
        )
    await session.flush()
    return n


async def deactivate_check_item(session: AsyncSession, item_id: int) -> None:
    item = await session.get(StageCheckItem, item_id)
    if item:
        item.is_active = False
