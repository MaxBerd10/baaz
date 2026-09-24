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


# --------------------------------------------------------------------------- #
# Bot rejimi: fayl botning serverida (yoki Telegram'da) — web Telegram'dan oladi
# --------------------------------------------------------------------------- #
import os as _os

_TG_API = _os.environ.get("TELEGRAM_API", "https://api.telegram.org").rstrip("/")
_TG_MAX_BYTES = 4_000_000  # Vercel funksiya javobi ~4.5MB bilan cheklangan


def _tg_fetch_sync(token: str, file_id: str) -> tuple[bytes, str] | None:
    import json
    import mimetypes
    import urllib.parse
    import urllib.request

    try:
        q = urllib.parse.urlencode({"file_id": file_id})
        with urllib.request.urlopen(
            f"{_TG_API}/bot{token}/getFile?{q}", timeout=8
        ) as r:
            info = json.load(r)
        if not info.get("ok"):
            return None
        tg_path = info["result"]["file_path"]
        size = info["result"].get("file_size") or 0
        if size and size > _TG_MAX_BYTES:
            return None
        with urllib.request.urlopen(
            f"{_TG_API}/file/bot{token}/{tg_path}", timeout=15
        ) as r:
            data = r.read(_TG_MAX_BYTES + 1)
        if len(data) > _TG_MAX_BYTES:
            return None
        ctype = mimetypes.guess_type(tg_path)[0] or "application/octet-stream"
        return data, ctype
    except Exception:  # noqa: BLE001 — tarmoq/Telegram xatosi: o'rin egallovchi ko'rsatiladi
        return None


async def fetch_telegram(file_id: str) -> tuple[bytes, str] | None:
    """Telegram file_id bo'yicha faylni (bayt, content-type) qaytaradi.
    Token faqat serverda qoladi, brauzerga hech qachon berilmaydi."""
    import asyncio

    token = settings.bot_token
    if not token or not file_id:
        return None
    return await asyncio.to_thread(_tg_fetch_sync, token, file_id)
