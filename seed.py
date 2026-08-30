"""Bazani tayyorlash: jadvallar + boshlang'ich bosqichlar.

Ishlatish:  python seed.py
"""
from __future__ import annotations

import asyncio

from app.config import settings
from app.db import SessionLocal, init_db
from app.services import stages as stages_svc
from app.services.media_store import ensure_root


async def main() -> None:
    await init_db()
    ensure_root()
    async with SessionLocal() as session:
        count = await stages_svc.ensure_seeded(session)
        await session.commit()
        rows = await stages_svc.list_stages(session)

    print(f"✅ Baza tayyor. Faol bosqichlar: {count}")
    for s in rows:
        print(f"   {s.order_no}. {s.name}")
    print()
    print("Keyingi qadamlar:")
    print("  1) .env faylini to'ldiring (BOT_TOKEN, ADMIN_TELEGRAM_IDS, WEB_PASSWORD)")
    print("  2) Bot:  python run_bot.py")
    print(f"  3) Web:  python run_web.py   ->  http://localhost:{settings.web_port}")
    print()
    print("Botda admin /start bosadi -> «🏭 Bosqichlar» dan nomlarni sozlaydi,")
    print("«👥 Xodimlar» dan ishchi/sifat rollarini biriktiradi.")


if __name__ == "__main__":
    asyncio.run(main())
