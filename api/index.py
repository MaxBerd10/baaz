"""Vercel serverless kirish nuqtasi — FastAPI (ASGI) ilovasi.

`vercel.json` dagi rewrite barcha yo'llarni shu funksiyaga yo'naltiradi.
"""
import os
import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# Baza: berilmagan yoki demo.db ga ishora qilsa — Vercel'ning yoziladigan /tmp
# papkasida yaratamiz va cold-start'da demo bilan to'ldiramiz.
_db = os.environ.get("DATABASE_URL", "")
if (not _db) or ("demo.db" in _db) or _db.startswith("sqlite+aiosqlite:///./"):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/baaz.db"
    os.environ.setdefault("AUTO_SEED", "1")
    os.environ.pop("SKIP_INIT_DB", None)
os.environ.setdefault("MEDIA_ROOT", "/tmp/media")

try:
    from app.web.main import app  # noqa: E402
except Exception:  # pragma: no cover
    _tb = traceback.format_exc()

    async def app(scope, receive, send):  # type: ignore
        if scope["type"] != "http":
            return
        body = ("IMPORT ERROR\n\n" + _tb).encode()
        await send({"type": "http.response.start", "status": 500,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": body})

__all__ = ["app"]
