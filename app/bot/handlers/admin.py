from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot import texts
from app.bot.filters import RoleFilter
from app.bot.notify import send_one
from app.bot.states import AdminFlow
from app.config import settings
from app.enums import PRODUCT_STATUS_LABEL, ROLE_LABEL, ProductStatus, Role
from app.foodtruck import SIZES
from app.models import TruckModel, User
from app.services import products as products_svc
from app.services import stages as stages_svc
from app.services import stats as stats_svc
from app.services import users as users_svc
from app.services import workflow

router = Router()
router.message.filter(RoleFilter(Role.admin))
router.callback_query.filter(RoleFilter(Role.admin))


def _web_url() -> str:
    host = "localhost" if settings.web_host in ("0.0.0.0", "") else settings.web_host
    return f"http://{host}:{settings.web_port}"


# --------------------------------------------------------------------------- #
# Boshqaruv paneli
# --------------------------------------------------------------------------- #
async def _dashboard_text(session: AsyncSession) -> str:
    ov = await stats_svc.overview(session)
    rows = await stats_svc.per_stage(session)
    lines = [
        "📊 <b>BOSHQARUV PANELI</b>",
        f"Jami mahsulot: {ov['total']}",
        f"🟢 Tayyor: {ov['by_status'][ProductStatus.done]}",
        f"🔵 Ishlab chiqarishda: {ov['by_status'][ProductStatus.in_production]}",
        f"🟡 Sifat nazoratida: {ov['by_status'][ProductStatus.qc_pending]}",
        f"🔴 Qaytarilgan: {ov['by_status'][ProductStatus.returned]}",
        f"\nBugun: +{ov['created_today']} yangi · {ov['finished_today']} tayyor",
        "\n<b>Bosqichlar bo'yicha:</b>",
    ]
    for r in rows:
        lines.append(
            f"{r['order_no']}. {texts.e(r['name'])} — "
            f"jami {r['total']} (🔵{r['in_production']} 🟡{r['qc_pending']} 🔴{r['returned']})"
        )
    lines.append(f"\n🌐 Batafsil web-panel: {_web_url()}")
    return "\n".join(lines)


@router.message(F.text == "📊 Boshqaruv paneli")
async def dashboard(message: Message, session: AsyncSession) -> None:
    await message.answer(await _dashboard_text(session))


@router.callback_query(F.data == "a:dash")
async def dashboard_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    await cb.message.answer(await _dashboard_text(session))
    await cb.answer()


# --------------------------------------------------------------------------- #
# Trucklar
# --------------------------------------------------------------------------- #
@router.message(F.text.in_(["🚚 Trucklar", "📦 Mahsulotlar"]))
async def products_list(message: Message, session: AsyncSession) -> None:
    items = await products_svc.list_products(session, limit=30)
    await message.answer(
        f"🚚 <b>So'nggi trucklar</b> ({len(items)})",
        reply_markup=kb.admin_product_list(items),
    )


@router.callback_query(F.data == "a:products")
async def products_list_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    items = await products_svc.list_products(session, limit=30)
    await cb.message.answer(
        f"🚚 <b>So'nggi trucklar</b> ({len(items)})",
        reply_markup=kb.admin_product_list(items),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("a:prod:"))
