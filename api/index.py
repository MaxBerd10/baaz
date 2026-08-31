"""Vercel serverless kirish nuqtasi — FastAPI (ASGI) ilovasi.

`vercel.json` dagi rewrite barcha yo'llarni shu funksiyaga yo'naltiradi.
"""
import os
import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# --- Vercel muhitini majburan to'g'rilaymiz (dashboard'dagi eski qiymatlardan qat'i nazar) ---
_db = os.environ.get("DATABASE_URL", "").strip()
_is_real_pg = _db.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://"))
if not _is_real_pg:
    # SQLite: yagona ishonchli joy — yoziladigan /tmp. Cold-start'da demo bilan to'ldiriladi.
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/baaz.db"
    os.environ["AUTO_SEED"] = "1"
    os.environ.pop("SKIP_INIT_DB", None)
# Media ham faqat /tmp da yozila oladi.
os.environ["MEDIA_ROOT"] = "/tmp/media"
os.environ.setdefault("SHOW_ERRORS", "1")

try:
    from app.web.main import app  # noqa: E402
except Exception:  # pragma: no cover
    _tb = traceback.format_exc()

    async def app(scope, receive, send):  # type: ignore
        if scope["type"] != "http":
            if scope["type"] == "lifespan":
                msg = await receive()
                await send({"type": msg["type"] + ".complete"})
            return
        body = ("IMPORT ERROR\n\n" + _tb).encode()
        await send({"type": "http.response.start", "status": 500,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": body})

__all__ = ["app"]
