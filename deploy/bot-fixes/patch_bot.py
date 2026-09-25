"""Bot manba kodiga docker build paytida qo'llanadigan kichik tuzatishlar.

Bot repo'sida shular to'g'rilangach, skript o'zi "allaqachon tuzatilgan" deb o'tkazib yuboradi
(build yiqilmaydi). Keyin bu papkani va compose'dagi `botfixes` kontekstini olib tashlasa bo'ladi.
"""
import pathlib

# 1) «👥 Foydalanuvchilar» tugmasi qattiq yozilgan (faqat lotin-o'zbek). Ruscha / kirill tilli adminlarda
#    tugma jim turardi. Boshqa handlerlar kabi tilga moslashuvchi `text_key` ishlatiladi.
p = pathlib.Path("src/bot/handlers/admin/users.py")
s = p.read_text(encoding="utf-8")
old_import = "from src.bot.filters import IsAdmin\n"
old_filter = 'F.text == "\U0001F465 Foydalanuvchilar"'
if old_filter in s and old_import in s:
    s = s.replace(old_import, "from src.bot.filters import IsAdmin, text_key\n")
    s = s.replace(old_filter, 'text_key("admin.menu_users")')
    p.write_text(s, encoding="utf-8")
    print("patch_bot: users.py tuzatildi (menu_users tilga moslashuvchi)")
else:
    print("patch_bot: users.py — tuzatish kerak emas (allaqachon tuzatilgan yoki kod o'zgargan)")

# 2) Taklif (invite) havolalari: eski handler `Invite(token=...)` yaratardi (modelda maydon `code`) va menyuda
#    tugmasi yo'q edi. To'liq almashtiramiz: rol -> bo'lim -> muddat (1 soat/1 kun/5 kun) -> havola.
here = pathlib.Path(__file__).resolve().parent
new_invites = here / "invites_new.py"
target = pathlib.Path("src/bot/handlers/admin/invites.py")
if new_invites.is_file() and target.is_file():
    target.write_text(new_invites.read_text(encoding="utf-8"), encoding="utf-8")
    print("patch_bot: invites.py almashtirildi (1 soat / 1 kun / 5 kun)")
else:
    print("patch_bot: invites.py almashtirilmadi (fayl topilmadi)")

# 3) Foydalanuvchilar ro'yxatida «➕ Yangi foydalanuvchi» (Telegram ID bilan) o'rniga faqat
#    «🔗 Taklif havolasi» turadi: odamlar havola orqali o'zi ro'yxatdan o'tadi.
kb = pathlib.Path("src/bot/keyboards/admin.py")
ks = kb.read_text(encoding="utf-8")
old_btn = '''    builder.row(
        InlineKeyboardButton(
            text=f"➕ {_('admin.user_add_title', language=language)}",
            callback_data="user_add",
        )
    )
'''
new_btn = '''    builder.row(
        InlineKeyboardButton(
            text={
                "uz_cyrl": "\\U0001F517 Таклиф ҳаволаси",
                "ru": "\\U0001F517 Пригласительная ссылка",
            }.get(language, "\\U0001F517 Taklif havolasi"),
            callback_data="invite_start",
        )
    )
'''
if "invite_start" in ks:
    print("patch_bot: keyboards/admin.py — taklif tugmasi allaqachon bor")
elif ks.count(old_btn) == 1:
    kb.write_text(ks.replace(old_btn, new_btn), encoding="utf-8")
    print("patch_bot: users ro'yxatida «Yangi foydalanuvchi» o'rniga «Taklif havolasi» qo'yildi")
else:
    print("patch_bot: keyboards/admin.py — tugma topilmadi, o'zgartirilmadi")


# 4) Ishchi uchun "Ish yuborish" oqimi soddalashtirildi:
#    eski: Ish yuborish -> vazifa tugmasi -> rasm -> "izohni o'tkazib yuborish" -> uzun tasdiq -> Yuborish
#    yangi: (Ish yuborish) -> rasm/video (izoh = rasm ostidagi yozuv) -> Yuborish.
#    Bitta vazifasi bor ishchi tugmasiz to'g'ridan-to'g'ri rasm tashlasa ham bo'ladi.
import re as _re

