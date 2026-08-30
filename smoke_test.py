"""Ish oqimi state-machine smoke-testi (Telegramsiz).

    python scripts_smoke.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.db import SessionLocal, init_db
from app.enums import MediaType, ProductStatus, Role, StageRunStatus
from app.models import User
from app.services import products as products_svc
from app.services import stages as stages_svc
from app.services import stats as stats_svc
from app.services import workflow
from app.services.media_store import MEDIA_ROOT, ensure_root


def check(cond: bool, label: str) -> None:
    print(("  ✅ " if cond else "  ❌ ") + label)
    assert cond, label


async def main() -> None:
    await init_db()
    ensure_root()

    async with SessionLocal() as s:
        await stages_svc.ensure_seeded(s)

        admin = User(telegram_id=1, full_name="Rahbar", role=Role.admin)
        qc = User(telegram_id=2, full_name="Sifatchi", role=Role.qc)
        s.add_all([admin, qc])
        await s.flush()

        stage_list = await stages_svc.list_stages(s)
        workers = []
        for st in stage_list:
            w = User(telegram_id=100 + st.order_no, full_name=f"Ishchi-{st.order_no}",
                     role=Role.worker, stage_id=st.id)
            s.add(w)
            workers.append(w)
        await s.flush()
        total = len(stage_list)
        print(f"Bosqichlar: {total}")

        # --- Mahsulot yaratish ---
        product = await workflow.create_product(s, name="Test detal", note=None, creator=admin)
        await s.flush()
        check(product.code == "PR-000001", f"kod = {product.code}")
        check(product.status == ProductStatus.in_production, "status = in_production")
        check(product.current_stage_order == 1, "joriy bosqich = 1")

        # --- 1..N bosqichlardan o'tkazish, 3-bosqichda bir marta qaytarish bilan ---
        fake = MEDIA_ROOT / "fake.jpg"
        fake.write_bytes(b"\xff\xd8\xff\xd9")

        returned_once = False
        while product.status != ProductStatus.done:
            order = product.current_stage_order
            run = await workflow.active_run(s, product)
            check(run is not None and run.stage_order == order, f"{order}-bosqich faol run bor")

            # media yo'q holatda yuborishga urinish -> xato
            try:
                await workflow.submit_to_qc(s, run, workers[order - 1])
                raise AssertionError("media yo'q, lekin yuborildi")
            except workflow.WorkflowError:
                pass

            await workflow.add_media(
                s, run, media_type=MediaType.photo, file_path="fake.jpg",
                telegram_file_id="x", uploader=workers[order - 1],
            )
            await workflow.submit_to_qc(s, run, workers[order - 1])
            await s.flush()
            check(product.status == ProductStatus.qc_pending, f"{order}-bosqich -> qc_pending")

            # checklist: avval belgilamay tasdiqlashga urinish -> xato
            cl = await workflow.checklist_state(s, run)
            if cl:
                try:
                    await workflow.qc_approve(s, run, qc)
                    raise AssertionError("checklist belgilanmagan, lekin tasdiqlandi")
                except workflow.WorkflowError:
                    pass

            if order == 3 and not returned_once:
                for j, st in enumerate(cl):
                    await workflow.set_check(s, run, st["item"].id, "fail" if j == 0 else "ok", qc)
                await s.flush()
                summ = await workflow.checklist_summary(s, run)
                check(len(summ["failed"]) == 1, "checklist: 1 punkt yiqildi")
                retry = await workflow.qc_return(s, run, qc, "Tirnalish bor")
                await s.flush()
                returned_once = True
                check(product.status == ProductStatus.returned, "3-bosqich qaytdi")
                check(retry.attempt_no == 2, "yangi urinish #2")
                check(product.current_stage_order == 3, "bosqich hali ham 3")
                check(run.status == StageRunStatus.returned, "eski run = returned")
                continue

            for st in cl:
                await workflow.set_check(s, run, st["item"].id, "ok", qc)
            await s.flush()
            res = await workflow.qc_approve(s, run, qc)
            await s.flush()
            if res.finished:
                check(product.status == ProductStatus.done, "oxirgi bosqich -> done")
                check(product.finished_at is not None, "finished_at o'rnatildi")
            else:
                check(product.current_stage_order == order + 1, f"-> {order + 1}-bosqichga o'tdi")

        # --- Statistika ---
        ov = await stats_svc.overview(s)
        check(ov["by_status"][ProductStatus.done] == 1, "overview: 1 tayyor")
        per = await stats_svc.per_stage(s)
        check(len(per) == total, "per_stage: barcha bosqichlar")
        prod = await stats_svc.worker_productivity(s)
        approved_total = sum(p["approved"] for p in prod)
        check(approved_total == total, f"ishchi tasdiqlari yig'indisi = {approved_total}")
        returned_total = sum(p["returned"] for p in prod)
        check(returned_total == 1, "qaytarishlar = 1")

        tf = await stats_svc.top_failed_checks(s)
        check(len(tf) == 1 and tf[0]["count"] == 1, "top_failed_checks: 1 ta yiqilgan punkt")

        # --- Tarix ---
        tl = await products_svc.timeline(s, product)
        check(len(tl) == total + 1, f"timeline yozuvlari = {len(tl)} (kutilgan {total + 1})")
        approved_runs = [r for r in tl if r.status == StageRunStatus.approved]
        check(all(len(r.checks) > 0 and all(c.ok for c in r.checks) for r in approved_runs),
              "tasdiqlangan run'larda barcha checklist punktlari ✅")

        await s.rollback()  # testni saqlamaymiz

    print("\n🎉 Barcha tekshiruvlar o'tdi.")


if __name__ == "__main__":
    asyncio.run(main())
