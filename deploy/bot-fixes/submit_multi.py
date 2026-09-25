"""Ishchi — «Ish yuborish»: bir yuborishda 10 tagacha rasm, 5 tagacha video (va 3 tagacha fayl).

Oqim: (Ish yuborish) -> rasm/video/... ketma-ket tashlanadi -> «✅ Yuborish».
Bitta vazifasi bor ishchi tugmasiz to'g'ridan-to'g'ri rasm/video tashlasa ham bo'ladi.
Fayllar `truck_step_media` jadvaliga darrov (qoralama sifatida) yoziladi, «Yuborish» bosilganda yakunlanadi;
shu sababli albom (bir nechta rasm birdan) yuborilganda ham hech biri yo'qolmaydi.
Botning eski `truck_steps.media_*` ustunlarida asosiy (birinchi) fayl saqlanadi.

Bu fayl docker build paytida `src/bot/handlers/worker/submit.py` ni to'liq almashtiradi (deploy/bot-fixes/patch_bot.py).
"""
import asyncio
from pathlib import Path
from uuid import uuid4

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsWorker, text_key
from src.bot.keyboards import (
    worker_after_submit_keyboard,
    worker_submit_cancel_keyboard,
    worker_tasks_keyboard,
)
from src.bot.states import SubmitWorkFSM
from src.config import settings
from src.database.models.user import User
from src.services.i18n_service import _, get_step_name
from src.services.step_media_service import LIMITS
from src.services.truck_step_service import (
    claim_step,
    get_step_with_truck,
    get_worker_tasks,
    submit_step,
)
from src.utils.logger import logger


router = Router(name="worker_submit")

_MEDIA = F.photo | F.video | F.document

