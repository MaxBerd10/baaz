from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.handlers import admin, common, qc, worker
from app.bot.keyboards import menu_for
from app.models import User

fallback = Router()


@fallback.callback_query(F.data == "noop")
async def _noop(cb: CallbackQuery) -> None:
    await cb.answer()


@fallback.message()
async def _unknown(message: Message, user: User | None = None) -> None:
    await message.answer(
        "Tushunmadim. Menyudan tanlang. 👇", reply_markup=menu_for(user)
    )


def build_router() -> Router:
    root = Router()
    root.include_router(common.router)
    root.include_router(admin.router)
    root.include_router(qc.router)
    root.include_router(worker.router)
    root.include_router(fallback)
    return root
