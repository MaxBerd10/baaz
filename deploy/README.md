# Ubuntu serverga o'rnatish (Postgres + bot + web + HTTPS)

Bitta `docker compose up` bilan: **Postgres**, **Telegram bot**, **web panel** va domen uchun **HTTPS (Caddy)**.

```
Telegram ◀──▶ bot ──▶ Postgres ◀── web ◀── Caddy(:443) ◀── brauzer (https://DOMEN)
```

## 0. Oldindan
- DNS: domeningizda **A-yozuv** (masalan `panel.example.uz`) → serveringizning IP'si.
- Serverda 80 va 443 portlar ochiq bo'lsin (Postgres/bot/web tashqariga ochilmaydi).
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
cp .env.example .env
nano .env        # DOMAIN, BOT_TOKEN, ADMIN_IDS, parollar
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
Brauzerda `https://DOMEN` → `WEB_PASSWORD` bilan kiring. Telegram'da botga `/start` yozing — `ADMIN_IDS` dagi
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
