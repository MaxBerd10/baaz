# Web-panelni Vercel'ga joylash (mijozga ko'rsatish uchun)

Faqat **web-panel** joylashtiriladi. Bot Vercel'da ishlamaydi (serverless — doimiy
jarayon yo'q) — bot kompyuterda / serverda alohida ishlaydi.

Vercel fayl tizimi faqat-o'qish va vaqtinchalik, shuning uchun:
- **Baza** — tashqi Postgres (Neon, bepul).
- **Media** — Vercel'da saqlanmaydi; rasm o'rniga chiroyli placeholder ikonka ko'rsatiladi
  (mijozga dizayn va raqamlarni ko'rsatish uchun yetarli).

---

## 1. Neon Postgres (bepul)

1. <https://neon.tech> — ro'yxatdan o'ting → **New Project** (nom: `baaz`).
2. Ochilgan **Connection string** ni nusxa oling. Ko'rinishi:
   ```
   postgresql://user:parol@ep-xxxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

## 2. Bazani to'ldirish (kompyuterdan, bir marta)

```bash
cd ~/Desktop/baaz_project
source .venv/bin/activate
DATABASE_URL="<Neon connection string>" python demo_data.py
```

Bu jadvallarni yaratadi va 10 ta namunaviy food truck qo'shadi.
(`app/db.py` URL'ni avtomat `asyncpg` + SSL ga o'giradi.)

## 3. Kodni GitHub'ga yuklash

```bash
cd ~/Desktop/baaz_project
git init
git add -A
git commit -m "Baaz web dashboard"
gh repo create baaz --private --source=. --push
```
(`gh` bo'lmasa: github.com da repo oching, so'ng `git remote add origin <url> && git push -u origin main`)

> `.env` fayli `.gitignore` da — bot tokeni GitHub'ga tushmaydi. ✅

## 4. Vercel'da deploy

1. <https://vercel.com> → **Add New → Project** → `baaz` repo'sini import qiling.
2. **Framework Preset**: `Other` (loyihada `vercel.json` bor).
3. **Environment Variables** qo'shing:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | Neon connection string |
   | `WEB_PASSWORD` | mijozga beriladigan parol |
   | `SECRET_KEY` | uzun tasodifiy satr (masalan `openssl rand -hex 32`) |
   | `MEDIA_ROOT` | `/tmp/media` |
   | `SKIP_INIT_DB` | `1` |
   | `TIMEZONE` | `Asia/Tashkent` |

4. **Deploy** → `https://baaz-xxxx.vercel.app` manzili chiqadi.

## 5. Mijozga ko'rsatish

Manzilni oching → `WEB_PASSWORD` ni kiriting. Barcha bo'limlar ishlaydi:
Boshqaruv paneli, Mahsulotlar, Bosqichlar, Ishchilar, Sifat nazorati,
KPI va tahlillar, Hisobotlar, Ogohlantirishlar, Kalendar, Fayllar, Sozlamalar.

## Eslatmalar

- **Bot** joylashtirilmadi — kompyuterda `python run_bot.py` bilan ishlab tursin.
  Keyinroq botni webhook rejimida alohida joylashtirsa bo'ladi.
- **Neon bepul tarif** faolsizlikdan keyin "uxlaydi" — birinchi ochilish ~1–2 soniya.
- **Demo ma'lumotni yangilash**: 2-qadamni qayta ishga tushiring. Toza boshlash uchun
  Neon SQL editor'da `drop schema public cascade; create schema public;` bajaring,
  so'ng qayta seed qiling.
- **Haqiqiy media kerak bo'lsa** (kelajakda): Vercel Blob yoki S3 ulash kerak —
  `media_store.py` ni o'zgartirish bilan.
