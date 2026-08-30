from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def render(
    event: Message | CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    edit: bool | None = None,
) -> None:
    """Bitta kartani joyida yangilaydi: callback bo'lsa xabarni tahrirlaydi,
    xabar bo'lsa yangi javob yuboradi. `edit=False` — har doim yangi xabar."""
    if isinstance(event, CallbackQuery):
        msg = event.message
        do_edit = True if edit is None else edit
    else:
        msg = event
        do_edit = False if edit is None else edit

    if do_edit and msg is not None:
        try:
            await msg.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass  # matn o'zgarmagan yoki tahrirlab bo'lmaydi — yangi yuboramiz
    if msg is not None:
        await msg.answer(text, reply_markup=markup)
