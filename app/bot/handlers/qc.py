from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot import texts
from app.bot.filters import RoleFilter
from app.bot.media_send import send_run_media
from app.bot.notify import send_many, send_one
from app.bot.states import QcFlow
from app.bot.ui import render
from app.enums import Role, StageRunStatus
from app.models import StageRun, User
from app.services import products as products_svc
from app.services import stages as stages_svc
from app.services import users as users_svc
from app.services import workflow

router = Router()
router.message.filter(RoleFilter(Role.qc))
router.callback_query.filter(RoleFilter(Role.qc))


async def _load_pending(cb: CallbackQuery, session: AsyncSession, run_id: int) -> StageRun | None:
    run = await workflow.get_run(session, run_id)
    if run is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return None
    if run.status != StageRunStatus.qc_pending:
        await cb.answer("Bu bosqich allaqachon ko'rib chiqilgan.", show_alert=True)
        return None
    return run


async def _queue_text(session: AsyncSession):
    runs = await products_svc.qc_queue(session)
    return f"🔍 <b>Tekshiruv navbati</b> ({len(runs)})", kb.qc_queue_list(runs)


@router.message(F.text == "🔍 Tekshiruv navbati")
async def queue(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    head, markup = await _queue_text(session)
    await message.answer(head, reply_markup=markup)


@router.callback_query(F.data == "q:queue")
async def queue_cb(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    head, markup = await _queue_text(session)
    await render(cb, head, markup)
    await cb.answer()


@router.message(F.text == "📜 So'nggi qarorlar")
async def recent(message: Message, session: AsyncSession) -> None:
    runs = await products_svc.qc_recent(session, limit=20)
    if not runs:
        await message.answer("Hali qaror yo'q.")
        return
    lines = []
    for r in runs:
        mark = "🟢" if r.status == StageRunStatus.approved else "🔴"
        line = f"{mark} <b>{texts.truck_name(r.product)}</b> · {r.stage_order}-bosqich · {texts.fmt_dt(r.decided_at)}"
        if r.qc_comment:
            line += f"\n    💬 {texts.e(r.qc_comment)}"
        lines.append(line)
    await message.answer("📜 <b>So'nggi qarorlar</b>\n\n" + "\n".join(lines))


async def _decision_kb(session: AsyncSession, run: StageRun):
    state = await workflow.checklist_state(session, run)
    if state:
        return kb.qc_checklist(run, state), state
    return kb.qc_decision(run), []


@router.callback_query(F.data.startswith("q:open:"))
async def open_run(cb: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    run = await _load_pending(cb, session, int(cb.data.split(":")[2]))
    if run is None:
        return
    total = await stages_svc.active_count(session)
    await cb.message.answer(texts.qc_card(run, total))
    await send_run_media(bot, cb.message.chat.id, run)
    markup, state = await _decision_kb(session, run)
    prompt = (
        "📋 Har bir punktni bosib belgilang (⬜️ → ✅ → ❌), so'ng qaror qabul qiling:"
        if state
        else "Qaror qabul qiling:"
    )
    await cb.message.answer(prompt, reply_markup=markup)
    await cb.answer()


@router.callback_query(F.data.startswith("q:hist:"))
async def history(cb: CallbackQuery, session: AsyncSession) -> None:
    run = await workflow.get_run(session, int(cb.data.split(":")[2]))
    if run is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    product = await products_svc.get_by_code(session, run.product.code)
    runs = await products_svc.timeline(session, product)
    total = await stages_svc.active_count(session)
    await cb.message.answer(texts.product_timeline(product, runs, total))
    await cb.answer()


@router.callback_query(F.data.startswith("q:chk:"))
async def toggle_check(cb: CallbackQuery, session: AsyncSession, user: User) -> None:
    _, _, run_id, item_id = cb.data.split(":")
    run = await _load_pending(cb, session, int(run_id))
    if run is None:
        return
    cur = next((c.ok for c in run.checks if c.check_item_id == int(item_id)), None)
    nxt = {None: "ok", True: "fail", False: "none"}[cur]
    await workflow.set_check(session, run, int(item_id), nxt, user)
    await session.flush()
    state = await workflow.checklist_state(session, run)
    try:
        await cb.message.edit_reply_markup(reply_markup=kb.qc_checklist(run, state))
    except TelegramBadRequest:
        pass
    s = await workflow.checklist_summary(session, run)
    await cb.answer(f"✅ {s['passed']}   ❌ {len(s['failed'])}   ⬜️ {s['pending']}")


@router.callback_query(F.data.startswith("q:approve:"))
async def approve(cb: CallbackQuery, session: AsyncSession, user: User, bot: Bot) -> None:
    run = await _load_pending(cb, session, int(cb.data.split(":")[2]))
    if run is None:
        return
    try:
        result = await workflow.qc_approve(session, run, user)
    except workflow.WorkflowError as exc:
        await cb.answer(str(exc), show_alert=True)
        return
    await session.flush()
    product = result.product

    if result.finished:
        await send_many(
            bot,
            await users_svc.admin_recipients(session),
            f"🟢 <b>{texts.truck_name(product)}</b> barcha bosqichlardan o'tdi.\n<b>MAHSULOT TAYYOR.</b>",
        )
        await render(cb, f"✅ <b>{texts.truck_name(product)}</b> · {run.stage_order}-bosqich tasdiqlandi.\n🟢 Mahsulot TAYYOR.", None)
    else:
        nxt = result.next_stage_order
        await send_many(
            bot,
            await users_svc.workers_at_stage(session, nxt),
            f"🔔 <b>Yangi ish</b>\n📦 {texts.truck_name(product)}"
            + (f"  ·  {product.line}" if product.line else "")
            + f"\n{nxt}-bosqich sizga keldi.",
            markup=kb.open_button("w", product.id, "Ochish"),
        )
        await render(cb, f"✅ <b>{texts.truck_name(product)}</b> · {run.stage_order}-bosqich tasdiqlandi → {nxt}-bosqichga o'tkazildi.", None)
    await cb.answer("Tasdiqlandi ✅")


@router.callback_query(F.data.startswith("q:return:"))
async def ask_reason(cb: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    run = await _load_pending(cb, session, int(cb.data.split(":")[2]))
    if run is None:
        return
    summary = await workflow.checklist_summary(session, run)
    auto = "; ".join(summary["failed"])
    await state.set_state(QcFlow.return_reason)
    await state.update_data(run_id=run.id, auto=auto, dec_msg=cb.message.message_id)
    if auto:
        await cb.message.answer(
            "❌ <b>Yiqilgan punktlar:</b>\n• " + "\n• ".join(summary["failed"])
            + "\n\nQo'shimcha izoh yozing yoki shu punktlarni sabab qilish uchun «-» yuboring:"
        )
    else:
        await cb.message.answer("❌ Qaytarish sababini yozing:")
    await cb.answer()


@router.message(QcFlow.return_reason, ~F.text)
async def reason_not_text(message: Message) -> None:
    await message.answer("Sababni matn ko'rinishida yuboring yoki /cancel bosing.")


@router.message(QcFlow.return_reason, F.text)
async def do_return(message: Message, session: AsyncSession, user: User, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    run = await workflow.get_run(session, int(data["run_id"]))
    if run is None or run.status != StageRunStatus.qc_pending:
        await message.answer("Bu bosqich allaqachon ko'rib chiqilgan.")
        return
    auto = (data.get("auto") or "").strip()
    text = message.text.strip()
    if text == "-" and auto:
        reason = f"Tekshiruv punktlari yiqildi: {auto}"
    elif auto and text != "-":
        reason = f"{text}\n(Yiqilgan punktlar: {auto})"
    else:
        reason = text

    code = run.product.code
    order = run.stage_order
    try:
        retry = await workflow.qc_return(session, run, user, reason)
    except workflow.WorkflowError as exc:
        await message.answer(str(exc))
        return
    await session.flush()

    await send_one(
        bot,
        run.worker,
        f"🔴 <b>{code}</b> — {order}-bosqich QAYTARILDI.\n"
        f"Sabab: {reason}\n\n"
        "Tuzatib, qayta yuboring:",
        markup=kb.open_button("w", run.product_id, "Ochish"),
    )
    if data.get("dec_msg"):
        try:
            await bot.edit_message_text(
                f"🔴 <b>{code}</b> · {order}-bosqich qaytarildi (urinish #{retry.attempt_no}).",
                chat_id=message.chat.id, message_id=data["dec_msg"],
            )
        except TelegramBadRequest:
            pass
    await message.answer(f"🔴 {code} ishchiga qaytarildi.")