_T = {
    "uz": {
        "ask": "📸 <b>{truck}</b>\n🔧 {step}\n\nQilingan ishning <b>rasm va videolarini</b> yuboring.\n\n"
               "📷 {p} tagacha rasm, 🎥 {v} tagacha video mumkin. Ketma-ket tashlang, so'ng <b>✅ Yuborish</b> tugmasini bosing.\n\n"
               "<i>Xohlasangiz, rasm ostiga izoh yozing.</i>",
        "status": "✅ Qabul qilindi\n\n{counts}{note}\n\n➕ Yana rasm yoki video tashlashingiz mumkin.\n👇 Tayyor bo'lsa — <b>✅ Yuborish</b> tugmasini bosing.",
        "note": "\n📝 Izoh: {c}",
        "photo": "📷 Rasm", "video": "🎥 Video", "document": "📄 Fayl",
        "limit": "⚠️ Bunday fayldan {n} tadan ko'p yuborib bo'lmaydi. Ortiqchasi qabul qilinmadi.",
        "which": "📤 Qaysi ishni yubormoqchisiz? «Ish yuborish» tugmasini bosib, ishni tanlang.",
        "none": "Hozircha yuborish uchun ish yo'q.",
        "empty": "Avval rasm yoki video yuboring.",
        "taken": "⚠️ Bu ish allaqachon yuborilgan.",
        "invalid": "⚠️ Faqat rasm yoki video yuboring.\n\n📷 Rasm — kamera yoki galereyadan\n🎥 Video — telefondan",
        "sent": "\n📎 Yuborilgan fayllar: {n} ta",
        "send": "✅ Yuborish", "reset": "🗑 Boshidan", "cancel": "❌ Bekor qilish",
    },
    "uz_cyrl": {
        "ask": "📸 <b>{truck}</b>\n🔧 {step}\n\nҚилинган ишнинг <b>расм ва видеоларини</b> юборинг.\n\n"
               "📷 {p} тагача расм, 🎥 {v} тагача видео мумкин. Кетма-кет ташланг, сўнг <b>✅ Юбориш</b> тугмасини босинг.\n\n"
               "<i>Хоҳласангиз, расм остига изоҳ ёзинг.</i>",
        "status": "✅ Қабул қилинди\n\n{counts}{note}\n\n➕ Яна расм ёки видео ташлашингиз мумкин.\n👇 Тайёр бўлса — <b>✅ Юбориш</b> тугмасини босинг.",
        "note": "\n📝 Изоҳ: {c}",
        "photo": "📷 Расм", "video": "🎥 Видео", "document": "📄 Файл",
        "limit": "⚠️ Бундай файлдан {n} тадан кўп юбориб бўлмайди. Ортиқчаси қабул қилинмади.",
        "which": "📤 Қайси ишни юбормоқчисиз? «Иш юбориш» тугмасини босиб, ишни танланг.",
        "none": "Ҳозирча юбориш учун иш йўқ.",
        "empty": "Аввал расм ёки видео юборинг.",
        "taken": "⚠️ Бу иш аллақачон юборилган.",
        "invalid": "⚠️ Фақат расм ёки видео юборинг.\n\n📷 Расм — камера ёки галереядан\n🎥 Видео — телефондан",
        "sent": "\n📎 Юборилган файллар: {n} та",
        "send": "✅ Юбориш", "reset": "🗑 Бошидан", "cancel": "❌ Бекор қилиш",
    },
    "ru": {
        "ask": "📸 <b>{truck}</b>\n🔧 {step}\n\nОтправьте <b>фото и видео</b> выполненной работы.\n\n"
               "📷 до {p} фото, 🎥 до {v} видео. Отправляйте подряд, затем нажмите <b>✅ Отправить</b>.\n\n"
               "<i>Если хотите, напишите комментарий под фото.</i>",
        "status": "✅ Получено\n\n{counts}{note}\n\n➕ Можно отправить ещё фото или видео.\n👇 Когда всё готово — нажмите <b>✅ Отправить</b>.",
        "note": "\n📝 Комментарий: {c}",
        "photo": "📷 Фото", "video": "🎥 Видео", "document": "📄 Файл",
        "limit": "⚠️ Таких файлов нельзя отправить больше {n}. Лишнее не принято.",
        "which": "📤 Какую работу отправить? Нажмите «Отправить работу» и выберите её.",
        "none": "Сейчас нет работ для отправки.",
        "empty": "Сначала отправьте фото или видео.",
        "taken": "⚠️ Эта работа уже отправлена.",
        "invalid": "⚠️ Отправьте только фото или видео.\n\n📷 Фото — с камеры или галереи\n🎥 Видео — с телефона",
        "sent": "\n📎 Отправлено файлов: {n}",
        "send": "✅ Отправить", "reset": "🗑 Заново", "cancel": "❌ Отмена",
    },
}


def _lang(user: User) -> str:
    return user.language if user.language in _T else "uz"


def _kb(lang: str) -> InlineKeyboardMarkup:
    t = _T[lang]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t["send"], callback_data="worker_submit_confirm")],
            [
                InlineKeyboardButton(text=t["reset"], callback_data="worker_submit_restart"),
                InlineKeyboardButton(text=t["cancel"], callback_data="worker_submit_cancel"),
            ],
        ]
    )


# ==================== Qoralama fayllar (DB) ====================
async def _clear_drafts(session: AsyncSession, step_id: int | None, user_id: int) -> None:
    if step_id:
        await session.execute(
            text("DELETE FROM truck_step_media WHERE draft AND step_id = :s AND added_by_id = :u"),
            {"s": step_id, "u": user_id},
        )
    # tashlab ketilgan eski qoralamalarni ham tozalaymiz
    await session.execute(
        text("DELETE FROM truck_step_media WHERE draft AND created_at < now() - interval '12 hours'")
    )
    await session.commit()


