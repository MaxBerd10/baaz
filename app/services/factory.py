"""Web'dan zavod ishi: model katalogi, truck yaratish (bot bazasiga) va xabar oluvchilar."""
from __future__ import annotations

import datetime as dt
import re
import uuid
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelCard
from app.services.media_store import MEDIA_ROOT, abs_path, ensure_root

PRIORITIES = ["low", "normal", "high", "urgent"]
PRIORITY_LABEL = {"low": "🟢 Past", "normal": "🔵 Oddiy", "high": "🟠 Yuqori", "urgent": "🔴 Shoshilinch"}

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # Telegram sendPhoto chegarasi 10MB


class DuplicateSerial(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Model katalogi
# --------------------------------------------------------------------------- #
async def list_models(session: AsyncSession, only_active: bool = False) -> list[ModelCard]:
    q = select(ModelCard).order_by(ModelCard.name)
    if only_active:
        q = q.where(ModelCard.is_active.is_(True))
    return list((await session.scalars(q)).all())


async def get_model(session: AsyncSession, model_id: int) -> ModelCard | None:
    return await session.get(ModelCard, model_id)


async def get_model_by_name(session: AsyncSession, name: str | None) -> ModelCard | None:
    if not name:
        return None
    return await session.scalar(select(ModelCard).where(ModelCard.name == name))


async def image_map(session: AsyncSession) -> dict[str, str]:
    """{model nomi: rasm URL'i} — faqat rasmi bor modellar."""
    rows = (await session.execute(
        select(ModelCard.name, ModelCard.id, ModelCard.image_file).where(ModelCard.image_file.is_not(None))
    )).all()
    # ?v= — rasm almashtirilganda brauzer keshi yangilansin
    return {n: f"/media/model/{i}?v={Path(f).stem[:8]}" for n, i, f in rows}


def sniff_image(data: bytes) -> str | None:
    """Fayl turini sarlavhasidan aniqlaydi (kengaytmaga ishonmaymiz)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save_image(data: bytes) -> str:
    """Rasmni MEDIA_ROOT/models/ ga yozadi, nisbiy yo'lni qaytaradi. ValueError — yaroqsiz fayl."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Rasm 8 MB dan katta")
    ext = sniff_image(data)
    if not ext:
        raise ValueError("Faqat JPG, PNG yoki WEBP rasm yuklang")
    ensure_root()
    rel = Path("models") / f"{uuid.uuid4().hex}.{ext}"
    (MEDIA_ROOT / "models").mkdir(parents=True, exist_ok=True)
    (MEDIA_ROOT / rel).write_bytes(data)
    return str(rel)


def delete_image(rel_path: str | None) -> None:
    if not rel_path:
        return
    try:
        abs_path(rel_path).unlink(missing_ok=True)
    except OSError:
        pass


def read_image(card: ModelCard) -> bytes | None:
    if not card.image_file:
        return None
    try:
        return abs_path(card.image_file).read_bytes()
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Truck yaratish (bot bazasiga)
# --------------------------------------------------------------------------- #
async def suggest_serial(session: AsyncSession, model: str | None) -> str:
    """'T1-2026-004' ko'rinishidagi keyingi bo'sh seriya raqami."""
    prefix = re.sub(r"[^A-Za-z0-9]+", "", model or "") or "TRK"
    year = dt.datetime.now().year
    like = f"{prefix}-{year}-%"
    rows = (await session.execute(
        text("SELECT serial_number FROM public.trucks WHERE serial_number LIKE :p"), {"p": like}
    )).scalars().all()
    nums = [int(m.group(1)) for s in rows if (m := re.search(r"-(\d+)$", s))]
    return f"{prefix}-{year}-{(max(nums) + 1) if nums else 1:03d}"


async def create_truck(
    session: AsyncSession, *, serial: str, model: str, customer: str | None,
    priority: str, deadline: dt.date | None,
) -> int:
    """`web.create_truck` SQL funksiyasi orqali truck + 6 bosqich yaratadi. Truck ID'sini qaytaradi."""
    if priority not in PRIORITIES:
        priority = "normal"
    deadline_ts = (
        dt.datetime.combine(deadline, dt.time(12, 0), tzinfo=dt.timezone(dt.timedelta(hours=5)))
        if deadline else None
    )
    try:
        tid = await session.scalar(
            text("SELECT web.create_truck(:s, :m, :c, :p, :d)"),
            {"s": serial, "m": model, "c": customer or "", "p": priority, "d": deadline_ts},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateSerial(serial) from exc
    return int(tid)


async def recipients(session: AsyncSession) -> list[dict]:
    """Xabar oladiganlar: botdagi barcha faol foydalanuvchilar (ishchi, QC, admin)."""
    rows = (await session.execute(text(
        "SELECT telegram_id, full_name, role::text AS role, step_number, language "
        "FROM public.users WHERE is_active AND telegram_id IS NOT NULL ORDER BY id"
    ))).mappings().all()
    return [dict(r) for r in rows]
