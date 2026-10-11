"""Mini App API sinovlari uchun umumiy tayyorgarlik.

Sinovlar HAQIQIY Postgres bazasini talab qiladi (bot jadvallari + web ko'rinishlari o'rnatilgan):
    BOT_DB=1 DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5544/truck_factory \\
    BOT_TOKEN=123456:TEST SECRET_KEY=test-secret MEDIA_ROOT=/tmp/baaz_test_media \\
    MINIAPP_URL=https://example.test/app pytest tests -q
Muhit o'zgaruvchilari bo'lmasa sinovlar o'tkazib yuboriladi.
"""
from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest

NEEDED = ("BOT_DB", "DATABASE_URL", "BOT_TOKEN", "SECRET_KEY", "MEDIA_ROOT", "MINIAPP_URL")
READY = all(os.environ.get(k) for k in NEEDED)


def pytest_collection_modifyitems(config, items):
    if not READY:
        skip = pytest.mark.skip(reason="Mini App sinovi uchun muhit o'zgaruvchilari kerak (tests/conftest.py ga qarang)")
        for it in items:
            it.add_marker(skip)


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1).split("?")[0]


def sql(query: str, *args):
    """Sinov ma'lumotini tayyorlash/tekshirish uchun alohida ulanish (ilovaning o'z ulanishidan mustaqil)."""
    async def run():
        conn = await asyncpg.connect(_dsn())
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()
    return asyncio.run(run())


USERS = {  # nom -> (telegram_id, rol, bosqich)
    "w1": (910001, "worker", 1), "w1b": (910002, "worker", 1), "w2": (910003, "worker", 2),
    "qc": (910004, "qc", None), "admin": (910005, "admin", None), "off": (910006, "worker", 1),
}


@pytest.fixture(scope="session", autouse=True)
def seed():
    if not READY:
        return
    for name, (tg, role, step) in USERS.items():
        sql("INSERT INTO public.users (telegram_id, full_name, role, step_number, is_active, language) "
            "VALUES ($1, $2, $3::user_role, $4, $5, 'uz') ON CONFLICT (telegram_id) DO UPDATE SET "
            "role = EXCLUDED.role, step_number = EXCLUDED.step_number, is_active = EXCLUDED.is_active",
            tg, f"Test {name}", role, step, name != "off")
    sql("INSERT INTO web.model_cards (name, description, is_active, created_at) VALUES ('TST', 'Sinov modeli', true, now()) "
        "ON CONFLICT (name) DO NOTHING")


@pytest.fixture(scope="session")
def client():
    """Bitta TestClient butun sessiya uchun: ilovaning DB ulanishlari bitta event loop'ga bog'langan bo'ladi."""
    from fastapi.testclient import TestClient

    import app.services.miniapp_notify as n
    from app.web.main import app

    mp = pytest.MonkeyPatch()
    # Standart: Telegram'ga umuman chiqmaymiz (menyu tugmasi, xabarlar). `sent` fixture buni o'z yig'uvchisi bilan almashtiradi.
    mp.setattr(n, "_api", lambda *a, **k: {"ok": True, "result": {}})
    try:
        with TestClient(app) as c:
            yield c
    finally:
        mp.undo()


@pytest.fixture()
def sent(monkeypatch):
    """Telegram'ga ketadigan xabarlarni yig'adi (tarmoqqa chiqmaydi)."""
    import app.services.miniapp_notify as n

    box: list[dict] = []

    def fake(method, fields, file=None, timeout=20, field="photo"):
        box.append({"method": method, **fields, "has_file": bool(file)})
        return {"ok": True, "result": {"photo": [{"file_id": "FID-TEST"}], "video": {"file_id": "FID-VID"}}}

    monkeypatch.setattr(n, "_api", fake)
    return box