async def _add_media(session: AsyncSession, step_id: int, user_id: int, mtype: str, file_id: str) -> int | None:
    """Faylni qoralamaga qo'shadi. Chegara to'lgan bo'lsa None. Bir vaqtda kelgan fayllar (albom) uchun xavfsiz."""
    await session.execute(text("SELECT pg_advisory_xact_lock(CAST(:k AS bigint))"), {"k": step_id})
    cnt = (
        await session.execute(
            text(
                "SELECT count(*) FROM truck_step_media "
                "WHERE draft AND step_id = :s AND added_by_id = :u AND media_type = :t"
            ),
            {"s": step_id, "u": user_id, "t": mtype},
        )
    ).scalar() or 0
    if cnt >= LIMITS[mtype]:
        await session.commit()
        return None
    rid = (
        await session.execute(
            text(
                "INSERT INTO truck_step_media (step_id, media_type, file_id, added_by_id, draft) "
                "VALUES (:s, :t, :f, :u, true) RETURNING id"
            ),
            {"s": step_id, "t": mtype, "f": file_id, "u": user_id},
        )
    ).scalar()
    await session.commit()
    return rid


async def _drafts(session: AsyncSession, step_id: int, user_id: int) -> list[tuple[int, str, str]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, media_type, file_id FROM truck_step_media "
                "WHERE draft AND step_id = :s AND added_by_id = :u ORDER BY id"
            ),
            {"s": step_id, "u": user_id},
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


async def _send_status(message: Message, state: FSMContext, session: AsyncSession, user: User, step_id: int) -> None:
    lang = _lang(user)
    t = _T[lang]
    rows = await _drafts(session, step_id, user.id)
    counts = {"photo": 0, "video": 0, "document": 0}
    for _id, mtype, _fid in rows:
        counts[mtype] = counts.get(mtype, 0) + 1
    lines = [f"{t[k]}: {counts[k]} / {LIMITS[k]}" for k in ("photo", "video", "document") if counts[k]]
    data = await state.get_data()
    c = data.get("worker_comment")
    note = t["note"].format(c=c) if c else ""
    old = data.get("status_msg_id")
    sent = await message.answer(
        t["status"].format(counts="\n".join(lines), note=note),
        reply_markup=_kb(lang),
    )
    await state.update_data(status_msg_id=getattr(sent, "message_id", None))
    if old:
        try:
            await message.bot.delete_message(message.chat.id, old)
        except Exception:  # noqa: BLE001 — eski xabar allaqachon o'chgan bo'lishi mumkin
            pass


# ==================== Boshlash ====================
async def _begin_submit(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    step_id: int,
) -> None:
    """Vazifani ishchiga biriktirib, rasm/video so'raydi."""
    lang = _lang(user)
    step = await get_step_with_truck(session, step_id)
    if not step or step.step_number != user.step_number or step.status not in ["pending", "rejected"]:
        await message.answer(_T[lang]["none"])
        return

    await claim_step(session, step, worker_id=user.id)
    await _clear_drafts(session, step_id, user.id)
    await state.clear()
    await state.update_data(step_id=step_id)
    await state.set_state(SubmitWorkFSM.media)
    await message.answer(
        _T[lang]["ask"].format(
            truck=step.truck.serial_number,
            step=get_step_name(step.step_number, lang),
            p=LIMITS["photo"],
            v=LIMITS["video"],
        ),
        reply_markup=worker_submit_cancel_keyboard(lang),
    )


@router.message(IsWorker(), text_key("worker.menu_submit"))
async def submit_from_menu(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
):
    """Reply tugmadan ish yuborish. Bitta vazifa bo'lsa — darrov rasm so'raymiz."""
    lang = user.language or "uz"

    tasks = await get_worker_tasks(session, user.id, user.step_number)

    if not tasks:
        await message.answer(_("worker.no_tasks_to_submit", language=lang))
        return

    if len(tasks) == 1:
        await _begin_submit(message, state, user, session, tasks[0].id)
        return

    await message.answer(
        _("worker.multiple_tasks_prompt", language=lang, count=len(tasks)),
        reply_markup=worker_tasks_keyboard(tasks, lang),
    )


