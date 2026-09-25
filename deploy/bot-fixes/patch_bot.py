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


# 5) Ro'yxatdan o'tishda SELFI (yuz rasmi): ism -> telefon -> selfi -> tasdiqlash.
#    Rasm foydalanuvchi profiliga (users.photo_file_id / photo_path) saqlanadi va web'da avatar bo'lib chiqadi.
def _patch_selfie() -> None:
    rp = pathlib.Path("src/bot/handlers/registration.py")
    stp = pathlib.Path("src/bot/states/registration.py")
    up = pathlib.Path("src/database/models/user.py")
    if not (rp.is_file() and stp.is_file() and up.is_file()):
        print("patch_bot: selfi — kerakli fayllar topilmadi, o'tkazib yuborildi")
        return
    rs, sts, us = (p.read_text(encoding="utf-8") for p in (rp, stp, up))
    if "process_selfie" in rs:
        print("patch_bot: selfi — allaqachon qo'shilgan")
        return

    # (a) FSM holati
    st_old = "    phone = State()\n    confirm = State()"
    # (b) telefon bosqichlaridan keyin selfi so'raymiz
    a_old = ("    await state.update_data(phone=None)\n    await state.set_state(RegistrationFSM.confirm)\n\n"
             "    await _show_registration_confirmation(callback.message, state)")
    b_old = ("    await state.update_data(phone=text)\n    await state.set_state(RegistrationFSM.confirm)\n\n"
             "    await _show_registration_confirmation(message, state)")
    # (c) tasdiqlashda foydalanuvchiga rasmni yozamiz
    c_old = '    if data.get("phone"):\n        new_user.phone = data["phone"]\n'
    # (d) tasdiqlash oynasi: tahrirlab bo'lmasa yangi xabar + selfi qatori
    d_old = ("    await message.edit_text(\n        text,\n        reply_markup=registration_confirm_keyboard(),\n    )")
    e_old = '        f"📞 Telefon: {phone}\\n\\n"'
    # (e) foydalanuvchi modeli
    u_old = "    # ==== Relationships ===="

    checks = [(st_old in sts, "states"), (a_old in rs, "skip_phone"), (b_old in rs, "process_phone"),
              (c_old in rs, "confirm"), (d_old in rs, "confirmation"), (e_old in rs, "confirmation-text"),
              (u_old in us, "user model")]
    missing = [n for ok, n in checks if not ok]
    if missing:
        print(f"patch_bot: selfi — kutilgan kod topilmadi ({', '.join(missing)}); o'zgartirilmadi")
        return

    sts = sts.replace(st_old, "    phone = State()\n    photo = State()\n    confirm = State()")
    rs = rs.replace(a_old, "    await state.update_data(phone=None)\n    await _ask_selfie(callback.message, state, edit=True)")
    rs = rs.replace(b_old, "    await state.update_data(phone=text)\n    await _ask_selfie(message, state)")
    rs = rs.replace(c_old, c_old + '    new_user.photo_file_id = data.get("photo_file_id")\n    new_user.photo_path = data.get("photo_path")\n')
    rs = rs.replace(d_old, ("    try:\n        await message.edit_text(text, reply_markup=registration_confirm_keyboard())\n"
                            "    except Exception:  # foydalanuvchining o'z xabarini tahrirlab bo'lmaydi\n"
                            "        await message.answer(text, reply_markup=registration_confirm_keyboard())"))
    rs = rs.replace(e_old, '        f"📞 Telefon: {phone}\\n"\n        f"🤳 Selfi: {\'✅ yuborilgan\' if data.get(\'photo_file_id\') else \'—\'}\\n\\n"')
    us = us.replace(u_old, ('    # ==== Selfi (ro\'yxatdan o\'tishda yuborilgan yuz rasmi) ====\n'
                            '    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)\n'
                            '    photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)\n\n' + u_old), 1)

    rs = rs.rstrip("\n") + '''


# ==== Selfi (yuz rasmi) ====
async def _ask_selfie(message: Message, state: FSMContext, edit: bool = False) -> None:
    from src.bot.keyboards.registration import registration_cancel_keyboard

    await state.set_state(RegistrationFSM.photo)
    text = (
        "3️⃣ <b>Selfi yuboring</b> 🤳\\n\\n"
        "Yuzingiz <b>aniq ko'rinadigan</b> rasm yuboring (yorug' joyda, kameraga qarab).\\n"
        "Bu rasm rahbarga sizni tanish uchun kerak.\\n\\n"
        "👇 Pastdagi <b>📎</b> tugmani bosib, <b>Kamera</b>ni tanlang va suratga oling."
    )
    if edit:
        try:
            await message.edit_text(text, reply_markup=registration_cancel_keyboard())
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=registration_cancel_keyboard())


@router.message(RegistrationFSM.photo, F.photo)
async def process_selfie(message: Message, state: FSMContext) -> None:
    """Selfini qabul qilamiz va serverga ham saqlab qo'yamiz (Telegram file_id bilan birga)."""
    file_id = message.photo[-1].file_id
    local = None
    try:
        from pathlib import Path
        from uuid import uuid4

        from src.config import settings

        folder = Path(settings.MEDIA_ROOT) / "users"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid4().hex}.jpg"
        tg_file = await message.bot.get_file(file_id)
        await message.bot.download_file(tg_file.file_path, destination=str(path))
        local = str(path)
    except Exception:  # noqa: BLE001 — file_id baribir saqlanadi, web uni Telegram'dan oladi
        local = None
    await state.update_data(photo_file_id=file_id, photo_path=local)
    await state.set_state(RegistrationFSM.confirm)
    await _show_registration_confirmation(message, state)


@router.message(RegistrationFSM.photo)
async def selfie_invalid(message: Message) -> None:
    from src.bot.keyboards.registration import registration_cancel_keyboard

    await message.answer(
        "❌ Iltimos, <b>rasm</b> yuboring (selfi).\\n\\n"
        "Matn yoki video emas — yuzingiz ko'rinadigan oddiy surat kerak.",
        reply_markup=registration_cancel_keyboard(),
    )
'''
    stp.write_text(sts, encoding="utf-8")
    rp.write_text(rs, encoding="utf-8")
    up.write_text(us, encoding="utf-8")
    print("patch_bot: ro'yxatdan o'tishga selfi bosqichi qo'shildi")


