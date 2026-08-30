"""Vercel serverless kirish nuqtasi — FastAPI (ASGI) ilovasi.

Vercel `@vercel/python` `app` nomli ASGI ilovasini avtomat aniqlaydi.
Barcha yo'llar `vercel.json` orqali shu funksiyaga yo'naltiriladi.
"""
import sys
from pathlib import Path

# Loyiha ildizini import yo'liga qo'shamiz (app/ paketi uchun).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.web.main import app  # noqa: E402

__all__ = ["app"]
