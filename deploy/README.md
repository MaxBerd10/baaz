# Ubuntu serverga o'rnatish (Postgres + bot + web)

Bitta `docker compose up` bilan: **Postgres**, **Telegram bot**, **web panel**. Web serverda faqat
`127.0.0.1:8090` da ochiladi; internetga ikki yo'ldan biri bilan chiqariladi:

**A) Cloudflare Tunnel (tavsiya — serverda allaqachon `cloudflared` bo'lsa)**
```
brauzer ─https─▶ Cloudflare ─tunnel─▶ cloudflared ─▶ 127.0.0.1:8090 (web) ─▶ Postgres ◀─ bot ◀─▶ Telegram
```
Port ochish, A-yozuv, sertifikat kerak emas. Tunnel sozlamasida: Public hostname `panel.max.co.uz` → `http://localhost:8090`.

**B) Caddy (agar tunnel yo'q bo'lsa):** `docker compose --profile caddy up -d --build`, `.env` da `DOMAIN=...`,
A-yozuv serverga qarasin, 80/443 ochiq bo'lsin.

## 0. Oldindan
- (B variant uchun) DNS'da **A-yozuv** (masalan `panel.example.uz`) → server IP'si, 80/443 ochiq.
- Postgres/bot/web tashqariga ochilmaydi.
- @BotFather'dan bot tokeni, @userinfobot'dan o'zingizning Telegram ID'ingiz.

## 1. Docker o'rnatish (bir marta)
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # keyin qayta kiring (logout/login)
sudo ufw allow 22,80,443/tcp && sudo ufw enable   # ufw ishlatsangiz
```

## 2. Sozlash va ishga tushirish
```bash
git clone https://github.com/MaxBerd10/baaz.git
cd baaz/deploy
cp env.example .env
nano .env        # BOT_TOKEN, ADMIN_IDS, WEB_PASSWORD (parol va kalit avtomatik yoziladi, pastga qarang)
docker compose up -d --build
```
`.env` da:
- `ADMIN_IDS=[123456789]` — **kvadrat qavs bilan** (botning `123456789` ko'rinishi xato beradi).
- `POSTGRES_PASSWORD` — faqat harf/raqam. `SECRET_KEY` — `openssl rand -hex 32`. `WEB_PASSWORD` — panel paroli.

Birinchi qurish 3–5 daqiqa oladi. Keyin:
```bash
docker compose ps                 # migrate = Exited (0), qolganlari Up
docker compose logs -f bot        # "Bot tasdiqlandi: @..." ko'rinsin
```
Serverning o'zida `curl -I http://127.0.0.1:8090/login` → `200`. So'ng tunnelga hostname qo'shing va `https://panel.max.co.uz` → `WEB_PASSWORD` bilan kiring. Telegram'da botga `/start` yozing — `ADMIN_IDS` dagi
ID avtomatik admin bo'ladi; keyin botdan ishchi/QC uchun taklif havolalari yarating.

## Kundalik
| Nima | Buyruq |
|---|---|
| Yangilash (web yoki bot yangi versiya) | `git pull && docker compose up -d --build` |
| Loglar | `docker compose logs -f bot` / `web` / `caddy` |
| Qayta ishga tushirish | `docker compose restart bot` |
| Zaxira nusxa | `docker compose exec -T db pg_dump -U truckbot truck_factory > backup_$(date +%F).sql` |
| Tiklash | `docker compose exec -T db psql -U truckbot truck_factory < backup.sql` |
| To'xtatish (ma'lumot saqlanadi) | `docker compose down` (⚠️ `-v` qo'shmang — bazani o'chiradi) |

## Muammolar
- **HTTPS chiqmayapti** → DNS hali yangilanmagan yoki 80/443 yopiq: `docker compose logs caddy`.
- **`bot` yiqilyapti, `ADMIN_IDS`** → `[123456789]` ko'rinishida yozing.
- **Web'da ma'lumot yo'q** → botda hali truck yaratilmagan (admin: "Trucklar → qo'shish").
- **Rasmlar chiqmayapti** → `BOT_TOKEN` web'ga ham beriladi (compose o'zi beradi); `docker compose logs web`.

## Eslatmalar
- `bot-compat.sql` — botning migratsiyalaridagi kamchilikni (`users.language`, `notification_settings`) to'ldiradi.
  Bot repo'sida haqiqiy migratsiya yozilgach, bu fayl va compose'dagi `psql ... /compat.sql` qadamini o'chiring.
- Botning o'z `Dockerfile`'i `locales/` va `migrations/` ni image'ga olmaydi, shuning uchun compose o'zining
  (inline) Dockerfile'ini ishlatadi. Bot manbasi GitHub'dan olinadi; lokal nusxadan qurish uchun `.env` da `BOT_SRC`.
- Vercel'dagi demo sayt bundan mustaqil — o'zgarmaydi.

## Web'dan zakaz berish (yangi)
1. **Modellar** bo'limi → model qo'shing (nom, **rasm**, tavsif). Rasm serverda `web_media` papkasida saqlanadi.
2. **Yangi zakaz** (yuqori o'ngdagi tugma yoki Trucklar → «＋ Truck qo'shish»): model, buyurtmachi, prioritet, muddat →
   **Zakaz yaratish**. Truck botning bazasiga yoziladi (6 bosqich bilan) va botdagi **barcha faol foydalanuvchilarga**
   (ishchi, QC, admin) o'z tilida «yangi zakaz keldi» xabari ketadi, model rasmi bilan.
   1-bosqich ishchilariga «Vazifalarim»ni bosib ishni boshlash aytiladi; qolganlarga ma'lumot uchun.
3. Xabar `BOT_TOKEN` orqali web'dan yuboriladi (compose o'zi beradi). Natija truck sahifasida ko'rinadi
   («N kishiga yuborildi, M tasiga yetmadi» — botni bloklaganlar yetmaydi).

Yangilashdan keyin: `git pull && docker compose up -d --build` (web ishga tushganda ko'rinishlar va `web.create_truck`
funksiyasi avtomatik yangilanadi).

## Botga odam qo'shish
1. Yangi odam botga **`/id`** yozadi — bot uning Telegram ID'sini qaytaradi (u hali tizimda bo'lmasa ham ishlaydi).
2. Admin botda **👥 Foydalanuvchilar → ➕ Yangi foydalanuvchi**: ID → ism → rol (ishchi/QC/admin) → bosqich → tasdiqlash.
3. Odam botga `/start` yozadi — menyusi paydo bo'ladi.

`bot-fixes/patch_bot.py` — botning manba kodidagi kichik xatolarni docker build paytida tuzatadi
(hozir: «👥 Foydalanuvchilar» tugmasi faqat lotin-o'zbek tilida ishlardi). Bot repo'sida tuzatilgach, skript
o'zini o'tkazib yuboradi; keyin papkani va compose'dagi `botfixes` ni o'chirsa bo'ladi.
