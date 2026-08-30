from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.bot.handlers import build_router
from app.bot.middlewares import AuthMiddleware, DbSessionMiddleware
from app.config import settings
from app.db import SessionLocal, init_db
from app.services import stages as stages_svc
from app.services.media_store import ensure_root

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")


async def _bootstrap() -> None:
    await init_db()
    ensure_root()
    async with SessionLocal() as session:
        count = await stages_svc.ensure_seeded(session)
        await session.commit()
    log.info("Bootstrap tayyor. Faol bosqichlar: %s", count)


async def main() -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN .env faylida ko'rsatilmagan.")

    await _bootstrap()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # outer_middleware — filtrlardan OLDIN ishlaydi, shunda RoleFilter `user` ni ko'radi
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(DbSessionMiddleware())
        observer.outer_middleware(AuthMiddleware())

    dp.include_router(build_router())

    await bot.set_my_commands([
        BotCommand(command="start", description="Boshlash / menyu"),
        BotCommand(command="help", description="Qo'llanma"),
        BotCommand(command="cancel", description="Joriy amalni bekor qilish"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Bot ishga tushdi.")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
