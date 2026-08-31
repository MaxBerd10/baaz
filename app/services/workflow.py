from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import MediaType, ProductStatus, StageRunStatus
from app.models import (
    Media,
    Product,
    StageCheckItem,
    StageRun,
    StageRunCheck,
    User,
    utcnow,
)
from app.services import audit, stages


class WorkflowError(Exception):
    """Ish jarayoni qoidasi buzilganda."""


@dataclass
class AdvanceResult:
    finished: bool
    next_stage_order: int | None
    product: Product


# --------------------------------------------------------------------------- #
# Yordamchi so'rovlar
# --------------------------------------------------------------------------- #
async def active_run(session: AsyncSession, product: Product) -> StageRun | None:
    """Joriy bosqichdagi tugallanmagan (in_progress / qc_pending) run."""
    return await session.scalar(
        select(StageRun)
        .where(
            StageRun.product_id == product.id,
            StageRun.stage_order == product.current_stage_order,
            StageRun.status.in_([StageRunStatus.in_progress, StageRunStatus.qc_pending]),
        )
        .order_by(StageRun.id.desc())
        .limit(1)
    )


async def get_run(session: AsyncSession, run_id: int) -> StageRun | None:
    return await session.get(StageRun, run_id)


# --------------------------------------------------------------------------- #
# Mahsulot yaratish
# --------------------------------------------------------------------------- #
async def create_product(
    session: AsyncSession, *, creator: User,
    model: str | None = None, size_m: int | None = None, color: str | None = None,
    name: str | None = None, note: str | None = None, line: str | None = None,
) -> Product:
    stage1 = await stages.get_by_order(session, 1)
    if stage1 is None:
        raise WorkflowError("Liniyalar sozlanmagan. Avval liniya qo'shing.")

    model = (model or "").strip() or None
    color = (color or "").strip() or None
    if not name:
        parts = [p for p in (model, f"{size_m} m" if size_m else None, color) if p]
        name = " · ".join(parts) or "Food truck"

    product = Product(
        code="",
        name=name.strip(),
        model=model,
        size_m=size_m,
        color=color,
        line=(line.strip() if line and line.strip() else None),
        note=(note or None),
        status=ProductStatus.in_production,
        current_stage_order=1,
        created_by_id=creator.id,
    )
    session.add(product)
    await session.flush()
    product.code = f"PR-{product.id:06d}"

    run = StageRun(
        product_id=product.id,
        stage_id=stage1.id,
        stage_order=1,
        attempt_no=1,
        status=StageRunStatus.in_progress,
    )
    session.add(run)
    await session.flush()

    await audit.log(
        session,
        actor=creator,
        action="product_created",
        product_id=product.id,
        stage_run_id=run.id,
        details=f"{product.code} — {product.name}",
    )
    return product


# --------------------------------------------------------------------------- #
# Ishchi harakatlari
# --------------------------------------------------------------------------- #
async def add_media(
    session: AsyncSession,
    run: StageRun,
    *,
    media_type: MediaType,
    file_path: str,
    telegram_file_id: str | None,
    uploader: User,
) -> Media:
    if run.status not in (StageRunStatus.in_progress,):
        raise WorkflowError("Bu bosqichga hozir media qo'shib bo'lmaydi.")
    m = Media(
        product_id=run.product_id,
        type=media_type,
        file_path=file_path,
        telegram_file_id=telegram_file_id,
        uploaded_by_id=uploader.id,
    )
    m.stage_run = run  # reverse-collection ham yangilanadi
    session.add(m)
    if run.worker_id is None:
        run.worker_id = uploader.id
    await session.flush()
    await audit.log(
        session,
        actor=uploader,
        action="media_added",
        product_id=run.product_id,
        stage_run_id=run.id,
        details=media_type.value,
    )
    return m


async def set_worker_comment(session: AsyncSession, run: StageRun, text: str, author: User) -> None:
    if run.status != StageRunStatus.in_progress:
        raise WorkflowError("Izohni faqat ishlab chiqarish bosqichida yozish mumkin.")
    run.worker_comment = text.strip() or None
    if run.worker_id is None:
        run.worker_id = author.id


async def submit_to_qc(session: AsyncSession, run: StageRun, worker: User) -> None:
    if run.status != StageRunStatus.in_progress:
        raise WorkflowError("Bu bosqich allaqachon yuborilgan yoki yakunlangan.")
    media_count = len(run.media)
    from app.config import settings

    if media_count < settings.min_media_to_submit:
        raise WorkflowError(
            f"Kamida {settings.min_media_to_submit} ta rasm/video qo'shing."
        )
    run.worker_id = worker.id
    run.status = StageRunStatus.qc_pending
    run.submitted_at = utcnow()
    run.product.status = ProductStatus.qc_pending

    await audit.log(
        session,
        actor=worker,
        action="submitted_to_qc",
        product_id=run.product_id,
        stage_run_id=run.id,
        details=f"{media_count} ta media",
    )


