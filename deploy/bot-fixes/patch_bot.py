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
