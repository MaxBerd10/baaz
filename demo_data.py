"""Namoyish uchun soxta ma'lumot to'ldiradi (ixtiyoriy).

    python demo_data.py

DIQQAT: mavjud bazaga yozadi. Toza boshlash uchun avval baaz.db ni o'chiring.
Vaqt belgilari so'nggi ~12 kunga tarqatiladi, shunда dashboard grafiklari jonli ko'rinadi.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import random

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.enums import MediaType, ProductStatus, Role, StageRunStatus
from app.models import Media, Product, StageRun, User
from app.services import stages as stages_svc
from app.services import workflow
from app.services.media_store import MEDIA_ROOT, ensure_root

_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkI"
    "CQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQ"
    "EBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
    "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX"
    "/9k="
)


async def _media(session, run, uploader, n=2):
    ensure_root()
    for i in range(n):
        (MEDIA_ROOT / "demo.jpg").write_bytes(_JPEG)
        await workflow.add_media(
            session, run, media_type=MediaType.photo, file_path="demo.jpg",
            telegram_file_id=f"demo{i}", uploader=uploader,
        )


async def main() -> None:
    await init_db()
    ensure_root()
    random.seed(7)
    async with SessionLocal() as s:
        await stages_svc.ensure_seeded(s)
        stage_list = await stages_svc.list_stages(s)
        N = len(stage_list)

        admin = User(telegram_id=900001, full_name="Rahbar Aliyev", role=Role.admin)
        qc = User(telegram_id=900002, full_name="Sifat Karimov", role=Role.qc)
        s.add_all([admin, qc])
        await s.flush()
        workers = []
        for st in stage_list:
            w = User(telegram_id=900100 + st.order_no, full_name=f"Ishchi {st.order_no}",
                     role=Role.worker, stage_id=st.id)
            s.add(w)
            workers.append(w)
        await s.flush()

        async def _mark_all(run, ok=True):
            for st in await workflow.checklist_state(s, run):
                await workflow.set_check(s, run, st["item"].id, "ok" if ok else "fail", qc)
            await s.flush()

        async def run_to(product, upto, returns=None):
            """returns: {stage_order: failed_check_index} — o'sha bosqichда 1-urinishda qaytariladi."""
            returns = returns or {}
            while product.current_stage_order <= upto and product.status != ProductStatus.done:
                order = product.current_stage_order
                run = await workflow.active_run(s, product)
                await _media(s, run, workers[order - 1])
                await workflow.submit_to_qc(s, run, workers[order - 1])
                await s.flush()
                if order in returns and run.attempt_no == 1:
                    state = await workflow.checklist_state(s, run)
                    bad = returns[order] % max(len(state), 1)
                    for j, st in enumerate(state):
                        await workflow.set_check(s, run, st["item"].id, "fail" if j == bad else "ok", qc)
                    await s.flush()
                    summ = await workflow.checklist_summary(s, run)
                    reason = "Tekshiruv: " + "; ".join(summ["failed"])
                    await workflow.qc_return(s, run, qc, reason)
                    await s.flush()
                    continue  # 2-urinish
                await _mark_all(run, ok=True)
                await workflow.qc_approve(s, run, qc)
                await s.flush()

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
            p = await workflow.create_product(s, name=name, note=note, creator=admin, line=line)
            await s.flush()
            if upto >= 1:
                await run_to(p, upto, returns=rets)
            products.append(p)

        # Qopqoq Q8 -> 2-bosqich sifat nazoratida
        q8 = products[7]
        run = await workflow.active_run(s, q8)
        await _media(s, run, workers[q8.current_stage_order - 1])
        await workflow.submit_to_qc(s, run, workers[q8.current_stage_order - 1])
        await s.flush()

        # ---- vaqt belgilarini so'nggi 12 kunga tarqatish ----
        now = dt.datetime.now(dt.timezone.utc)
        day_offsets = [11, 10, 9, 9, 7, 6, 5, 5, 3, 2]
        for idx, p in enumerate(products):
            base = now - dt.timedelta(
                days=day_offsets[idx % len(day_offsets)], hours=random.randint(0, 10)
            )
            p.created_at = base
            runs = list(
                (await s.scalars(
                    select(StageRun).where(StageRun.product_id == p.id).order_by(StageRun.id)
                )).all()
            )
            t = base + dt.timedelta(hours=1)
            for r in runs:
                r.started_at = t
                dur = dt.timedelta(hours=random.uniform(1.5, 6))
                for k, mrow in enumerate(
                    (await s.scalars(select(Media).where(Media.stage_run_id == r.id))).all()
                ):
                    mrow.created_at = t + dt.timedelta(minutes=15 * (k + 1))
                if r.submitted_at is not None:
                    r.submitted_at = t + dur
                if r.decided_at is not None:
                    r.decided_at = t + dur + dt.timedelta(hours=random.uniform(0.3, 2))
                    t = r.decided_at + dt.timedelta(hours=random.uniform(0.5, 4))
                else:
                    t = t + dur
            if p.status == ProductStatus.done:
                last = max((r.decided_at for r in runs if r.decided_at), default=t)
                p.finished_at = last

        # ---- audit log vaqtlarini ham moslashtirish ----
        from app.models import AuditLog

        run_ts = {
            r.id: (r.decided_at or r.submitted_at or r.started_at)
            for r in (await s.scalars(select(StageRun))).all()
        }
        prod_ts = {
            p.id: (p.created_at, p.finished_at)
            for p in products
        }
        for a in (await s.scalars(select(AuditLog))).all():
            ts = None
            if a.stage_run_id and run_ts.get(a.stage_run_id):
                ts = run_ts[a.stage_run_id]
            elif a.product_id in prod_ts:
                c, f = prod_ts[a.product_id]
                ts = f if a.action in ("product_finished",) and f else c
            if ts:
                a.created_at = ts

        await s.commit()
    print("✅ Namoyish ma'lumotlari qo'shildi (10 ta mahsulot, 1 admin, 1 QC, 7 ishchi).")


if __name__ == "__main__":
    asyncio.run(main())
