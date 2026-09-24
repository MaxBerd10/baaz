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
# Bot rejimi: fayl botning diskida (umumiy papka) yoki Telegram'da bo'ladi
# --------------------------------------------------------------------------- #
import hashlib
import mimetypes
import os as _os

_TG_API = _os.environ.get("TELEGRAM_API", "https://api.telegram.org").rstrip("/")
# Serverda (Docker) Telegram limiti 20MB; Vercel funksiya javobi ~4.5MB bilan cheklangan.
_SERVERLESS = bool(_os.environ.get("VERCEL") or _os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
_TG_MAX_BYTES = 4_000_000 if _SERVERLESS else 20_000_000

# Botning media papkasi web konteynerida shu yerga ulanadi (compose: bot_media -> /botmedia).
BOT_MEDIA_ROOT = _os.environ.get("BOT_MEDIA_ROOT", "")
BOT_MEDIA_PREFIX = _os.environ.get("BOT_MEDIA_PREFIX", "/app/media").rstrip("/")


def _inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def resolve_local(file_path: str | None) -> Path | None:
    """Media yozuvidagi yo'lni serverdagi haqiqiy faylga aylantiradi (yo'q bo'lsa None).
    Bot yo'lni o'z konteynerida yozadi (/app/media/...) — uni web'ga ulangan papkaga moslaymiz."""
    if not file_path:
        return None
    cands: list[tuple[Path, Path]] = []
    if BOT_MEDIA_ROOT:
        root = Path(BOT_MEDIA_ROOT)
        rel = None
        if file_path.startswith(BOT_MEDIA_PREFIX + "/"):
            rel = file_path[len(BOT_MEDIA_PREFIX) + 1:]
        elif not file_path.startswith("/"):
            rel = file_path[6:] if file_path.startswith("media/") else file_path
        if rel:
            cands.append((root / rel, root))
    if not file_path.startswith("/"):
        cands.append((abs_path(file_path), MEDIA_ROOT))
    for p, root in cands:
        if p.is_file() and _inside(p, root):
            return p
    return None


def guess_type(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in (".mov", ".mp4", ".m4v"):
        return "video/mp4"  # brauzerlar H.264 .mov ni ham shu tur bilan o'ynaydi
    return mimetypes.guess_type(p.name)[0] or "application/octet-stream"


def _tg_download_sync(token: str, file_id: str, dest_dir: Path) -> Path | None:
    import json
    import urllib.parse
    import urllib.request

    try:
        q = urllib.parse.urlencode({"file_id": file_id})
        with urllib.request.urlopen(f"{_TG_API}/bot{token}/getFile?{q}", timeout=8) as r:
            info = json.load(r)
        if not info.get("ok"):
            return None
        tg_path = info["result"]["file_path"]
        size = info["result"].get("file_size") or 0
        if size and size > _TG_MAX_BYTES:
            return None
        ext = Path(tg_path).suffix or ".bin"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (hashlib.sha1(file_id.encode()).hexdigest() + ext)
        tmp = dest.with_suffix(dest.suffix + ".part")
        total = 0
        with urllib.request.urlopen(f"{_TG_API}/file/bot{token}/{tg_path}", timeout=60) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 16):
                total += len(chunk)
                if total > _TG_MAX_BYTES:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    return None
                f.write(chunk)
        tmp.replace(dest)
        return dest
    except Exception:  # noqa: BLE001 — tarmoq/Telegram xatosi: o'rin egallovchi ko'rsatiladi
        return None


async def telegram_cached(file_id: str) -> Path | None:
    """Telegram file_id bo'yicha faylni diskka keshlab, yo'lini qaytaradi (Range so'rovlari uchun).
    Token faqat serverda qoladi, brauzerga hech qachon berilmaydi."""
    import asyncio

    token = settings.bot_token
    if not token or not file_id:
        return None
    cache_dir = MEDIA_ROOT / "tgcache"
    prefix = hashlib.sha1(file_id.encode()).hexdigest()
    try:
        hit = next((p for p in cache_dir.glob(prefix + ".*") if not p.name.endswith(".part")), None)
    except OSError:
        hit = None
    if hit:
        return hit
    return await asyncio.to_thread(_tg_download_sync, token, file_id, cache_dir)