@router.callback_query(IsWorker(), F.data.startswith("worker_submit:"))
async def start_submit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    session: AsyncSession,
):
    """Vazifa tugmasi bosilganda ish yuborishni boshlash."""
    lang = user.language or "uz"
    step_id = int(callback.data.split(":")[1])

    step = await get_step_with_truck(session, step_id)
    if not step:
        await callback.answer(_("common.not_found", language=lang), show_alert=True)
        return
    if step.step_number != user.step_number:
        await callback.answer(_("worker.wrong_step", language=lang), show_alert=True)
        return
    if step.status not in ["pending", "rejected"]:
        await callback.answer(_("worker.already_submitted", language=lang), show_alert=True)
        return

    await callback.answer()
    await _begin_submit(callback.message, state, user, session, step_id)


# ==================== Rasm / video / fayl qabul qilish ====================
@router.message(IsWorker(), SubmitWorkFSM.media, _MEDIA)
@router.message(IsWorker(), SubmitWorkFSM.confirm, _MEDIA)
@router.message(IsWorker(), StateFilter(None), F.photo | F.video)  # tugmasiz: bitta vazifa bo'lsa darrov qabul qilamiz
async def receive_media(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
):
    lang = _lang(user)
    t = _T[lang]
    data = await state.get_data()
    step_id = data.get("step_id")

    if not step_id:
        tasks = await get_worker_tasks(session, user.id, user.step_number)
        if len(tasks) != 1:
            await message.answer(t["which"] if tasks else t["none"])
            return
        step_id = tasks[0].id
        await claim_step(session, tasks[0], worker_id=user.id)
        await session.commit()
        await state.update_data(step_id=step_id)

    if message.photo:
        mtype, file_id = "photo", message.photo[-1].file_id
    elif message.video:
        mtype, file_id = "video", message.video.file_id
    else:
        mtype, file_id = "document", message.document.file_id

    cap = (message.caption or "").strip()
    if cap:
        await state.update_data(worker_comment=cap[:1000])
    await state.set_state(SubmitWorkFSM.confirm)

    rid = await _add_media(session, step_id, user.id, mtype, file_id)
    if rid is None:
        await message.answer(t["limit"].format(n=LIMITS[mtype]))
        return

    # Albom (bir nechta rasm birdan) — har biriga alohida javob bermaymiz: faqat oxirgisi holatni yozadi
    await asyncio.sleep(1.0)
    latest = (
        await session.execute(
            text("SELECT max(id) FROM truck_step_media WHERE draft AND step_id = :s AND added_by_id = :u"),
            {"s": step_id, "u": user.id},
        )
    ).scalar()
    if latest != rid:
        return
    await _send_status(message, state, session, user, step_id)


@router.message(IsWorker(), SubmitWorkFSM.media)
async def invalid_media(message: Message, user: User):
    """Rasm/video emas."""
    lang = _lang(user)
    await message.answer(_T[lang]["invalid"], reply_markup=worker_submit_cancel_keyboard(lang))


