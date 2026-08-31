from __future__ import annotations

import datetime as dt
import html

from app.config import settings
from app.enums import PRODUCT_STATUS_LABEL, ROLE_LABEL, StageRunStatus
from app.models import Product, StageRun, User

try:
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo(settings.timezone)
except Exception:  # pragma: no cover
    _TZ = dt.timezone.utc


def e(text: str | None) -> str:
    return html.escape(str(text or ""))


def truck_line(p: Product) -> str:
    """T1 · 5 m · Oq"""
    parts = [p.model, f"{p.size_m} m" if p.size_m else None, p.color]
    return " · ".join(e(x) for x in parts if x) or "—"


def fmt_dt(value: dt.datetime | None) -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(_TZ).strftime("%d.%m.%Y %H:%M")


RUN_STATUS_LABEL = {
    StageRunStatus.in_progress: "🔵 Jarayonda",
    StageRunStatus.qc_pending: "🟡 Tekshiruvda",
    StageRunStatus.approved: "🟢 Tasdiqlangan",
    StageRunStatus.returned: "🔴 Qaytarilgan",
}


def whoami(user: User) -> str:
    lines = [
        f"👤 <b>{e(user.full_name)}</b>",
        f"Rol: {ROLE_LABEL[user.role]}",
    ]
    if user.stage:
        lines.append(f"Bosqich: {user.stage.order_no}. {e(user.stage.name)}")
    lines.append(f"ID: <code>{user.telegram_id}</code>")
    if not user.is_active:
        lines.append("⚠️ Hisobingiz vaqtincha o'chirilgan.")
    return "\n".join(lines)


def worker_card(
    product: Product, run: StageRun, total_stages: int,
    check_items: list[str] | None = None,
) -> str:
    media_photos = sum(1 for m in run.media if m.type.value == "photo")
    media_videos = sum(1 for m in run.media if m.type.value == "video")
    lines = [
        f"📦 <b>{e(product.code)}</b> — {e(product.name)}"
        + f"\n🚚 {truck_line(product)}",
        f"Liniya {run.stage_order}/{total_stages}: {e(run.stage.name)}",
        f"Urinish: #{run.attempt_no}   Holat: {PRODUCT_STATUS_LABEL[product.status]}",
        f"Media: 📸 {media_photos} · 🎥 {media_videos}",
    ]
    if run.worker_comment:
        lines.append(f"📝 Izoh: {e(run.worker_comment)}")
    if run.attempt_no > 1:
        prev = next(
            (
                r
                for r in reversed(product.stage_runs)
                if r.stage_order == run.stage_order
                and r.status == StageRunStatus.returned
            ),
            None,
        )
        if prev and prev.qc_comment:
            lines.append(f"\n🔴 <b>Sifat qaytardi:</b> {e(prev.qc_comment)}")
    if check_items:
        lines.append("\n🔍 <b>Sifat nazorati shularni tekshiradi:</b>")
        for i, t in enumerate(check_items, 1):
            lines.append(f"  {i}. {e(t)}")
        lines.append("<i>Har bir punktni tasdiqlaydigan rasm/video qo'shing.</i>")
    return "\n".join(lines)


def qc_card(run: StageRun, total_stages: int) -> str:
    product = run.product
    media_photos = sum(1 for m in run.media if m.type.value == "photo")
    media_videos = sum(1 for m in run.media if m.type.value == "video")
    lines = [
        "🔍 <b>SIFAT TEKSHIRUVI</b>",
        f"📦 {e(product.code)} — {e(product.name)}"
        + f"\n🚚 {truck_line(product)}",
        f"Liniya {run.stage_order}/{total_stages}: {e(run.stage.name)}",
        f"Urinish: #{run.attempt_no}   👷 {e(run.worker.full_name) if run.worker else '—'}",
        f"Yuborilgan: {fmt_dt(run.submitted_at)}",
        f"Media: 📸 {media_photos} · 🎥 {media_videos}",
    ]
    if product.note:
        lines.append(f"🗒 Mahsulot izohi: {e(product.note)}")
    if run.worker_comment:
        lines.append(f"📝 Ishchi izohi: {e(run.worker_comment)}")
    return "\n".join(lines)


def product_timeline(product: Product, runs: list[StageRun], total_stages: int) -> str:
    lines = [
        f"📦 <b>{e(product.code)}</b> — {e(product.name)}",
        f"🚚 {truck_line(product)}",
        f"Holat: {PRODUCT_STATUS_LABEL[product.status]}",
        f"Joriy liniya: {product.current_stage_order}/{total_stages}",
        f"Yaratilgan: {fmt_dt(product.created_at)}"
        + (f" · {e(product.created_by.full_name)}" if product.created_by else ""),
    ]
    if product.finished_at:
        lines.append(f"Tayyor bo'lgan: {fmt_dt(product.finished_at)}")
    if product.note:
        lines.append(f"Izoh: {e(product.note)}")
    lines.append("\n<b>Tarix:</b>")
    for r in runs:
        head = f"• {r.stage_order}-liniya (#{r.attempt_no}) — {RUN_STATUS_LABEL[r.status]}"
        lines.append(head)
        sub = []
        if r.worker:
            sub.append(f"👷 {e(r.worker.full_name)}")
        if r.submitted_at:
            sub.append(f"yuborildi {fmt_dt(r.submitted_at)}")
        if r.decided_at:
            sub.append(f"qaror {fmt_dt(r.decided_at)}")
        if r.qc:
            sub.append(f"🔍 {e(r.qc.full_name)}")
        if sub:
            lines.append("   " + " · ".join(sub))
        if r.worker_comment:
            lines.append(f"   📝 {e(r.worker_comment)}")
        if r.qc_comment:
            lines.append(f"   💬 {e(r.qc_comment)}")
        if r.checks:
            ok = sum(1 for c in r.checks if c.ok)
            bad = [c for c in r.checks if not c.ok]
            lines.append(f"   📋 Tekshiruv: {ok}/{len(r.checks)} ✅")
            for c in bad:
                lines.append(f"      ❌ {e(c.check_item.text)}")
        if r.media:
            lines.append(f"   📎 {len(r.media)} ta media")
    return "\n".join(lines)
