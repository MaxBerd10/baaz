from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot import texts
from app.bot.filters import RoleFilter
from app.bot.notify import send_many
from app.bot.states import WorkerFlow
from app.bot.ui import render
from app.enums import MediaType, Role, StageRunStatus
from app.models import StageRun, User
from app.services import products as products_svc
from app.services import stages as stages_svc
from app.services import users as users_svc
from app.services import workflow
from app.services.media_store import save_from_telegram

router = Router()
router.message.filter(RoleFilter(Role.worker))
router.callback_query.filter(RoleFilter(Role.worker))


async def _load_run(cb: CallbackQuery, session: AsyncSession, user: User, run_id: int) -> StageRun | None:
    run = await workflow.get_run(session, run_id)
    if run is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return None
    if not user.stage or run.stage_order != user.stage.order_no:
        await cb.answer("Bu bosqich sizga tegishli emas.", show_alert=True)
        return None
    if run.status != StageRunStatus.in_progress:
        await cb.answer("Bu bosqich hozir tahrirlanmaydi.", show_alert=True)
        return None
    return run


async def _render_card(event, session: AsyncSession, run: StageRun, kind: str = "active") -> None:
    total = await stages_svc.active_count(session)
    items = await stages_svc.list_check_items(session, run.stage_id)
    await render(
        event,
        texts.worker_card(run.product, run, total, [i.text for i in items]),
        kb.worker_product_card(run, kind),
    )


async def _render_list(event, session: AsyncSession, user: User, kind: str) -> None:
    if kind == "returned":
        items = await products_svc.worker_returned(session, user)
        head = f"🔴 <b>Qaytarilganlar</b> ({len(items)})"
    else:
        items = await products_svc.worker_active(session, user)
        head = f"👷 {user.stage.order_no}-bosqich · <b>Mening ishlarim</b> ({len(items)})"
    await render(event, head, kb.worker_product_list(items, kind))


# --------------------------------------------------------------------------- #
# Ro'yxatlar
# --------------------------------------------------------------------------- #
@router.message(F.text == "📦 Mening ishlarim")
async def my_active(message: Message, session: AsyncSession, user: User, state: FSMContext) -> None:
    await state.clear()
    if not user.stage:
        await message.answer("Sizga hali bosqich biriktirilmagan. Rahbarga murojaat qiling.")
        return
    await _render_list(message, session, user, "active")


@router.message(F.text == "🔴 Qaytarilganlar")
async def my_returned(message: Message, session: AsyncSession, user: User, state: FSMContext) -> None:
    await state.clear()
    if not user.stage:
        await message.answer("Sizga hali bosqich biriktirilmagan.")
        return
    await _render_list(message, session, user, "returned")


@router.message(F.text == "✅ Tugatganlarim")
async def my_done(message: Message, session: AsyncSession, user: User) -> None:
    items = await products_svc.worker_done(session, user)
    lines = [f"• <b>{p.code}</b> — {texts.e(p.name)}" for p in items] or ["— hali yo'q —"]
    await message.answer("✅ <b>Tugatganlarim</b>\n" + "\n".join(lines))


@router.callback_query(F.data.startswith("w:list:"))
async def back_to_list(cb: CallbackQuery, session: AsyncSession, user: User, state: FSMContext) -> None:
    await state.clear()
    if not user.stage:
        await cb.answer("Sizga bosqich biriktirilmagan.", show_alert=True)
        return
    await _render_list(cb, session, user, cb.data.split(":")[2])
    await cb.answer()


# --------------------------------------------------------------------------- #
# Mahsulot kartasi
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("w:open:"))
async def open_product(cb: CallbackQuery, session: AsyncSession, user: User, state: FSMContext) -> None:
    await state.clear()
    product = await products_svc.get_by_id(session, int(cb.data.split(":")[2]))
    if product is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    if not user.stage or product.current_stage_order != user.stage.order_no:
        await cb.answer("Bu mahsulot sizning bosqichingizda emas.", show_alert=True)
        return
    run = await workflow.active_run(session, product)
    if run is None:
        await cb.answer("Faol bosqich topilmadi.", show_alert=True)
        return
    kind = "returned" if product.status.value == "returned" else "active"
    await _render_card(cb, session, run, kind)
    await cb.answer()


# --------------------------------------------------------------------------- #
# Media yig'ish
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("w:media:"))
async def start_media(cb: CallbackQuery, session: AsyncSession, user: User, state: FSMContext) -> None:
    run = await _load_run(cb, session, user, int(cb.data.split(":")[2]))
    if run is None:
        return
    await state.set_state(WorkerFlow.collecting_media)
    await state.update_data(run_id=run.id, status_msg=None)
    await cb.message.answer(
        "📸 Rasm va videolarni yuboravering (bir nechtasini birdan ham bo'ladi).\n"
        "Tugatgach «✅ Tayyor» ni bosing.",
        reply_markup=kb.worker_collecting(run),
    )
    await cb.answer()


