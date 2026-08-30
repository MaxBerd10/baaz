from __future__ import annotations

import calendar as _cal
import datetime as dt

from sqlalchemy import func, select
from app.db import day
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.enums import MediaType, ProductStatus, Role, StageRunStatus
from app.models import (
    Media,
    Product,
    Stage,
    StageCheckItem,
    StageRun,
    StageRunCheck,
    User,
)


async def overview(session: AsyncSession) -> dict:
    rows = await session.execute(
        select(Product.status, func.count()).group_by(Product.status)
    )
    by_status = {s: 0 for s in ProductStatus}
    for status, count in rows:
        by_status[status] = count

    total = sum(by_status.values())

    today = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    finished_today = int(
        await session.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.status == ProductStatus.done, Product.finished_at >= today)
        )
        or 0
    )
    created_today = int(
        await session.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.created_at >= today)
        )
        or 0
    )
    return {
        "total": total,
        "by_status": by_status,
        "finished_today": finished_today,
        "created_today": created_today,
    }


async def per_stage(session: AsyncSession) -> list[dict]:
    stages = list(
        (await session.scalars(select(Stage).where(Stage.is_active.is_(True)).order_by(Stage.order_no))).all()
    )
    # joriy bosqichi shu bo'lgan mahsulotlar, statusi bo'yicha
    rows = await session.execute(
        select(Product.current_stage_order, Product.status, func.count())
        .where(Product.status != ProductStatus.done)
        .group_by(Product.current_stage_order, Product.status)
    )
    bucket: dict[int, dict[ProductStatus, int]] = {}
    for order, status, count in rows:
        bucket.setdefault(order, {})[status] = count

    out = []
    for st in stages:
        b = bucket.get(st.order_no, {})
        out.append(
            {
                "order_no": st.order_no,
                "name": st.name,
                "in_production": b.get(ProductStatus.in_production, 0),
                "qc_pending": b.get(ProductStatus.qc_pending, 0),
                "returned": b.get(ProductStatus.returned, 0),
                "total": sum(b.values()),
            }
        )
    return out


async def worker_productivity(session: AsyncSession) -> list[dict]:
    approved = dict(
        (
            await session.execute(
                select(StageRun.worker_id, func.count())
                .where(StageRun.status == StageRunStatus.approved)
                .group_by(StageRun.worker_id)
            )
        ).all()
    )
    returned = dict(
        (
            await session.execute(
                select(StageRun.worker_id, func.count())
                .where(StageRun.status == StageRunStatus.returned)
                .group_by(StageRun.worker_id)
            )
        ).all()
    )
    worker_ids = {wid for wid in (approved | returned) if wid is not None}
    if not worker_ids:
        return []
    users = {
        u.id: u
        for u in (await session.scalars(select(User).where(User.id.in_(worker_ids)))).all()
    }
    out = []
    for wid in worker_ids:
        u = users.get(wid)
        out.append(
            {
                "name": u.full_name if u else f"#{wid}",
                "stage": (u.stage.name if u and u.stage else "—"),
                "approved": approved.get(wid, 0),
                "returned": returned.get(wid, 0),
            }
        )
    out.sort(key=lambda r: r["approved"], reverse=True)
    return out


async def daily_throughput(session: AsyncSession, days: int = 14) -> dict:
    start = dt.datetime.now(dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - dt.timedelta(days=days - 1)

    created_rows = {
        str(k): int(v)
        for k, v in (
            await session.execute(
                select(day(Product.created_at), func.count())
                .where(Product.created_at >= start)
                .group_by(day(Product.created_at))
            )
        ).all()
    }
    finished_rows = {
        str(k): int(v)
        for k, v in (
            await session.execute(
                select(day(Product.finished_at), func.count())
                .where(Product.finished_at.is_not(None), Product.finished_at >= start)
                .group_by(day(Product.finished_at))
            )
        ).all()
    }
    labels, created, finished = [], [], []
    for i in range(days):
        d = (start + dt.timedelta(days=i)).date()
        key = d.isoformat()
        labels.append(d.strftime("%d.%m"))
        created.append(int(created_rows.get(key, 0)))
        finished.append(int(finished_rows.get(key, 0)))
    return {"labels": labels, "created": created, "finished": finished}


async def stage_cycle_times(session: AsyncSession) -> list[dict]:
    """Har bir bosqich uchun o'rtacha ishlash vaqti (soatda), tasdiqlangan run'lar bo'yicha."""
    stages = list(
        (
            await session.scalars(
                select(Stage).where(Stage.is_active.is_(True)).order_by(Stage.order_no)
            )
        ).all()
    )
    rows = (
        await session.execute(
            select(StageRun.stage_order, StageRun.started_at, StageRun.decided_at).where(
                StageRun.status == StageRunStatus.approved,
                StageRun.decided_at.is_not(None),
            )
        )
    ).all()
    acc: dict[int, list[float]] = {}
    for order, started, decided in rows:
        if not started or not decided:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=dt.timezone.utc)
        if decided.tzinfo is None:
            decided = decided.replace(tzinfo=dt.timezone.utc)
        acc.setdefault(order, []).append((decided - started).total_seconds() / 3600)
    out = []
    for st in stages:
        vals = acc.get(st.order_no, [])
        out.append(
            {
                "order_no": st.order_no,
                "name": st.name,
                "hours": round(sum(vals) / len(vals), 1) if vals else 0.0,
                "count": len(vals),
            }
        )
    return out