# ==================== Yuborish ====================
@router.callback_query(SubmitWorkFSM.confirm, F.data == "worker_submit_confirm")
async def confirm_submit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    bot: Bot,
):
    """Ishni yuborish."""
    lang = user.language or "uz"
    t = _T[_lang(user)]
    data = await state.get_data()

    step_id = data.get("step_id")
    step = await get_step_with_truck(session, step_id) if step_id else None
    if not step:
        await callback.answer(_("common.not_found", language=lang), show_alert=True)
        await state.clear()
        return
    if step.status not in ["pending", "rejected"]:
        await callback.answer(t["taken"], show_alert=True)
        await _clear_drafts(session, step_id, user.id)
        await state.clear()
        return

    items = await _drafts(session, step_id, user.id)
    if not items:
        await callback.answer(t["empty"], show_alert=True)
        return
    await callback.answer()

    loading_msg = await callback.message.answer(_("worker.submit_loading", language=lang))

    # Fayllarni serverga ham saqlab qo'yamiz (Telegram file_id baribir saqlanadi)
    folder = Path(settings.MEDIA_ROOT) / "trucks" / str(step.truck_id) / f"step_{step.step_number}"
    ext_map = {"photo": ".jpg", "video": ".mp4", "document": ".bin"}
    locals_: dict[int, str | None] = {}
    for rid, mtype, file_id in items:
        path = None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            file = await bot.get_file(file_id)
            local = folder / f"{uuid4().hex}{ext_map.get(mtype, '.bin')}"
            await bot.download_file(file.file_path, destination=str(local))
            path = str(local)
        except Exception as e:  # noqa: BLE001 — masalan 20 MB dan katta video: web uni Telegram'dan olmaydi, lekin QC botda ko'radi
            logger.error(f"❌ Media saqlashda xato: {e}")
        locals_[rid] = path
        if path:
            await session.execute(
                text("UPDATE truck_step_media SET local_path = :p WHERE id = :i"), {"p": path, "i": rid}
            )

    # Asosiy fayl (izoh va tugmalar bilan ko'rsatiladigani): birinchi rasm, bo'lmasa video, bo'lmasa fayl
    primary = next((i for i in items if i[1] == "photo"), None) \
        or next((i for i in items if i[1] == "video"), None) or items[0]

    # avvalgi urinishdagi (qaytarilgan) fayllarni almashtiramiz
    await session.execute(
        text("DELETE FROM truck_step_media WHERE step_id = :s AND NOT draft"), {"s": step_id}
    )
    await session.execute(
        text("UPDATE truck_step_media SET draft = false WHERE draft AND step_id = :s AND added_by_id = :u"),
        {"s": step_id, "u": user.id},
    )

    await submit_step(
        session=session,
        step=step,
        worker_id=user.id,
        media_type=primary[1],
        media_file_id=primary[2],
        media_local_path=locals_.get(primary[0]),
        worker_comment=data.get("worker_comment"),
        bot=bot,
    )
    await session.commit()
    await state.clear()

    try:
        await loading_msg.delete()
    except Exception:  # noqa: BLE001
        pass

    await callback.message.answer(
        _(
            "worker.submit_success",
            language=lang,
            truck=step.truck.serial_number,
            step=get_step_name(step.step_number, lang),
        )
        + t["sent"].format(n=len(items)),
        reply_markup=worker_after_submit_keyboard(lang),
    )


# ==================== Boshidan ====================
@router.callback_query(SubmitWorkFSM.confirm, F.data == "worker_submit_restart")
async def restart_submit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    session: AsyncSession,
):
    """Yig'ilgan fayllarni o'chirib, boshidan boshlash."""
    lang = _lang(user)
    data = await state.get_data()
    await _clear_drafts(session, data.get("step_id"), user.id)
    await callback.answer()
    await state.update_data(status_msg_id=None, worker_comment=None)
    await state.set_state(SubmitWorkFSM.media)
    step = await get_step_with_truck(session, data["step_id"]) if data.get("step_id") else None
    ask = _T[lang]["ask"].format(
        truck=step.truck.serial_number if step else "",
        step=get_step_name(step.step_number, lang) if step else "",
        p=LIMITS["photo"],
        v=LIMITS["video"],
    )
    try:
        await callback.message.edit_text(ask, reply_markup=worker_submit_cancel_keyboard(lang))
    except Exception:  # noqa: BLE001
        await callback.message.answer(ask, reply_markup=worker_submit_cancel_keyboard(lang))


# ==================== Bekor qilish ====================
@router.callback_query(F.data == "worker_submit_cancel")
async def cancel_submit(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    session: AsyncSession,
):
    """Bekor qilish."""
    lang = user.language or "uz"
    data = await state.get_data()
    await _clear_drafts(session, data.get("step_id"), user.id)
    await callback.answer(_("common.cancel", language=lang))
    await state.clear()
    try:
        await callback.message.edit_text(_("common.cancelled", language=lang))
    except Exception:  # noqa: BLE001
        await callback.message.answer(_("common.cancelled", language=lang))