# --------------------------------------------------------------------------- #
# Sifat nazorati qarorlari
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# QC tekshiruv ro'yxati (checklist)
# --------------------------------------------------------------------------- #
async def checklist_state(session: AsyncSession, run: StageRun) -> list[dict]:
    items = list(
        (
            await session.scalars(
                select(StageCheckItem)
                .where(
                    StageCheckItem.stage_id == run.stage_id,
                    StageCheckItem.is_active.is_(True),
                )
                .order_by(StageCheckItem.order_no, StageCheckItem.id)
            )
        ).all()
    )
    marks = {c.check_item_id: c for c in run.checks}
    out = []
    for it in items:
        c = marks.get(it.id)
        out.append({"item": it, "ok": (c.ok if c else None)})
    return out


async def set_check(
    session: AsyncSession, run: StageRun, item_id: int, state: str, qc_user: User
) -> None:
    existing = next((c for c in run.checks if c.check_item_id == item_id), None)
    if state == "none":
        if existing:
            run.checks.remove(existing)
        return
    ok = state == "ok"
    if existing:
        existing.ok = ok
        existing.checked_by_id = qc_user.id
    else:
        run.checks.append(
            StageRunCheck(
                stage_run_id=run.id,
                check_item_id=item_id,
                ok=ok,
                checked_by_id=qc_user.id,
            )
        )
    await session.flush()


async def checklist_summary(session: AsyncSession, run: StageRun) -> dict:
    state = await checklist_state(session, run)
    total = len(state)
    passed = sum(1 for s in state if s["ok"] is True)
    failed = [s["item"].text for s in state if s["ok"] is False]
    pending = sum(1 for s in state if s["ok"] is None)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pending": pending,
        "all_ok": total > 0 and passed == total,
        "has_items": total > 0,
    }


async def qc_approve(
    session: AsyncSession, run: StageRun, qc_user: User, note: str | None = None
) -> AdvanceResult:
    if run.status != StageRunStatus.qc_pending:
        raise WorkflowError("Bu bosqich tekshiruvga tayyor emas.")

    summary = await checklist_summary(session, run)
    if summary["has_items"] and not summary["all_ok"]:
        if summary["failed"]:
            raise WorkflowError(
                "Tekshiruv ro'yxatida yiqilgan punktlar bor — tasdiqlab bo'lmaydi, qaytaring."
            )
        raise WorkflowError(
            f"Avval barcha punktlarni belgilang ({summary['passed']}/{summary['total']})."
        )

    run.status = StageRunStatus.approved
    run.qc_id = qc_user.id
    run.qc_comment = (note or None)
    run.decided_at = utcnow()

    product = run.product
    total = await stages.active_count(session)

    await audit.log(
        session,
        actor=qc_user,
        action="qc_approved",
        product_id=product.id,
        stage_run_id=run.id,
        details=f"bosqich {run.stage_order}/{total}",
    )

    if run.stage_order < total:
        next_order = run.stage_order + 1
        next_stage = await stages.get_by_order(session, next_order)
        product.current_stage_order = next_order
        product.status = ProductStatus.in_production
        new_run = StageRun(
            product_id=product.id,
            stage_id=next_stage.id,
            stage_order=next_order,
            attempt_no=1,
            status=StageRunStatus.in_progress,
        )
        session.add(new_run)
        await session.flush()
        await audit.log(
            session,
            actor=qc_user,
            action="stage_advanced",
            product_id=product.id,
            stage_run_id=new_run.id,
            details=f"-> bosqich {next_order}",
        )
        return AdvanceResult(finished=False, next_stage_order=next_order, product=product)

    product.status = ProductStatus.done
    product.finished_at = utcnow()
    await audit.log(
        session,
        actor=qc_user,
        action="product_finished",
        product_id=product.id,
        stage_run_id=run.id,
        details=product.code,
    )
    return AdvanceResult(finished=True, next_stage_order=None, product=product)


async def qc_return(
    session: AsyncSession, run: StageRun, qc_user: User, reason: str
) -> StageRun:
    if run.status != StageRunStatus.qc_pending:
        raise WorkflowError("Bu bosqich tekshiruvga tayyor emas.")
    reason = reason.strip()
    if not reason:
        raise WorkflowError("Qaytarish sababini yozish shart.")

    run.status = StageRunStatus.returned
    run.qc_id = qc_user.id
    run.qc_comment = reason
    run.decided_at = utcnow()

    product = run.product
    product.status = ProductStatus.returned

    # O'sha bosqich uchun yangi urinish
    retry = StageRun(
        product_id=product.id,
        stage_id=run.stage_id,
        stage_order=run.stage_order,
        attempt_no=run.attempt_no + 1,
        worker_id=run.worker_id,
        status=StageRunStatus.in_progress,
    )
    session.add(retry)
    await session.flush()

    await audit.log(
        session,
        actor=qc_user,
        action="qc_returned",
        product_id=product.id,
        stage_run_id=run.id,
        details=reason[:500],
    )
    return retry
