"""Admin — taklif (invite) havolalari.

Oqim: rol → (ishchi bo'lsa) bo'lim → muddat (1 soat / 1 kun / 5 kun) → bir martalik havola.
Eski `invites.py` `Invite(token=...)` yaratardi, modelda esa maydon `code` — shuning uchun ishlamasdi,
menyuda tugmasi ham yo'q edi va muddat 24 soatga qattiq yozilgan edi. Bu fayl docker build paytida
`src/bot/handlers/admin/invites.py` o'rniga qo'yiladi (deploy/bot-fixes/patch_bot.py).
"""
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.filters import IsAdmin
from src.bot.states import CreateInviteFSM
from src.database.models.user import User
from src.services.i18n_service import _, get_role_name, get_step_name
from src.services.invite_service import create_invite
from src.utils.logger import logger


router = Router(name="admin_invites")

# (soat, {til: yozuv})
TTL_OPTIONS = [
    (1, {"uz": "⏱ 1 soat", "uz_cyrl": "⏱ 1 соат", "ru": "⏱ 1 час"}),
    (24, {"uz": "📅 1 kun", "uz_cyrl": "📅 1 кун", "ru": "📅 1 день"}),
    (120, {"uz": "📅 5 kun", "uz_cyrl": "📅 5 кун", "ru": "📅 5 дней"}),
]

TXT = {
    "uz": {
        "share": "📤 Yuborish",
        "open": "✅ Ro'yxatdan o'tish",
        "fwd": "👋 <b>BAAZ Trucks</b>\n\nSizni jamoaga taklif qilamiz.\n\n🎭 <b>{role}</b>{step}\n\nRo'yxatdan o'tish uchun pastdagi tugmani bosing ⬇️\n\n⏰ Havola {ttl} amal qiladi.",
        "share_text": "BAAZ Trucks jamoasiga qo'shiling ({ttl} amal qiladi):",
        "hint": "👇 Pastdagi xabarni odamga <b>yuboring (forward)</b> yoki «📤 Yuborish» tugmasini bosing.",
        "ttl_prompt": "3️⃣ <b>Havola qancha vaqt amal qilsin?</b>\n\n🎭 {role}{step}\n\nMuddat o'tgach havola ishlamaydi. Havola bir martalik.",
        "done": "✅ <b>Taklif yaratildi!</b>\n\n🎭 {role}{step}\n\n🔗 <b>Havola:</b>\n{link}\n\n⏰ Muddat: <b>{ttl}</b>\n☝️ Bir martalik: bitta odam foydalana oladi.\n\n{hint}",
        "cancel": "❌ Bekor qilish",
    },
    "uz_cyrl": {
        "share": "📤 Юбориш",
        "open": "✅ Рўйхатдан ўтиш",
        "fwd": "👋 <b>BAAZ Trucks</b>\n\nСизни жамоага таклиф қиламиз.\n\n🎭 <b>{role}</b>{step}\n\nРўйхатдан ўтиш учун пастдаги тугмани босинг ⬇️\n\n⏰ Ҳавола {ttl} амал қилади.",
        "share_text": "BAAZ Trucks жамоасига қўшилинг ({ttl} амал қилади):",
        "hint": "👇 Пастдаги хабарни одамга <b>юборинг (forward)</b> ёки «📤 Юбориш» тугмасини босинг.",
        "ttl_prompt": "3️⃣ <b>Ҳавола қанча вақт амал қилсин?</b>\n\n🎭 {role}{step}\n\nМуддат ўтгач ҳавола ишламайди. Ҳавола бир марталик.",
        "done": "✅ <b>Таклиф яратилди!</b>\n\n🎭 {role}{step}\n\n🔗 <b>Ҳавола:</b>\n{link}\n\n⏰ Муддат: <b>{ttl}</b>\n☝️ Бир мартали: битта одам фойдалана олади.\n\n{hint}",
        "cancel": "❌ Бекор қилиш",
    },
    "ru": {
        "share": "📤 Отправить",
        "open": "✅ Зарегистрироваться",
        "fwd": "👋 <b>BAAZ Trucks</b>\n\nПриглашаем вас в команду.\n\n🎭 <b>{role}</b>{step}\n\nДля регистрации нажмите кнопку ниже ⬇️\n\n⏰ Ссылка действует {ttl}.",
        "share_text": "Присоединяйтесь к команде BAAZ Trucks (действует {ttl}):",
        "hint": "👇 <b>Перешлите</b> сообщение ниже человеку или нажмите «📤 Отправить».",
        "ttl_prompt": "3️⃣ <b>Сколько времени ссылка будет действовать?</b>\n\n🎭 {role}{step}\n\nПосле истечения срока ссылка не работает. Ссылка одноразовая.",
        "done": "✅ <b>Приглашение создано!</b>\n\n🎭 {role}{step}\n\n🔗 <b>Ссылка:</b>\n{link}\n\n⏰ Срок: <b>{ttl}</b>\n☝️ Одноразовая: ей сможет воспользоваться один человек.\n\n{hint}",
        "cancel": "❌ Отмена",
    },
}


def _lang(user: User) -> str:
    return user.language if user.language in TXT else "uz"


