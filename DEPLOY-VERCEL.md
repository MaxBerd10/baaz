# Web-panelni Vercel'ga joylash (mijozga ko'rsatish uchun)

Faqat **web-panel** joylashtiriladi. Bot Vercel'da ishlamaydi (serverless — doimiy
jarayon yo'q) va kompyuterda / serverda alohida ishlaydi.

**Tashqi baza kerak emas.** Demo ma'lumot loyihaga qo'shilgan `demo.db` (SQLite)
faylida turadi va Vercel uni **faqat-o'qish** rejimida ochadi. Media Vercel'da
saqlanmaydi — rasm o'rniga chiroyli placeholder ikonka ko'rsatiladi (dizayn va
raqamlarni ko'rsatish uchun yetarli).

---

## 1. Demo bazani yangilash (ixtiyoriy, kompyuterdan)

`demo.db` allaqachon repo ichida — 10 ta namunaviy food truck bilan. Yangilash kerak
bo'lsa:

```bash
cd ~/Desktop/baaz_project
source .venv/bin/activate
rm -f demo.db
DATABASE_URL="sqlite+aiosqlite:///./demo.db" python demo_data.py
git add -f demo.db && git commit -m "demo ma'lumot yangilandi" && git push
```

## 2. Vercel'da deploy

1. <https://vercel.com> → **Add New → Project** → `MaxBerd10/baaz` repo'sini import qiling.
2. **Framework Preset**: `Other` (loyihada `vercel.json` bor).
3. **Environment Variables** qo'shing:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | `sqlite+aiosqlite:///file:demo.db?mode=ro&immutable=1&uri=true` |
   | `SKIP_INIT_DB` | `1` |
   | `WEB_PASSWORD` | mijozga beriladigan parol |
   | `SECRET_KEY` | uzun tasodifiy satr (`openssl rand -hex 32`) |
   | `MEDIA_ROOT` | `/tmp/media` |
   | `TIMEZONE` | `Asia/Tashkent` |

4. **Deploy** → `https://baaz-xxxx.vercel.app` manzili chiqadi.

## 3. Mijozga ko'rsatish

Manzilni oching → `WEB_PASSWORD` ni kiriting. Barcha bo'limlar ishlaydi:
Boshqaruv paneli, Mahsulotlar, Bosqichlar, Ishchilar, Sifat nazorati,
KPI va tahlillar, Hisobotlar, Ogohlantirishlar, Kalendar, Fayllar, Sozlamalar.

## Eslatmalar

- **Bot** joylashtirilmadi — kompyuterda `python run_bot.py` bilan ishlab tursin.
  Bot alohida SQLite (`baaz.db`) bilan ishlaydi, `demo.db` ga tegmaydi.
- Vercel'dagi demo **statik** (o'zgarmaydi) — bu demo uchun ayni muddao.
- **Keyinchalik jonli baza kerak bo'lsa**: `DATABASE_URL` ni Neon/Supabase Postgres
  manziliga o'zgartirish kifoya, `SKIP_INIT_DB` ni olib tashlang. Kod ikkalasini ham
  qo'llab-quvvatlaydi.
- **Haqiqiy media kerak bo'lsa**: Vercel Blob yoki S3 (`media_store.py` o'zgartiriladi).
