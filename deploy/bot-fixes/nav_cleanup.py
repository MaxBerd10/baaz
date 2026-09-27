"""Telegram chatda 'axlat' bo'lib qolmasligi uchun: pastdagi menyu tugmasi
(«📋 Vazifalarim», «📤 Ish yuborish», «📊 Statistika» va h.k.) bosilganda, bot javobi
oldingi shunday javobning O'RNINI oladi — eski ekran avtomatik o'chiriladi, chatda faqat
oxirgi ekran qoladi. Faqat menyu tugmalariga tegishli: bildirishnomalar (yangi ish keldi,
tasdiqlandi/rad etildi) va foydalanuvchining o'z yozgan xabarlari (masalan rad etish sababi)
tegilmaydi, chunki ular alohida yo'l bilan (bot.send_message) yuboriladi yoki bu filterga
mos kelmaydi.

docker build paytida `src/services/nav_cleanup.py` sifatida qo'yiladi (deploy/bot-fixes/patch_bot.py).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from src.bot.handlers.common import _get_all_menu_buttons, _get_all_translations

# Bot o'zining `_get_all_menu_buttons()`da ro'yxatlagan tugmalari + shu ro'yxatda yo'q
# QC tarixi/statistikasi tugmalari (worker/admin bilan bir xil matn, lekin ro'yxatga
# faqat qc.menu_queue kiritilgan edi).
_MENU_BUTTONS: set[str] = set(_get_all_menu_buttons())
_MENU_BUTTONS.update(_get_all_translations("qc.menu_history"))
_MENU_BUTTONS.update(_get_all_translations("qc.menu_stats"))

# chat_id -> shu chatda oxirgi marta ko'rsatilgan "menyu ekrani"ning xabar id'si
_last_nav: dict[int, int] = {}


def _wrap_send(bound_method: Callable[..., Awaitable[Any]], chat_id: int, state: dict) -> Callable[..., Awaitable[Any]]:
    async def sender(*args, **kwargs):
        if not state["cleaned"]:
            state["cleaned"] = True
            old_id = _last_nav.get(chat_id)
            if old_id:
                try:
                    await bound_method.__self__.bot.delete_message(chat_id, old_id)
                except Exception:  # noqa: BLE001 — 48 soatdan eski yoki allaqachon o'chirilgan bo'lishi mumkin
                    pass
        result = await bound_method(*args, **kwargs)
        msgs = result if isinstance(result, list) else [result]
        if msgs and msgs[-1] is not None:
            _last_nav[chat_id] = msgs[-1].message_id
        return result

    return sender


class NavCleanupMiddleware(BaseMiddleware):
    """Faqat pastdagi menyu tugmasi bosilgan xabarlarda ishlaydi (yuqoridagi izohga qarang)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        msg = getattr(event, "message", None)
        if not (isinstance(msg, Message) and msg.text and msg.text in _MENU_BUTTONS):
            return await handler(event, data)

        chat_id = msg.chat.id
        state = {"cleaned": False}
        for attr in ("answer", "answer_photo", "answer_document", "answer_video", "answer_media_group"):
            bound = getattr(msg, attr, None)
            if bound is not None:
                object.__setattr__(msg, attr, _wrap_send(bound, chat_id, state))
        return await handler(event, data)
