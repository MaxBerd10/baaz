"""Bir bosqichga bir nechta rasm/video (docker build paytida botga `src/services/step_media_service.py` sifatida qo'yiladi).

Jadval `truck_step_media` (deploy/bot-compat.sql yaratadi): har bir yuborilgan fayl — bitta qator.
`draft = true` — ishchi hali «Yuborish»ni bosmagan (yig'ilayotgan) fayllar.
Botning eski ustunlari (`truck_steps.media_*`) ham to'ldiriladi: ularda asosiy (birinchi) fayl turadi.
"""
from aiogram.types import InputMediaPhoto, InputMediaVideo, Message
from sqlalchemy import text

from src.database.session import async_session_maker
from src.utils.logger import logger

# Bir yuborishdagi eng ko'p fayl soni
LIMITS = {"photo": 10, "video": 5, "document": 3}


async def send_extra_media(message: Message, step_id: int, primary_file_id: str | None) -> None:
    """Bosqichdagi asosiy fayldan boshqa hamma rasm/videolarni (albom qilib) yuboradi.

    Asosiy fayl chaqiruvchi kodda izoh va tugmalar bilan yuboriladi. Xatolik asosiy oqimni buzmasligi kerak.
    """
    try:
        async with async_session_maker() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT media_type, file_id FROM truck_step_media "
                        "WHERE step_id = :s AND NOT draft AND file_id <> COALESCE(:p, '') ORDER BY id"
                    ),
                    {"s": step_id, "p": primary_file_id},
                )
            ).all()
        if not rows:
            return
        visual = [
            InputMediaVideo(media=fid) if mtype == "video" else InputMediaPhoto(media=fid)
            for mtype, fid in rows
            if mtype in ("photo", "video")
        ]
        for i in range(0, len(visual), 10):
            chunk = visual[i : i + 10]
            if len(chunk) == 1:
                one = chunk[0]
                if isinstance(one, InputMediaVideo):
                    await message.answer_video(video=one.media)
                else:
                    await message.answer_photo(photo=one.media)
            else:
                await message.answer_media_group(media=chunk)
        for mtype, fid in rows:
            if mtype == "document":
                await message.answer_document(document=fid)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ Qo'shimcha media yuborilmadi (step {step_id}): {e}")