async def extra_kpis(session: AsyncSession) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yday = today - dt.timedelta(days=1)

    async def _count(col, lo, hi=None):
        q = select(func.count()).select_from(Product).where(col >= lo)
        if hi is not None:
            q = q.where(col < hi)
        return int(await session.scalar(q) or 0)

    created_today = await _count(Product.created_at, today)
    created_yday = await _count(Product.created_at, yday, today)
    finished_today = await _count(Product.finished_at, today)
    finished_yday = await _count(Product.finished_at, yday, today)

    approved = int(
        await session.scalar(
            select(func.count()).select_from(StageRun).where(
                StageRun.status == StageRunStatus.approved
            )
        )
        or 0
    )
    returned = int(
        await session.scalar(
            select(func.count()).select_from(StageRun).where(
                StageRun.status == StageRunStatus.returned
            )
        )
        or 0
    )
    decided = approved + returned
    pass_rate = round(approved / decided * 100) if decided else 0

    # o'rtacha ishlab chiqarish sikli (yaratilgan -> tayyor), soatda
    done_rows = (
        await session.execute(
            select(Product.created_at, Product.finished_at).where(
                Product.finished_at.is_not(None)
            )
        )
    ).all()
    spans = []
    for c, f in done_rows:
        if c and f:
            if c.tzinfo is None:
                c = c.replace(tzinfo=dt.timezone.utc)
            if f.tzinfo is None:
                f = f.replace(tzinfo=dt.timezone.utc)
            spans.append((f - c).total_seconds() / 3600)
    avg_cycle = round(sum(spans) / len(spans), 1) if spans else 0.0

    return {
        "created_today": created_today,
        "created_delta": created_today - created_yday,
        "finished_today": finished_today,
        "finished_delta": finished_today - finished_yday,
        "pass_rate": pass_rate,
        "returns": returned,
        "avg_cycle_h": avg_cycle,
    }


