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

# 3) Foydalanuvchilar ro'yxatiga «🔗 Taklif havolasi» tugmasi.
kb = pathlib.Path("src/bot/keyboards/admin.py")
ks = kb.read_text(encoding="utf-8")
anchor = '''            callback_data="user_add",
        )
    )
'''
if "invite_start" in ks:
    print("patch_bot: keyboards/admin.py — taklif tugmasi allaqachon bor")
elif ks.count(anchor) == 1:
    add = anchor + '''
    builder.row(
        InlineKeyboardButton(
            text={
                "uz_cyrl": "\\U0001F517 Таклиф ҳаволаси",
                "ru": "\\U0001F517 Пригласительная ссылка",
            }.get(language, "\\U0001F517 Taklif havolasi"),
            callback_data="invite_start",
        )
    )
'''
    kb.write_text(ks.replace(anchor, add), encoding="utf-8")
    print("patch_bot: users ro'yxatiga taklif tugmasi qo'shildi")
else:
    print("patch_bot: keyboards/admin.py — anchor topilmadi, tugma qo'shilmadi")
