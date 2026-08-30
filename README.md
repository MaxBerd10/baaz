# BAAZ — Food truck ishlab chiqarish + Sifat nazorati (Telegram + Web)

Food truck (mobil oshxona) ishlab chiqarish liniyasi — 7 bosqich (sozlanadigan):
shassi va rama → korpus va karkas → izolyatsiya va tashqi qoplama → suv va gaz tizimi →
elektr tizimi → oshxona jihozlari → yakuniy jihozlash va sinov.

Har bir bosqichdan keyin **Sifat nazorati** rasm/video ko'radi, **tekshiruv ro'yxati**dagi
(checklist) har bir punktni ✅/❌ belgilaydi va **tasdiqlaydi** yoki **qaytaradi**.
Barcha punkt ✅ bo'lmasa tasdiqlab bo'lmaydi. Tasdiqsiz keyingi bosqich ochilmaydi.

## Rollar

| Rol | Nima ko'radi |
|-----|--------------|
| 👷 Ishchi | Faqat **o'z bosqichidagi** mahsulotlar, o'z bosqichiga kelgan qaytarish sababi. Boshqa bosqich xatolarini **ko'rmaydi**. |
| 🔍 Sifat nazorati | Tekshiruv navbati, rasm/video, tasdiqlash / qaytarish |
| 👑 Rahbar | Hammasi: barcha bosqichlar, mahsulotlar, media, xatolar, vaqtlar, ishchi samaradorligi, to'liq audit tarix (Telegram + **PROD CRM** web-panel) |

**Web-panel (PROD CRM)** — http://localhost:8080, parol `.env` dagi `WEB_PASSWORD`:
Boshqaruv paneli (KPI kartalar, 7 bosqich jarayoni, progress donut, bosqichlar KPI
jadvali, top qaytarish sabablari, real-time faollik, liniyalar holati, kunlik dinamika),
Mahsulotlar, Bosqichlar, Ishchilar, Sifat nazorati, Hisobotlar, KPI va tahlillar,
Ogohlantirishlar. Grafiklar ichki SVG — internet talab qilmaydi.

## Texnologiya

- Telegram bot — `aiogram 3`
- Backend / model — `SQLAlchemy 2` (async), SQLite (lokal) yoki PostgreSQL (prod)
- Rahbar web-panel — `FastAPI` + Jinja2
- Media — lokal papka (`MEDIA_ROOT`)

## Tez ishga tushirish (lokal, SQLite)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env ni tahrirlang: BOT_TOKEN, ADMIN_TELEGRAM_IDS, WEB_PASSWORD

python seed.py          # baza + 7 ta placeholder bosqich
python run_bot.py        # Telegram bot
python run_web.py        # http://localhost:8080  (alohida terminalda)
```

### Yordamchi skriptlar

```bash
python smoke_test.py     # ish oqimini (7 bosqich + qaytarish) Telegramsiz tekshiradi
python demo_data.py      # web-panelni ko'rish uchun 5 ta soxta mahsulot qo'shadi
```

## Docker (PostgreSQL bilan)

```bash
cp .env.example .env      # BOT_TOKEN, ADMIN_TELEGRAM_IDS, WEB_PASSWORD to'ldiring
docker compose up --build
```

Web panel: <http://localhost:8080>

## Birinchi sozlash

1. `ADMIN_TELEGRAM_IDS` da ko'rsatilgan hisob botga `/start` bosadi → avtomat **Rahbar**.
2. Rahbar → **🏭 Bosqichlar** → har bir bosqich nomi/tavsifini yozadi, kerak bo'lsa yangi bosqich qo'shadi.
3. Ishchi va sifat xodimlari botga `/start` bosadi → «Tayinlanmagan» holatga tushadi.
4. Rahbar → **👥 Xodimlar** → har biriga rol (ishchi + bosqich / sifat) biriktiradi.
5. Rahbar → **➕ Yangi mahsulot** → `PR-000001` yaratiladi, 1-bosqich ishchilariga xabar boradi.

## Ish oqimi

```
Yangi mahsulot → 1-bosqich (ishchi: rasm/video + izoh) → 🔍 Sifat
      ├── ✅ tasdiq  → 2-bosqich → 🔍 Sifat → ... → 7-bosqich → 🔍 → 🟢 TAYYOR
      └── ❌ qaytdi  → sabab yoziladi → o'sha ishchiga qaytadi (urinish #2) → qayta 🔍
```

Har bir amal (kim, qachon, nima) `audit_logs` jadvalida saqlanadi — Web paneldagi
**Tarix** bo'limida ko'rinadi.

## Loyiha tuzilishi

```
app/
  config.py          sozlamalar (.env)
  models.py          DB modellari
  db.py              engine / session
  enums.py           holatlar, rollar
  services/          biznes-mantiq (workflow — asosiy state machine)
  bot/               aiogram: handlerlar, klaviaturalar, matnlar
  web/               FastAPI rahbar paneli + shablonlar
run_bot.py  run_web.py  seed.py
```

## Sozlamalar (.env)

| O'zgaruvchi | Izoh |
|-------------|------|
| `BOT_TOKEN` | @BotFather token |
| `ADMIN_TELEGRAM_IDS` | vergul bilan; bu hisoblar avtomat rahbar |
| `DATABASE_URL` | `sqlite+aiosqlite:///./baaz.db` yoki `postgresql+asyncpg://...` |
| `MEDIA_ROOT` | rasm/video papkasi (default `./media`) |
| `WEB_PASSWORD` | web-panelga kirish paroli |
| `SECRET_KEY` | cookie imzosi uchun uzun tasodifiy satr |
| `DEFAULT_STAGE_COUNT` | birinchi ishga tushishda yaratiladigan bosqichlar soni |
| `MIN_MEDIA_TO_SUBMIT` | sifatga yuborishdan oldin minimal media soni (default 1) |
