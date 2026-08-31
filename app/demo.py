"""Namoyish ma'lumotini bazaga to'ldirish (bo'sh bo'lsa).

Vercel'da cold-start paytida `/tmp` ichida SQLite yaratiladi va shu funksiya
chaqiriladi. Lokal test uchun `demo_data.py` ham shuni ishlatadi."""
from __future__ import annotations

import base64
import datetime as dt
import random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import MediaType, ProductStatus, Role, StageRunStatus
from app.models import AuditLog, Media, Product, StageRun, User
from app.services import stages as stages_svc
from app.services import workflow

_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkI"
    "CQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQ"
    "EBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
    "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX"
    "/9k="
)


async def is_empty(session: AsyncSession) -> bool:
    return not await session.scalar(select(func.count()).select_from(Product))


async def seed_demo(session: AsyncSession) -> None:
    """Bazaga 10 ta namunaviy food truck, 1 admin, 1 QC, 7 ishchi qo'shadi."""
    random.seed(7)
    await stages_svc.ensure_seeded(session)
    stage_list = await stages_svc.list_stages(session)
    N = len(stage_list)

    admin = User(telegram_id=900001, full_name="Rahbar Aliyev", role=Role.admin)
    qc = User(telegram_id=900002, full_name="Sifat Karimov", role=Role.qc)
    session.add_all([admin, qc])
    await session.flush()
    workers = []
    for st in stage_list:
        w = User(telegram_id=900100 + st.order_no, full_name=f"Ishchi {st.order_no}",
                 role=Role.worker, stage_id=st.id)
        session.add(w)
        workers.append(w)
    await session.flush()

    async def _media(run, uploader, n=2):
        for i in range(n):
            m = Media(product_id=run.product_id, type=MediaType.photo,
                      file_path="demo.jpg", telegram_file_id=f"d{i}", uploaded_by_id=uploader.id)
            m.stage_run = run
            session.add(m)
        await session.flush()

    async def _mark_all(run, ok=True):
        for stt in await workflow.checklist_state(session, run):
            await workflow.set_check(session, run, stt["item"].id, "ok" if ok else "fail", qc)
        await session.flush()

    async def run_to(product, upto, returns=None):
        returns = returns or {}
        while product.current_stage_order <= upto and product.status != ProductStatus.done:
            order = product.current_stage_order
            run = await workflow.active_run(session, product)
            await _media(run, workers[order - 1])
            await workflow.submit_to_qc(session, run, workers[order - 1])
            await session.flush()
            if order in returns and run.attempt_no == 1:
                state = await workflow.checklist_state(session, run)
                bad = returns[order] % max(len(state), 1)
                for j, stt in enumerate(state):
                    await workflow.set_check(session, run, stt["item"].id, "fail" if j == bad else "ok", qc)
                await session.flush()
                summ = await workflow.checklist_summary(session, run)
                await workflow.qc_return(session, run, qc, "Tekshiruv: " + "; ".join(summ["failed"]))
                await session.flush()
                continue
            await _mark_all(run, ok=True)
            await workflow.qc_approve(session, run, qc)
            await session.flush()

    specs = [
        ("Food truck «Burger»", "Partiya A", "Liniya 1", N, {2: 1, 5: 2}),
        ("Food truck «Coffee»", None, "Liniya 1", N, {4: 3}),
        ("Food truck «Pizza»", None, "Liniya 2", 4, {1: 0}),
        ("Food truck «Shaurma»", "Shoshilinch", "Liniya 2", 3, None),
        ("Food truck «Doner»", None, "Liniya 3", 3, {3: 1}),
        ("Food truck «Ice cream»", None, "Liniya 1", 6, {2: 1, 4: 3}),
        ("Food truck «BBQ»", None, "Liniya 3", 2, {1: 0}),
        ("Food truck «Fish»", "Partiya B", "Liniya 2", 1, None),
        ("Food truck «Vegan»", None, "Liniya 1", N, {6: 4}),
        ("Food truck «Crepe»", None, "Liniya 3", 0, None),
    ]
    products = []
    for name, note, line, upto, rets in specs:
        p = await workflow.create_product(session, name=name, note=note, creator=admin, line=line)
        await session.flush()
        if upto >= 1:
            await run_to(p, upto, returns=rets)
        products.append(p)

    q8 = products[7]
    run = await workflow.active_run(session, q8)
    await _media(run, workers[q8.current_stage_order - 1])
    await workflow.submit_to_qc(session, run, workers[q8.current_stage_order - 1])
    await session.flush()

    # ---- vaqt belgilarini so'nggi ~12 kunga tarqatish ----
    now = dt.datetime.now(dt.timezone.utc)
    day_offsets = [11, 10, 9, 9, 7, 6, 5, 5, 3, 2]
    for idx, p in enumerate(products):
        base = now - dt.timedelta(days=day_offsets[idx % len(day_offsets)], hours=random.randint(0, 10))
        p.created_at = base
        runs = list((await session.scalars(
            select(StageRun).where(StageRun.product_id == p.id).order_by(StageRun.id))).all())
        t = base + dt.timedelta(hours=1)
        for r in runs:
            r.started_at = t
            for k, mrow in enumerate((await session.scalars(
                    select(Media).where(Media.stage_run_id == r.id))).all()):
                mrow.created_at = t + dt.timedelta(minutes=15 * (k + 1))
            dur = dt.timedelta(hours=random.uniform(1.5, 6))
            if r.submitted_at is not None:
                r.submitted_at = t + dur
            if r.decided_at is not None:
                r.decided_at = t + dur + dt.timedelta(hours=random.uniform(0.3, 2))
                t = r.decided_at + dt.timedelta(hours=random.uniform(0.5, 4))
            else:
                t = t + dur
        if p.status == ProductStatus.done:
            p.finished_at = max((r.decided_at for r in runs if r.decided_at), default=t)

    run_ts = {r.id: (r.decided_at or r.submitted_at or r.started_at)
              for r in (await session.scalars(select(StageRun))).all()}
    prod_ts = {p.id: (p.created_at, p.finished_at) for p in products}
    for a in (await session.scalars(select(AuditLog))).all():
        ts = None
        if a.stage_run_id and run_ts.get(a.stage_run_id):
            ts = run_ts[a.stage_run_id]
        elif a.product_id in prod_ts:
            c, f = prod_ts[a.product_id]
            ts = f if a.action == "product_finished" and f else c
        if ts:
            a.created_at = ts
