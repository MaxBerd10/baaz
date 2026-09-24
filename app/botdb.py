"""Bot bazasiga web ko'rinishlarini (VIEW) o'rnatish.

    python -m app.botdb install     # `web` sxemasidagi VIEW'larni yaratadi/yangilaydi
    python -m app.botdb check       # bot jadvallari va ko'rinishlar mavjudligini tekshiradi

DATABASE_URL — `truck-factory-bot` ishlatadigan Postgres bazasi (avval botning
`alembic upgrade head` buyrug'i bajarilgan bo'lishi kerak).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

from app.db import _connect_args, _url

SQL_FILE = Path(__file__).with_name("bot_views.sql")
VIEWS = ["stages", "users", "products", "stage_runs", "media", "audit_logs",
         "stage_check_items", "stage_run_checks", "truck_models"]


def _dsn() -> str:
    if _url.startswith("sqlite"):
        sys.exit("DATABASE_URL Postgres bo'lishi kerak (hozir SQLite).")
    return _url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(_dsn(), ssl=_connect_args.get("ssl"),
                                 statement_cache_size=0)


async def install() -> None:
    conn = await _connect()
    try:
        have = {r["t"] for r in await conn.fetch(
            "select table_name t from information_schema.tables where table_schema='public'")}
        missing = {"users", "trucks", "truck_steps"} - have
        if missing:
            sys.exit(f"Bot jadvallari topilmadi: {sorted(missing)}. "
                     "Avval botda `alembic upgrade head` ni ishga tushiring.")
        await conn.execute(SQL_FILE.read_text(encoding="utf-8"))
        print("✅ web ko'rinishlari o'rnatildi:", ", ".join(VIEWS))
    finally:
        await conn.close()


async def check() -> None:
    conn = await _connect()
    try:
        for v in VIEWS:
            n = await conn.fetchval(f"select count(*) from web.{v}")
            print(f"web.{v:<18} {n} qator")
    finally:
        await conn.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "install"
    fn = {"install": install, "check": check}.get(cmd)
    if fn is None:
        sys.exit(__doc__)
    asyncio.run(fn())
