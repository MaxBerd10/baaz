from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo

from app.enums import MediaType
from app.models import StageRun
from app.services.media_store import abs_path

log = logging.getLogger("bot.media")


async def send_run_media(bot: Bot, chat_id: int, run: StageRun) -> None:
    """Bosqichdagi barcha rasm/videoni chatga yuboradi (10 tadan guruhlab)."""
    items = list(run.media)
    if not items:
        await bot.send_message(chat_id, "📎 Bu bosqichda media yo'q.")
        return

    batch: list = []
    for m in items:
        path = abs_path(m.file_path)
        if not path.exists():
            log.warning("media file missing: %s", path)
            continue
        file = FSInputFile(str(path))
        if m.type == MediaType.photo:
            batch.append(InputMediaPhoto(media=file))
        else:
            batch.append(InputMediaVideo(media=file))
        if len(batch) == 10:
            await bot.send_media_group(chat_id, batch)
            batch = []
    if batch:
        await bot.send_media_group(chat_id, batch)