_patch_selfie()


# 6) Bir yuborishda bir nechta rasm/video (10 rasm + 5 video + 3 fayl). Jadval `truck_step_media` (bot-compat.sql).
#    submit.py to'liq almashtiriladi (submit_multi.py), QC/tarix ko'rinishlariga qo'shimcha fayllar albomi qo'shiladi.
def _patch_multi_media() -> None:
    svc_src = here / "step_media_service.py"
    sub_src = here / "submit_multi.py"
    sub_dst = pathlib.Path("src/bot/handlers/worker/submit.py")
    svc_dst = pathlib.Path("src/services/step_media_service.py")
    if not (svc_src.is_file() and sub_src.is_file() and sub_dst.is_file() and svc_dst.parent.is_dir()):
        print("patch_bot: ko'p media — kerakli fayllar topilmadi, o'tkazib yuborildi")
        return
    if "truck_step_media" in sub_dst.read_text(encoding="utf-8"):
        print("patch_bot: ko'p media — allaqachon qo'shilgan")
        return

    def _album(path: str, anchor: str, call_first: str) -> None:
        fp = pathlib.Path(path)
        if not fp.is_file():
            print(f"patch_bot: {path} topilmadi — albom qo'shilmadi")
            return
        txt = fp.read_text(encoding="utf-8")
        if "send_extra_media" in txt:
            return
        if txt.count(anchor) != 1:
            print(f"patch_bot: {path} — kutilgan kod topilmadi, albom qo'shilmadi")
            return
        ins = (
            "    from src.services.step_media_service import send_extra_media\n"
            f"    await send_extra_media(callback.message, {call_first}.id, {call_first}.media_file_id)\n"
        )
        fp.write_text(txt.replace(anchor, ins + anchor), encoding="utf-8")

    _album(
        "src/bot/handlers/qc/review.py",
        '    keyboard = qc_review_keyboard(step.id, lang)\n\n    if step.media_type == "photo" and step.media_file_id:\n',
        "step",
    )
    _album(
        "src/bot/handlers/worker/history.py",
        '    if step.media_type == "photo" and step.media_file_id:\n'
        "        await callback.message.answer_photo(\n"
        "            photo=step.media_file_id,\n"
        "            caption=text,\n"
        "            reply_markup=worker_history_detail_keyboard(step, lang),\n",
        "step",
    )
    _album(
        "src/bot/handlers/qc/history.py",
        '    if step.media_type == "photo" and step.media_file_id:\n'
        "        await callback.message.answer_photo(\n"
        "            photo=step.media_file_id,\n"
        "            caption=text,\n"
        "            reply_markup=qc_history_detail_keyboard(lang),\n",
        "step",
    )
    svc_dst.write_text(svc_src.read_text(encoding="utf-8"), encoding="utf-8")
    backup = sub_dst.read_text(encoding="utf-8")
    sub_dst.write_text(sub_src.read_text(encoding="utf-8"), encoding="utf-8")
    try:  # sintaksis xatosi bo'lsa — eski (bitta media) versiyaga qaytamiz, bot yiqilmasin
        import py_compile

        py_compile.compile(str(sub_dst), doraise=True)
        py_compile.compile(str(svc_dst), doraise=True)
    except Exception as e:  # noqa: BLE001
        sub_dst.write_text(backup, encoding="utf-8")
        print(f"patch_bot: ko'p media — kompilyatsiya xatosi ({e}); eski submit.py qaytarildi")
        return
    print("patch_bot: ko'p media qo'shildi (10 rasm + 5 video + 3 fayl)")


_patch_multi_media()


# 7) Trucklar yuzlab bo'lganda ishchi vazifalari va QC navbati tugmalari Telegram chegarasidan (100 ta tugma) oshib
#    ketmasin: eng muhim 40 tasi ko'rsatiladi (ro'yxat allaqachon prioritet va muddat bo'yicha tartiblangan).
def _patch_button_caps() -> None:
    for path, old, new in (
        ("src/bot/keyboards/worker.py", "    for step in tasks:\n        truck = step.truck", "    for step in tasks[:40]:\n        truck = step.truck"),
        ("src/bot/keyboards/qc.py", "    for step in steps:\n        truck = step.truck", "    for step in steps[:40]:\n        truck = step.truck"),
    ):
        fp = pathlib.Path(path)
        if not fp.is_file():
            print(f"patch_bot: {path} topilmadi — tugma chegarasi qo'yilmadi")
            continue
        txt = fp.read_text(encoding="utf-8")
        if new in txt:
            continue
        if txt.count(old) != 1:
            print(f"patch_bot: {path} — kutilgan kod topilmadi, tugma chegarasi qo'yilmadi")
            continue
        fp.write_text(txt.replace(old, new), encoding="utf-8")
        print(f"patch_bot: {path} — ro'yxat 40 tagacha cheklandi")


_patch_button_caps()