async def product_detail(cb: CallbackQuery, session: AsyncSession) -> None:
    product = await products_svc.get_by_id(session, int(cb.data.split(":")[2]))
    if product is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    runs = await products_svc.timeline(session, product)
    total = await stages_svc.active_count(session)
    await cb.message.answer(
        texts.product_timeline(product, runs, total),
        reply_markup=kb.admin_product_open(product),
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
# Yangi truck: model -> o'lcham -> rang -> izoh
# --------------------------------------------------------------------------- #
@router.message(F.text.in_(["➕ Yangi truck", "➕ Yangi mahsulot"]))
async def new_product(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    models = await stages_svc.list_models(session)
    await message.answer(
        "🚚 <b>Yangi truck</b>\nModelni tanlang:",
        reply_markup=kb.admin_pick_model(models),
    )


@router.callback_query(F.data.startswith("a:npmodel:"))
async def np_model(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    val = cb.data.split(":")[2]
    if val == "new":
        await state.set_state(AdminFlow.model_add)
        await state.update_data(_np=True)
        await cb.message.answer("Yangi model nomini yuboring (masalan T6):")
        await cb.answer()
        return
    m = await session.get(TruckModel, int(val))
    if m is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    await state.set_state(None)
    await state.update_data(model=m.name)
    await cb.message.answer(
        f"Model: <b>{texts.e(m.name)}</b>\nO'lchamni tanlang:",
        reply_markup=kb.admin_pick_size(SIZES),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("a:npsize:"))
async def np_size(cb: CallbackQuery, state: FSMContext) -> None:
    size = int(cb.data.split(":")[2])
    await state.update_data(size=size)
    await state.set_state(AdminFlow.product_color)
    await cb.message.answer(f"O'lcham: <b>{size} m</b>\nRangni yozing (masalan «Oq», «Qizil»):")
    await cb.answer()


@router.message(AdminFlow.product_color, F.text)
async def np_color(message: Message, state: FSMContext) -> None:
    await state.update_data(color=message.text.strip())
    await state.set_state(AdminFlow.product_note)
    await message.answer("Izoh yuboring (yoki «-» qo'ying):")


@router.message(AdminFlow.product_note, F.text)
async def np_note(
    message: Message, state: FSMContext, session: AsyncSession, user: User, bot: Bot
) -> None:
    data = await state.get_data()
    await state.clear()
    note = None if message.text.strip() in ("-", "—", "") else message.text.strip()
    try:
        product = await workflow.create_product(
            session, creator=user, note=note,
            model=data.get("model"), size_m=data.get("size"), color=data.get("color"),
        )
    except workflow.WorkflowError as exc:
        await message.answer(str(exc))
        return
    await session.flush()
    workers = await users_svc.workers_at_stage(session, 1)
    await message.answer(
        f"✅ Yaratildi: <b>{texts.truck_name(product)}</b>\n"
        f"🚚 {texts.e(product.model or '—')} · {product.size_m or '—'} m · {texts.e(product.color or '—')}\n"
        f"1-liniya ({texts.e((await stages_svc.get_by_order(session, 1)).name)}) ishchilariga xabar berildi ({len(workers)} ta)."
    )
    for w in workers:
        await send_one(
            bot, w,
            f"🔔 <b>Yangi truck</b>\nModel {product.model or "—"} · {product.size_m or "—"} m · {product.color or "—"}\n"
            "1-liniyadan boshlanadi.",
            markup=kb.open_button("w", product.id, "Ochish"),
        )


# --------------------------------------------------------------------------- #
# Modellar
# --------------------------------------------------------------------------- #
@router.message(F.text == "🚚 Modellar")
async def models_list(message: Message, session: AsyncSession) -> None:
    models = await stages_svc.list_models(session)
    lines = [f"🚚 <b>Modellar</b> ({len(models)})"] + [f"• {texts.e(m.name)}" for m in models]
    await message.answer("\n".join(lines), reply_markup=kb.admin_models_list(models))


@router.callback_query(F.data == "a:models")
async def models_list_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    models = await stages_svc.list_models(session)
    await cb.message.answer("🚚 <b>Modellar</b>", reply_markup=kb.admin_models_list(models))
    await cb.answer()


@router.callback_query(F.data == "a:modeladd")
async def model_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.model_add)
    await cb.message.answer("Yangi model nomini yuboring (masalan T6):")
    await cb.answer()


@router.message(AdminFlow.model_add, F.text)
async def model_add_do(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    is_np = bool(data.get("_np"))
    await state.clear()
    m = await stages_svc.add_model(session, message.text)
    await session.flush()
    if m is None:
        await message.answer("Nom bo'sh. Qaytadan urinib ko'ring.")
        return
    await message.answer(f"✅ Model qo'shildi: <b>{texts.e(m.name)}</b>")
    if is_np:
        await state.update_data(model=m.name)  # state=None, keyingi qadam a:npsize:
        await message.answer(
            f"Model: <b>{texts.e(m.name)}</b>\nO'lchamni tanlang:",
            reply_markup=kb.admin_pick_size(SIZES),
        )
    else:
        models = await stages_svc.list_models(session)
        await message.answer("🚚 <b>Modellar</b>", reply_markup=kb.admin_models_list(models))


@router.callback_query(F.data.startswith("a:modeldel:"))
async def model_del(cb: CallbackQuery, session: AsyncSession) -> None:
    await stages_svc.deactivate_model(session, int(cb.data.split(":")[2]))
    await session.flush()
    models = await stages_svc.list_models(session)
    await cb.message.answer("🚚 <b>Modellar</b>", reply_markup=kb.admin_models_list(models))
    await cb.answer("O'chirildi")


# --------------------------------------------------------------------------- #
# Xodimlar
# --------------------------------------------------------------------------- #
@router.message(F.text == "👥 Xodimlar")
async def users_list(message: Message, session: AsyncSession) -> None:
    items = await users_svc.all_users(session)
    pending = [u for u in items if u.role == Role.pending]
    head = f"👥 <b>Xodimlar</b> ({len(items)})"
    if pending:
        head += f"\n⏳ Tayinlanmagan: {len(pending)}"
    await message.answer(head, reply_markup=kb.admin_users_list(items))


@router.callback_query(F.data == "a:users")
async def users_list_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    items = await users_svc.all_users(session)
    await cb.message.answer("👥 <b>Xodimlar</b>", reply_markup=kb.admin_users_list(items))
    await cb.answer()


async def _user_card_text(target: User) -> str:
    lines = [
        f"👤 <b>{texts.e(target.full_name)}</b>",
        f"Rol: {ROLE_LABEL[target.role]}",
        f"ID: <code>{target.telegram_id}</code>",
        f"Holat: {'faol' if target.is_active else 'oʻchirilgan'}",
    ]
    if target.stage:
        lines.append(f"Bosqich: {target.stage.order_no}. {texts.e(target.stage.name)}")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("a:user:"))
async def user_card(cb: CallbackQuery, session: AsyncSession) -> None:
    target = await session.get(User, int(cb.data.split(":")[2]))
    if target is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    await cb.message.answer(await _user_card_text(target), reply_markup=kb.admin_user_card(target))
    await cb.answer()


@router.callback_query(F.data.startswith("a:setrole:"))
async def set_role(cb: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    _, _, uid, role_name = cb.data.split(":")
    target = await session.get(User, int(uid))
    if target is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    role = Role(role_name)
    if role == Role.worker:
        stages = await stages_svc.list_stages(session)
        await state.set_state(AdminFlow.assign_stage)
        await state.update_data(user_id=target.id)
        await cb.message.answer(
            f"{texts.e(target.full_name)} — qaysi bosqichga?",
            reply_markup=kb.admin_pick_stage(target.id, stages),
        )
        await cb.answer()
        return
    await users_svc.assign(session, target, role)
    await session.flush()
    await send_one(bot, target, f"✅ Sizga rol biriktirildi: {ROLE_LABEL[role]}. /start bosing.")
    await cb.message.answer(await _user_card_text(target), reply_markup=kb.admin_user_card(target))
    await cb.answer("Saqlandi")


@router.callback_query(F.data.startswith("a:setstage:"))
async def set_stage(cb: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    _, _, uid, order = cb.data.split(":")
    await state.clear()
    target = await session.get(User, int(uid))
    stage = await stages_svc.get_by_order(session, int(order))
    if target is None or stage is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    await users_svc.assign(session, target, Role.worker, stage.id)
    await session.flush()
    await send_one(
        bot, target,
        f"✅ Sizga rol biriktirildi: 👷 Ishchi · {stage.order_no}-bosqich ({stage.name}). /start bosing.",
    )
    await cb.message.answer(await _user_card_text(target), reply_markup=kb.admin_user_card(target))
    await cb.answer("Saqlandi")


@router.callback_query(F.data.startswith("a:toggleuser:"))
async def toggle_user(cb: CallbackQuery, session: AsyncSession) -> None:
    target = await session.get(User, int(cb.data.split(":")[2]))
    if target is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    await users_svc.set_active(session, target, not target.is_active)
    await session.flush()
    await cb.message.answer(await _user_card_text(target), reply_markup=kb.admin_user_card(target))
    await cb.answer("O'zgartirildi")


# --------------------------------------------------------------------------- #
# Bosqichlar
# --------------------------------------------------------------------------- #
@router.message(F.text.in_(["🏭 Liniyalar", "🏭 Bosqichlar"]))
async def stages_list(message: Message, session: AsyncSession) -> None:
    items = await stages_svc.list_stages(session)
    await message.answer(
        f"🏭 <b>Ishlab chiqarish liniyalari</b> ({len(items)})",
        reply_markup=kb.admin_stages_list(items),
    )


@router.callback_query(F.data == "a:stages")
async def stages_list_cb(cb: CallbackQuery, session: AsyncSession) -> None:
    items = await stages_svc.list_stages(session)
    await cb.message.answer("🏭 <b>Bosqichlar</b>", reply_markup=kb.admin_stages_list(items))
    await cb.answer()


@router.callback_query(F.data.startswith("a:stage:"))
async def stage_card(cb: CallbackQuery, session: AsyncSession) -> None:
    from app.models import Stage

    stage = await session.get(Stage, int(cb.data.split(":")[2]))
    if stage is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    text = (
        f"🏭 <b>{stage.order_no}. {texts.e(stage.name)}</b>\n"
        f"Tavsif: {texts.e(stage.description) or '—'}"
    )
    await cb.message.answer(text, reply_markup=kb.admin_stage_card(stage))
    await cb.answer()


@router.callback_query(F.data == "a:stageadd")
async def stage_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.stage_name)
    await cb.message.answer("Yangi bosqich nomini yuboring:")
    await cb.answer()


@router.message(AdminFlow.stage_name, F.text)
async def stage_add_name(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    stage = await stages_svc.add_stage(session, message.text)
    await session.flush()
    await message.answer(f"✅ Qo'shildi: {stage.order_no}. {texts.e(stage.name)}")


@router.callback_query(F.data.startswith("a:stagerename:"))
async def stage_rename(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.stage_rename)
    await state.update_data(stage_id=int(cb.data.split(":")[2]))
    await cb.message.answer("Yangi nomni yuboring:")
    await cb.answer()


@router.message(AdminFlow.stage_rename, F.text)
async def stage_rename_do(message: Message, session: AsyncSession, state: FSMContext) -> None:
    from app.models import Stage

    data = await state.get_data()
    await state.clear()
    stage = await session.get(Stage, int(data["stage_id"]))
    if stage is None:
        await message.answer("Topilmadi.")
        return
    await stages_svc.rename_stage(session, stage, message.text)
    await session.flush()
    await message.answer(f"✅ Yangilandi: {stage.order_no}. {texts.e(stage.name)}")


@router.callback_query(F.data.startswith("a:stagedesc:"))
async def stage_desc(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.stage_desc)
    await state.update_data(stage_id=int(cb.data.split(":")[2]))
    await cb.message.answer("Bosqich tavsifini yuboring:")
    await cb.answer()


@router.message(AdminFlow.stage_desc, F.text)
async def stage_desc_do(message: Message, session: AsyncSession, state: FSMContext) -> None:
    from app.models import Stage

    data = await state.get_data()
    await state.clear()
    stage = await session.get(Stage, int(data["stage_id"]))
    if stage is None:
        await message.answer("Topilmadi.")
        return
    await stages_svc.set_description(session, stage, message.text)
    await session.flush()
    await message.answer("✅ Tavsif saqlandi.")


async def _show_checklist(target: Message, session: AsyncSession, stage_id: int) -> None:
    from app.models import Stage

    stage = await session.get(Stage, stage_id)
    if stage is None:
        await target.answer("Topilmadi.")
        return
    items = await stages_svc.list_check_items(session, stage_id)
    lines = [f"📋 <b>{stage.order_no}. {texts.e(stage.name)}</b> — tekshiruv ro'yxati ({len(items)})"]
    for it in items:
        lines.append(f"{it.order_no}. {texts.e(it.text)}")
    if not items:
        lines.append("<i>hozircha punkt yo'q</i>")
    lines.append("\n🗑 tugma — punktni o'chirish")
    await target.answer("\n".join(lines), reply_markup=kb.admin_checklist(stage, items))


@router.callback_query(F.data.startswith("a:chklist:"))
async def checklist_show(cb: CallbackQuery, session: AsyncSession) -> None:
    await _show_checklist(cb.message, session, int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("a:chkadd:"))
async def checklist_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.check_add)
    await state.update_data(stage_id=int(cb.data.split(":")[2]))
    await cb.message.answer(
        "Yangi punkt(lar)ni yuboring. Har bir qatorda bittadan:\n\n"
        "<i>Payvand choklari yorilishsiz\nRama diagonallari teng</i>"
    )
    await cb.answer()


@router.message(AdminFlow.check_add, F.text)
async def checklist_add_do(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    stage_id = int(data["stage_id"])
    n = await stages_svc.add_check_items(session, stage_id, message.text)
    await session.flush()
    await message.answer(f"✅ {n} ta punkt qo'shildi.")
    await _show_checklist(message, session, stage_id)


@router.callback_query(F.data.startswith("a:chkdel:"))
async def checklist_del(cb: CallbackQuery, session: AsyncSession) -> None:
    from app.models import StageCheckItem

    item = await session.get(StageCheckItem, int(cb.data.split(":")[2]))
    if item is None:
        await cb.answer("Topilmadi.", show_alert=True)
        return
    stage_id = item.stage_id
    await stages_svc.deactivate_check_item(session, item.id)
    await session.flush()
    await _show_checklist(cb.message, session, stage_id)
    await cb.answer("O'chirildi")


# --------------------------------------------------------------------------- #
# Hisobot
# --------------------------------------------------------------------------- #
@router.message(F.text == "📈 Hisobot")
async def report(message: Message, session: AsyncSession) -> None:
    prod = await stats_svc.worker_productivity(session)
    defects = await stats_svc.defects(session, limit=15)

    lines = ["📈 <b>HISOBOT</b>", "", "<b>Ishchilar samaradorligi:</b>"]
    if prod:
        for p in prod:
            lines.append(
                f"• {texts.e(p['name'])} ({texts.e(p['stage'])}) — "
                f"✅ {p['approved']} · 🔴 {p['returned']}"
            )
    else:
        lines.append("— maʼlumot yo'q —")

    lines += ["", "<b>So'nggi kamchiliklar:</b>"]
    if defects:
        for d in defects:
            lines.append(
                f"• {texts.truck_name(d.product)} · {d.stage_order}-bosqich · {texts.fmt_dt(d.decided_at)}"
                f"\n    💬 {texts.e(d.qc_comment)}"
            )
    else:
        lines.append("— yo'q —")

    await message.answer("\n".join(lines))


@router.message(Command("web"))
async def web_link(message: Message) -> None:
    await message.answer(f"🌐 Rahbar web-panel: {_web_url()}\nParol: .env dagi WEB_PASSWORD")


@router.message(Command("find"))
async def find_product(message: Message, session: AsyncSession, command: CommandObject) -> None:
    code = (command.args or "").strip().upper()
    if not code:
        await message.answer("Foydalanish: <code>/find PR-000123</code>")
        return
    if code.isdigit():
        code = f"PR-{int(code):06d}"
    product = await products_svc.get_by_code(session, code)
    if product is None:
        await message.answer(f"«{texts.e(code)}» topilmadi.")
        return
    runs = await products_svc.timeline(session, product)
    total = await stages_svc.active_count(session)
    await message.answer(
        texts.product_timeline(product, runs, total),
        reply_markup=kb.admin_product_open(product),
    )