async def _bump_status(message: Message, state: FSMContext, run: StageRun) -> None:
    data = await state.get_data()
    n = len(run.media)
    txt = f"📥 Qabul qilindi: {n} ta media"
    mid = data.get("status_msg")
    if mid:
        try:
            await message.bot.edit_message_text(txt, chat_id=message.chat.id, message_id=mid)
            return
        except TelegramBadRequest:
            pass
    sent = await message.answer(txt)
    await state.update_data(status_msg=sent.message_id)


@router.message(WorkerFlow.collecting_media, F.photo)
async def collect_photo(message: Message, session: AsyncSession, user: User, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    run = await workflow.get_run(session, int(data["run_id"]))
    if run is None or run.status != StageRunStatus.in_progress:
        await state.clear()
        await message.answer("Bosqich yopilgan.")
        return
    file_id = message.photo[-1].file_id
    rel = await save_from_telegram(
        bot, file_id, product_code=run.product.code, stage_order=run.stage_order, ext="jpg"
    )
    await workflow.add_media(
        session, run, media_type=MediaType.photo, file_path=rel,
        telegram_file_id=file_id, uploader=user,
    )
    await session.flush()
    await _bump_status(message, state, run)


@router.message(WorkerFlow.collecting_media, F.video)
async def collect_video(message: Message, session: AsyncSession, user: User, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    run = await workflow.get_run(session, int(data["run_id"]))
    if run is None or run.status != StageRunStatus.in_progress:
        await state.clear()
        await message.answer("Bosqich yopilgan.")
        return
    file_id = message.video.file_id
    ext = "mp4"
    if message.video.file_name and "." in message.video.file_name:
        ext = message.video.file_name.rsplit(".", 1)[-1][:5]
    rel = await save_from_telegram(
        bot, file_id, product_code=run.product.code, stage_order=run.stage_order, ext=ext
    )
    await workflow.add_media(
        session, run, media_type=MediaType.video, file_path=rel,
        telegram_file_id=file_id, uploader=user,
    )
    await session.flush()
    await _bump_status(message, state, run)


@router.message(WorkerFlow.collecting_media)
async def collect_other(message: Message) -> None:
    await message.answer(
        "📸 Faqat rasm yoki video yuboring. Tugatgach «✅ Tayyor» ni bosing."
    )


@router.callback_query(F.data.startswith("w:mediadone:"))
async def finish_media(cb: CallbackQuery, session: AsyncSession, user: User, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    run = await workflow.get_run(session, int(cb.data.split(":")[2]))
    if run is not None:
        await _render_card(cb, session, run)
    await cb.answer(f"Media qo'shildi: {len(run.media) if run else 0} ta")


# --------------------------------------------------------------------------- #
# Izoh
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("w:comment:"))
async def start_comment(cb: CallbackQuery, session: AsyncSession, user: User, state: FSMContext) -> None:
    run = await _load_run(cb, session, user, int(cb.data.split(":")[2]))
    if run is None:
        return
    await state.set_state(WorkerFlow.writing_comment)
    await state.update_data(run_id=run.id)
    await cb.message.answer("📝 Izoh matnini yuboring:")
    await cb.answer()


@router.message(WorkerFlow.writing_comment, ~F.text)
async def comment_not_text(message: Message) -> None:
    await message.answer("Izohni matn ko'rinishida yuboring yoki /cancel bosing.")


@router.message(WorkerFlow.writing_comment, F.text)
async def save_comment(message: Message, session: AsyncSession, user: User, state: FSMContext) -> None:
    data = await state.get_data()
    run = await workflow.get_run(session, int(data["run_id"]))
    await state.clear()
    if run is None or run.status != StageRunStatus.in_progress:
        await message.answer("Bosqich yopilgan.")
        return
    await workflow.set_worker_comment(session, run, message.text, user)
    await session.flush()
    await _render_card(message, session, run)


# --------------------------------------------------------------------------- #
# Sifatga yuborish
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("w:submit:"))
async def submit(cb: CallbackQuery, session: AsyncSession, user: User, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    run = await _load_run(cb, session, user, int(cb.data.split(":")[2]))
    if run is None:
        return
    try:
        await workflow.submit_to_qc(session, run, user)
    except workflow.WorkflowError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    await session.flush()
    total = await stages_svc.active_count(session)
    await send_many(
        bot,
        await users_svc.qc_recipients(session),
        "🔔 <b>Yangi tekshiruv</b>\n"
        f"📦 {run.product.code} — {run.product.name}"
        + (f"  ·  {run.product.line}" if run.product.line else "")
        + f"\nBosqich {run.stage_order}/{total} · {run.stage.name}\n"
        f"👷 {user.full_name}",
        markup=kb.open_button("q", run.id, "Tekshirish"),
    )
    await render(
        cb,
        f"🚀 <b>{run.product.code}</b> — {run.stage_order}-bosqich sifat nazoratiga yuborildi.\n"
        "Natijani kuting — qaror kelganda xabar beramiz.",
        None,
    )
    await cb.answer("Yuborildi ✅")
