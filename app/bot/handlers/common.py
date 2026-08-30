from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import menu_for
from app.bot.notify import send_many
from app.enums import Role
from app.models import User
from app.services import users as users_svc

router = Router()


@router.message(CommandStart())
async def start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    user_created: bool,
    bot: Bot,
) -> None:
    await state.clear()
    if user.role == Role.pending:
        await message.answer(
            "Assalomu alaykum! 👋\n\n"
            "Siz ro'yxatdan o'tdingiz. Endi rahbar sizga rol (ishchi / sifat nazorati) "
            "biriktirishi kerak.\n\n"
            f"Sizning ID: <code>{user.telegram_id}</code>\n"
            "Iltimos, bu ID ni rahbaringizga yuboring.",
            reply_markup=menu_for(user),
        )
        if user_created:
            admins = await users_svc.admin_recipients(session)
            await send_many(
                bot,
                admins,
                "🆕 Yangi xodim ro'yxatdan o'tdi:\n"
                f"👤 {texts.e(user.full_name)}"
                + (f" (@{user.username})" if user.username else "")
                + f"\nID: <code>{user.telegram_id}</code>\n\n"
                "«👥 Xodimlar» bo'limidan rol biriktiring.",
            )
        return

    await message.answer(
        f"Assalomu alaykum, {texts.e(user.full_name)}!\n{texts.whoami(user)}",
        reply_markup=menu_for(user),
    )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"Sizning ID: <code>{message.from_user.id}</code>")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, user: User) -> None:
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=menu_for(user))


@router.message(F.text == "ℹ️ Men kim")
async def whoami(message: Message, user: User) -> None:
    await message.answer(texts.whoami(user), reply_markup=menu_for(user))


_HELP = {
    Role.worker: (
        "👷 <b>Ishchi qo'llanmasi</b>\n\n"
        "1. «📦 Mening ishlarim» — sizning bosqichingizdagi mahsulotlar.\n"
        "2. Mahsulotni oching → «📸 Rasm/Video qo'shish» → bajarilgan ishni suratga oling.\n"
        "3. Kerak bo'lsa «📝 Izoh» qoldiring.\n"
        "4. «🚀 Sifat nazoratiga yuborish» — tekshiruvga jo'natasiz.\n"
        "5. Agar qaytarilsa — «🔴 Qaytarilganlar» dan oching, sababni o'qing, tuzatib qayta yuboring.\n\n"
        "Faqat o'z bosqichingizni ko'rasiz. /cancel — amalni bekor qiladi."
    ),
    Role.qc: (
        "🔍 <b>Sifat nazorati qo'llanmasi</b>\n\n"
        "1. «🔍 Tekshiruv navbati» — tekshirish kutayotgan bosqichlar.\n"
        "2. Mahsulotni oching → rasm/videolarni ko'ring.\n"
        "3. Tekshiruv ro'yxatidagi har punktni bosib belgilang (⬜️ → ✅ → ❌).\n"
        "4. Hammasi ✅ bo'lsa — «✅ TASDIQLASH». Aks holda — «❌ QAYTARISH» va sabab.\n"
        "5. «📜 Mahsulot tarixi» — oldingi bosqichlarni ko'rish.\n\n"
        "/cancel — amalni bekor qiladi."
    ),
    Role.admin: (
        "👑 <b>Rahbar qo'llanmasi</b>\n\n"
        "• «➕ Yangi mahsulot» — nom, liniya, izoh → PR-kod avtomat beriladi.\n"
        "• «👥 Xodimlar» — /start bosgan xodimlarga rol (ishchi + bosqich / sifat) biriktiring.\n"
        "• «🏭 Bosqichlar» — nom, tavsif, tekshiruv ro'yxati (checklist).\n"
        "• «📊 Boshqaruv paneli» / «📈 Hisobot» — tezkor ko'rsatkichlar.\n"
        "• /find PR-000123 — mahsulotni kod bo'yicha topish.\n"
        "• /web — batafsil web-panel havolasi.\n"
    ),
    Role.pending: (
        "Hisobingizga hali rol biriktirilmagan.\n"
        f"ID: <code>%s</code> — bu raqamni rahbaringizga yuboring."
    ),
}


@router.message(Command("help"))
async def cmd_help(message: Message, user: User) -> None:
    txt = _HELP.get(user.role, _HELP[Role.pending])
    if user.role == Role.pending:
        txt = txt % user.telegram_id
    await message.answer(txt, reply_markup=menu_for(user))