async def top_failed_checks(session: AsyncSession, limit: int = 12) -> list[dict]:
    rows = (
        await session.execute(
            select(
                StageCheckItem.text,
                Stage.order_no,
                Stage.name,
                func.count(),
            )
            .join(StageRunCheck, StageRunCheck.check_item_id == StageCheckItem.id)
            .join(Stage, Stage.id == StageCheckItem.stage_id)
            .where(StageRunCheck.ok.is_(False))
            .group_by(StageCheckItem.id, Stage.order_no, Stage.name)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    return [
        {"text": t, "stage_order": so, "stage_name": sn, "count": c}
        for (t, so, sn, c) in rows
    ]


async def defects(session: AsyncSession, limit: int = 50) -> list[StageRun]:
    return list(
        (
            await session.scalars(
                select(StageRun)
                .where(StageRun.status == StageRunStatus.returned)
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
# Kalendar
# --------------------------------------------------------------------------- #
async def month_calendar(session: AsyncSession, year: int, month: int) -> dict:
    ndays = _cal.monthrange(year, month)[1]
    lo = dt.datetime(year, month, 1, tzinfo=dt.timezone.utc)
    hi = lo + dt.timedelta(days=ndays)

    def daymap(rows):
        return {str(k): int(c) for k, c in rows}

    created = daymap(
        (
            await session.execute(
                select(day(Product.created_at), func.count())
                .where(Product.created_at >= lo, Product.created_at < hi)
                .group_by(day(Product.created_at))
            )
        ).all()
    )
    finished = daymap(
        (
            await session.execute(
                select(day(Product.finished_at), func.count())
                .where(Product.finished_at >= lo, Product.finished_at < hi)
                .group_by(day(Product.finished_at))
            )
        ).all()
    )
    returned = daymap(
        (
            await session.execute(
                select(day(StageRun.decided_at), func.count())
                .where(
                    StageRun.status == StageRunStatus.returned,
                    StageRun.decided_at >= lo,
                    StageRun.decided_at < hi,
                )
                .group_by(day(StageRun.decided_at))
            )
        ).all()
    )
    approved = daymap(
        (
            await session.execute(
                select(day(StageRun.decided_at), func.count())
                .where(
                    StageRun.status == StageRunStatus.approved,
                    StageRun.decided_at >= lo,
                    StageRun.decided_at < hi,
                )
                .group_by(day(StageRun.decided_at))
            )
        ).all()
    )

    weeks: list[list] = []
    week: list = [None] * dt.date(year, month, 1).weekday()  # Monday-first
    for dnum in range(1, ndays + 1):
        iso = dt.date(year, month, dnum).isoformat()
        week.append(
            {
                "day": dnum,
                "iso": iso,
                "created": created.get(iso, 0),
                "finished": finished.get(iso, 0),
                "returned": returned.get(iso, 0),
                "approved": approved.get(iso, 0),
            }
        )
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        week += [None] * (7 - len(week))
        weeks.append(week)

    return {
        "year": year,
        "month": month,
        "weeks": weeks,
        "totals": {
            "created": sum(created.values()),
            "finished": sum(finished.values()),
            "returned": sum(returned.values()),
            "approved": sum(approved.values()),
        },
    }


# --------------------------------------------------------------------------- #
# Fayllar (media kutubxonasi)
# --------------------------------------------------------------------------- #
async def media_library(
    session: AsyncSession,
    stage_order: int | None = None,
    mtype: str | None = None,
    limit: int = 300,
) -> list[dict]:
    q = (
        select(Media, Product.code, Product.name, Stage.name, User.full_name)
        .join(Product, Product.id == Media.product_id)
        .join(StageRun, StageRun.id == Media.stage_run_id)
        .join(Stage, Stage.id == StageRun.stage_id)
        .outerjoin(User, User.id == Media.uploaded_by_id)
        .order_by(Media.id.desc())
        .limit(limit)
    )
    if stage_order:
        q = q.where(StageRun.stage_order == stage_order)
    if mtype in ("photo", "video"):
        q = q.where(Media.type == MediaType(mtype))
    rows = (await session.execute(q)).all()
    return [
        {
            "id": m.id,
            "type": m.type.value,
            "code": code,
            "pname": pname,
            "stage": sname,
            "by": uname or "—",
            "at": m.created_at,
        }
        for (m, code, pname, sname, uname) in rows
    ]


async def media_counts(session: AsyncSession) -> dict:
    rows = (
        await session.execute(select(Media.type, func.count()).group_by(Media.type))
    ).all()
    d = {t.value: int(c) for t, c in rows}
    return {"photo": d.get("photo", 0), "video": d.get("video", 0), "total": sum(d.values())}


# --------------------------------------------------------------------------- #
# Sozlamalar ko'rinishi
# --------------------------------------------------------------------------- #
async def config_overview(session: AsyncSession) -> dict:
    roles = {
        r: int(c)
        for r, c in (
            await session.execute(select(User.role, func.count()).group_by(User.role))
        ).all()
    }
    checks_n = int(
        await session.scalar(
            select(func.count()).select_from(StageCheckItem).where(
                StageCheckItem.is_active.is_(True)
            )
        )
        or 0
    )
    products_n = int(await session.scalar(select(func.count()).select_from(Product)) or 0)
    stage_count = int(
        await session.scalar(
            select(func.count()).select_from(Stage).where(Stage.is_active.is_(True))
        )
        or 0
    )
    media = await media_counts(session)
    return {
        "db": "SQLite" if settings.database_url.startswith("sqlite") else "PostgreSQL",
        "media_root": settings.media_root,
        "timezone": settings.timezone,
        "min_media": settings.min_media_to_submit,
        "stage_count": stage_count,
        "check_items": checks_n,
        "products": products_n,
        "media_total": media["total"],
        "admins": roles.get(Role.admin, 0),
        "qc": roles.get(Role.qc, 0),
        "workers": roles.get(Role.worker, 0),
        "pending": roles.get(Role.pending, 0),
    }