def _cancel_btn(builder: InlineKeyboardBuilder, lang: str) -> None:
    builder.button(text=TXT[lang]["cancel"], callback_data="invite_cancel")


def _role_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for role in ("worker", "qc", "admin"):
        b.button(text=get_role_name(role, lang), callback_data=f"invite_role:{role}")
    _cancel_btn(b, lang)
    b.adjust(1)
    return b.as_markup()


def _step_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in range(1, 7):
        b.button(text=f"{n}️⃣ {get_step_name(n, lang)}", callback_data=f"invite_step:{n}")
    _cancel_btn(b, lang)
    b.adjust(1)
    return b.as_markup()


def _ttl_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for hours, labels in TTL_OPTIONS:
        b.button(text=labels[lang], callback_data=f"invite_ttl:{hours}")
    _cancel_btn(b, lang)
    b.adjust(3, 1)
    return b.as_markup()


async def _begin(target: Message | CallbackQuery, state: FSMContext, user: User) -> None:
    lang = _lang(user)
    await state.clear()
    await state.set_state(CreateInviteFSM.role)
    text = _("admin.invite_step1", language=lang)
    if isinstance(target, CallbackQuery):
        await target.answer()
        await target.message.edit_text(text, reply_markup=_role_kb(lang))
    else:
        await target.answer(text, reply_markup=_role_kb(lang))


# ==================== Boshlash: foydalanuvchilar ro'yxatidagi tugma yoki eski matn tugmasi ====================
@router.callback_query(IsAdmin(), F.data == "invite_start")
async def start_invite_cb(callback: CallbackQuery, state: FSMContext, user: User):
    await _begin(callback, state, user)


@router.message(IsAdmin(), F.text == "➕ Taklif yaratish")
async def start_invite(message: Message, state: FSMContext, user: User):
    await _begin(message, state, user)


# ==================== Rol ====================
@router.callback_query(CreateInviteFSM.role, F.data.startswith("invite_role:"))
async def choose_role(callback: CallbackQuery, state: FSMContext, user: User):
    lang = _lang(user)
    role = callback.data.split(":")[1]
    await callback.answer()
    await state.update_data(role=role, step_number=None)

    if role == "worker":
        await state.set_state(CreateInviteFSM.step_number)
        await callback.message.edit_text(
            _("admin.invite_step2_worker", language=lang), reply_markup=_step_kb(lang)
        )
        return
    await _ask_ttl(callback, state, lang)


# ==================== Bo'lim (faqat ishchi) ====================
@router.callback_query(CreateInviteFSM.step_number, F.data.startswith("invite_step:"))
async def choose_step(callback: CallbackQuery, state: FSMContext, user: User):
    await callback.answer()
    await state.update_data(step_number=int(callback.data.split(":")[1]))
    await _ask_ttl(callback, state, _lang(user))


async def _ask_ttl(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    data = await state.get_data()
    await state.set_state(CreateInviteFSM.expires_in)
    step = f"\n🔧 {get_step_name(data['step_number'], lang)}" if data.get("step_number") else ""
    await callback.message.edit_text(
        TXT[lang]["ttl_prompt"].format(role=get_role_name(data["role"], lang), step=step),
        reply_markup=_ttl_kb(lang),
    )


# ==================== Muddat -> havola ====================
@router.callback_query(CreateInviteFSM.expires_in, F.data.startswith("invite_ttl:"))
async def choose_ttl(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User, bot: Bot
):
    lang = _lang(user)
    hours = int(callback.data.split(":")[1])
    if hours not in {h for h, _l in TTL_OPTIONS}:
        await callback.answer("❌", show_alert=True)
        return
    data = await state.get_data()
    role, step_number = data["role"], data.get("step_number")

    invite = await create_invite(
        session, role=role, step_number=step_number,
        created_by=user.telegram_id, expires_in_hours=hours,
    )
    await state.clear()
    await callback.answer("✅")

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={invite.code}"
    ttl_label = next(lbl[lang] for h, lbl in TTL_OPTIONS if h == hours).split(" ", 1)[1]
    step = f"\n🔧 {get_step_name(step_number, lang)}" if step_number else ""
    logger.info(
        f"➕ Taklif yaratildi: role={role}, step={step_number}, muddat={hours}s, "
        f"code={invite.code}, kim={user.telegram_id}"
    )
    t = TXT[lang]
    role_name = get_role_name(role, lang)
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(t['share_text'].format(ttl=ttl_label))}"
    share_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t["share"], url=share_url)]])
    await callback.message.edit_text(
        t["done"].format(role=role_name, step=step, link=link, ttl=ttl_label, hint=t["hint"]),
        reply_markup=share_kb,
        disable_web_page_preview=True,
    )
    # Oldinga yuborishga tayyor xabar: ichida bosiladigan tugma bor (forward qilinganda ham saqlanadi).
    await callback.message.answer(
        t["fwd"].format(role=role_name, step=step, ttl=ttl_label),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=t["open"], url=link)]]
        ),
    )


# ==================== Bekor qilish ====================
@router.callback_query(F.data == "invite_cancel")
async def cancel_invite(callback: CallbackQuery, state: FSMContext, user: User):
    lang = _lang(user)
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(TXT[lang]["cancel"])
