from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings

MEDIA_ROOT = Path(settings.media_root)


def ensure_root() -> None:
    try:
        MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Faqat-o'qish uchun fayl tizimi (masalan Vercel) — e'tiborsiz qoldiramiz.
        pass


def abs_path(rel_path: str) -> Path:
    return MEDIA_ROOT / rel_path


async def save_from_telegram(
    bot, file_id: str, *, product_code: str, stage_order: int, ext: str
) -> str:
    """Telegram faylini lokal papkaga yuklab, MEDIA_ROOT ga nisbatan yo'lni qaytaradi."""
    ensure_root()
    rel_dir = Path(product_code) / f"stage_{stage_order:02d}"
    (MEDIA_ROOT / rel_dir).mkdir(parents=True, exist_ok=True)
    rel_path = rel_dir / f"{uuid.uuid4().hex}.{ext.lstrip('.')}"
    tg_file = await bot.get_file(file_id)
    await bot.download_file(tg_file.file_path, destination=str(MEDIA_ROOT / rel_path))
    return str(rel_path)
