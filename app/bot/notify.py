from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup

from app.models import User

log = logging.getLogger("bot.notify")


async def send_many(
    bot: Bot, users: list[User], text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    for u in users:
        if not u.telegram_id:
            continue
        try:
            await bot.send_message(u.telegram_id, text, reply_markup=markup)
        except TelegramAPIError as exc:  # pragma: no cover
            log.warning("notify failed for %s: %s", u.telegram_id, exc)


async def send_one(
    bot: Bot, user: User | None, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    if user is None or not user.telegram_id:
        return
    try:
        await bot.send_message(user.telegram_id, text, reply_markup=markup)
    except TelegramAPIError as exc:  # pragma: no cover
        log.warning("notify failed for %s: %s", user.telegram_id, exc)
