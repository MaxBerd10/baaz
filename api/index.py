"""Vercel serverless kirish nuqtasi — FastAPI (ASGI) ilovasi.

`vercel.json` dagi rewrite barcha yo'llarni shu funksiyaga yo'naltiradi.
`app` nomli ASGI ilovasini Vercel avtomat aniqlaydi.
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# Nisbiy `demo.db` yo'lini paket ildiziga nisbatan absolyut qilamiz —
# serverless funksiyaning ishchi papkasi (cwd) noaniq bo'lishi mumkin.
_db = os.environ.get("DATABASE_URL", "")
if "demo.db" in _db and "file:/" not in _db:
    abs_db = (_ROOT / "demo.db").as_posix()
    os.environ["DATABASE_URL"] = (
        f"sqlite+aiosqlite:///file:{abs_db}?mode=ro&immutable=1&uri=true"
    )

from app.web.main import app  # noqa: E402

__all__ = ["app"]