sp = pathlib.Path("src/bot/handlers/worker/submit.py")
if not sp.is_file():
    print("patch_bot: submit.py topilmadi — o'tkazib yuborildi")
else:
    ss = sp.read_text(encoding="utf-8")
    if "_begin_submit" in ss:
        print("patch_bot: submit.py — allaqachon soddalashtirilgan")
    else:
        ok = True

        # (a) "Ish yuborish" reply tugmasi: bitta vazifa bo'lsa darrov rasm so'raymiz
        a = ss.find('@router.message(IsWorker(), text_key("worker.menu_submit"))')
        b = ss.find('# ==================== "Ish yuborish" (inline callback)')
        if a == -1 or b == -1 or b < a:
            ok = False
        else:
            new_menu = '''@router.message(IsWorker(), text_key("worker.menu_submit"))
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
        await message.answer(
            _("worker.no_tasks_to_submit", language=lang),
        )
        return

    if len(tasks) == 1:
        await _begin_submit(message, state, user, session, tasks[0].id)
        return

    await message.answer(
        _("worker.multiple_tasks_prompt", language=lang, count=len(tasks)),
        reply_markup=worker_tasks_keyboard(tasks, lang),
    )


_EASY = {
    "uz": {
        "ask": "📸 <b>{truck}</b>\\n🔧 {step}\\n\\nQilingan ishning <b>rasmini yoki videosini</b> yuboring.\\n\\n<i>Xohlasangiz, rasm ostiga izoh yozing.</i>",
        "confirm": "✅ {media} qabul qilindi.{note}\\n\\n👇 Yuborish uchun pastdagi <b>✅ tugmani</b> bosing.",
        "note": "\\n📝 Izoh: {c}",
        "which": "📤 Qaysi ishni yubormoqchisiz? «Ish yuborish» tugmasini bosib, ishni tanlang.",
        "none": "Hozircha yuborish uchun ish yo'q.",
    },
    "uz_cyrl": {
        "ask": "📸 <b>{truck}</b>\\n🔧 {step}\\n\\nҚилинган ишнинг <b>расмини ёки видеосини</b> юборинг.\\n\\n<i>Хоҳласангиз, расм остига изоҳ ёзинг.</i>",
        "confirm": "✅ {media} қабул қилинди.{note}\\n\\n👇 Юбориш учун пастдаги <b>✅ тугмани</b> босинг.",
        "note": "\\n📝 Изоҳ: {c}",
        "which": "📤 Қайси ишни юбормоқчисиз? «Иш юбориш» тугмасини босиб, ишни танланг.",
        "none": "Ҳозирча юбориш учун иш йўқ.",
    },
    "ru": {
        "ask": "📸 <b>{truck}</b>\\n🔧 {step}\\n\\nОтправьте <b>фото или видео</b> выполненной работы.\\n\\n<i>Если хотите, напишите комментарий под фото.</i>",
        "confirm": "✅ {media} получено.{note}\\n\\n👇 Для отправки нажмите <b>кнопку ✅</b> ниже.",
        "note": "\\n📝 Комментарий: {c}",
        "which": "📤 Какую работу отправить? Нажмите «Отправить работу» и выберите её.",
        "none": "Сейчас нет работ для отправки.",
    },
}


async def _begin_submit(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    step_id: int,
) -> None:
    """Vazifani ishchiga biriktirib, rasm/video so'raydi (tugma bosish shart emas)."""
    lang = user.language if user.language in _EASY else "uz"
    step = await get_step_with_truck(session, step_id)
    if not step or step.step_number != user.step_number or step.status not in ["pending", "rejected"]:
        await message.answer(_EASY[lang]["none"])
        return

    await claim_step(session, step, worker_id=user.id)
    await state.clear()
    await state.update_data(step_id=step_id)
    await state.set_state(SubmitWorkFSM.media)
    await message.answer(
        _EASY[lang]["ask"].format(
            truck=step.truck.serial_number, step=get_step_name(step.step_number, lang)
        ),
        reply_markup=worker_submit_cancel_keyboard(lang),
    )


'''
            ss = ss[:a] + new_menu + ss[b:]

        # (b) rasm/video/hujjat qabul qilingach izoh bosqichini o'tkazib, darrov tasdiqlashga
        pat = _re.compile(
            r'    await state\.set_state\(SubmitWorkFSM\.comment\)\n\n'
            r'    await message\.answer\(\n'
            r'        _\("worker\.submit_(?:photo|video|doc|document)_received", language=lang\),\n'
            r'        reply_markup=worker_submit_skip_comment_keyboard\(lang\),\n'
            r'    \)\n'
        )
        repl = (
            '    _cap = (message.caption or "").strip()\n'
            '    await state.update_data(worker_comment=_cap[:1000] if _cap else None)\n'
            '    await state.set_state(SubmitWorkFSM.confirm)\n'
            '    await _show_submit_confirmation(message, state, user, use_edit=False)\n'
        )
        ss, n = pat.subn(repl, ss)
        if n < 1:
            ok = False

        # (c) qisqa tasdiqlash matni
        c0 = ss.find('    """Tasdiqlash oynasini ko\'rsatish."""')
        c1 = ss.find("    if use_edit:", c0)
        if c0 == -1 or c1 == -1:
            ok = False
        else:
            new_confirm = '''    """Tasdiqlash oynasini ko'rsatish (qisqa va tushunarli)."""
    lang = user.language if user.language in _EASY else "uz"
    data = await state.get_data()
    media = {
        "photo": {"uz": "📷 Rasm", "uz_cyrl": "📷 Расм", "ru": "📷 Фото"},
        "video": {"uz": "🎥 Video", "uz_cyrl": "🎥 Видео", "ru": "🎥 Видео"},
        "document": {"uz": "📄 Fayl", "uz_cyrl": "📄 Файл", "ru": "📄 Файл"},
    }.get(data.get("media_type", "photo"), {}).get(lang, "📎")
    c = data.get("worker_comment")
    note = _EASY[lang]["note"].format(c=c) if c else ""
    text = _EASY[lang]["confirm"].format(media=media, note=note)

'''
            ss = ss[:c0] + new_confirm + ss[c1:]

        # (d) tugmasiz: bitta vazifasi bor ishchi to'g'ridan-to'g'ri rasm/video tashlasa
        if "StateFilter" not in ss:
            ss = _re.sub(r"^(from aiogram import [^\n]+\n)", r"\1from aiogram.filters import StateFilter\n", ss, count=1, flags=_re.M)
        ss = ss.rstrip("\n") + '''


# ==================== Tugmasiz: to'g'ridan-to'g'ri rasm/video ====================
@router.message(IsWorker(), StateFilter(None), F.photo | F.video)
async def quick_send(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
):
    """Ishchi «Ish yuborish»ni bosmasdan rasm/video tashlasa: bitta vazifa bo'lsa — darrov qabul qilamiz."""
    lang = user.language if user.language in _EASY else "uz"
    tasks = await get_worker_tasks(session, user.id, user.step_number)
    if len(tasks) != 1:
        await message.answer(_EASY[lang]["which"] if tasks else _EASY[lang]["none"])
        return

    step = tasks[0]
    await claim_step(session, step, worker_id=user.id)
    await state.clear()
    is_photo = bool(message.photo)
    _cap = (message.caption or "").strip()
    await state.update_data(
        step_id=step.id,
        media_type="photo" if is_photo else "video",
        media_file_id=message.photo[-1].file_id if is_photo else message.video.file_id,
        worker_comment=_cap[:1000] if _cap else None,
    )
    await state.set_state(SubmitWorkFSM.confirm)
    await _show_submit_confirmation(message, state, user, use_edit=False)
'''
        if ok and "_begin_submit" in ss and n >= 1:
            sp.write_text(ss, encoding="utf-8")
            print(f"patch_bot: submit.py soddalashtirildi ({n} ta media handler)")
        else:
            print("patch_bot: submit.py — kutilgan kod topilmadi, o'zgartirilmadi (bot kodi o'zgargan bo'lishi mumkin)")
