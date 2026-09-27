# Telegram bot (`truck-factory-bot`) ↔ Web panel

```
Ishchi/QC/Admin ──Telegram──▶  BOT (src.main)  ──yozadi──▶  ┐
                                                            │  Postgres (Neon)
Rahbar ──brauzer──▶  WEB  ──o'qiydi (+ buyurtma yaratadi)──◀───┘
                          │
                          └─ rasmlar: Telegram file_id orqali (BOT_TOKEN)
```

- **Bir baza.** Bot o'z jadvallarini (`users`, `trucks`, `truck_steps`) `public` sxemasida yuritadi.
- **Web bot jadvallariga to'g'ridan-to'g'ri yozmaydi** (faqat `web.create_truck()` funksiyasi orqali truck yaratadi, pastga qarang). `app/bot_views.sql` bot jadvallarini web kutgan shaklga o'giradigan
  VIEW'larni `web` sxemasida yaratadi (`products`, `stage_runs`, `media`, …). Botga tegilmaydi.
- **Real vaqt.** VIEW'lar jonli — ishchi botda "yuborish" bossa, web'da keyingi yangilashda ko'rinadi.
- **Rasmlar.** Web ularni Telegram'dan `file_id` bilan olib beradi (token faqat serverda qoladi).
- `BOT_DB` o'rnatilmasa web avvalgidek **demo rejimida** ishlaydi (SQLite) — mijozga ko'rsatilayotgan sayt buzilmaydi.

## 1. Postgres (Neon)

1. https://neon.tech → yangi project (region: Frankfurt) → **Connection string** ni nusxalang.
2. Bot uchun: `.env` ichida `DB_URL=postgresql+asyncpg://USER:PASS@HOST/DB?ssl=require`
3. Web uchun (Vercel): `DATABASE_URL=postgresql://USER:PASS@HOST/DB?sslmode=require`
   (pooled `-pooler` host ham bo'ladi — web `statement_cache_size=0` ni o'zi qo'yadi).

## 2. Botning jadvallarini yaratish

Botning papkasida:

```bash
alembic upgrade head
```

> ⚠️ **Botdagi kamchilik.** Botning migratsiyalari modellardan orqada qolgan: `users.language`
> ustuni va `notification_settings` jadvali hech qaysi migratsiyada yo'q (til tanlash tizimi
> qo'shilganda migratsiya yozilmagan). Toza bazada bot `INSERT INTO users (... language)` da
> yiqiladi. Bot repo'sida `alembic revision --autogenerate -m "users.language, notification_settings"`
> qilib, `alembic upgrade head` qiling. Shoshilinch bo'lsa qo'lda:
>
> ```sql
> ALTER TABLE users ADD COLUMN IF NOT EXISTS language varchar(10) NOT NULL DEFAULT 'uz';
> CREATE TABLE IF NOT EXISTS notification_settings (
>   id serial PRIMARY KEY,
>   user_id int UNIQUE REFERENCES users(id) ON DELETE CASCADE,
>   on_new_task bool DEFAULT true, on_approved bool DEFAULT true, on_rejected bool DEFAULT true,
>   on_next_step bool DEFAULT true, daily_report bool DEFAULT false);
> ```

## 3. Web ko'rinishlarini o'rnatish

Web repo'sida (bir marta; bot migratsiyasi o'zgarganda qayta ishga tushirish xavfsiz):

```bash
DATABASE_URL='postgresql://USER:PASS@HOST/DB?sslmode=require' python -m app.botdb install
DATABASE_URL='...' python -m app.botdb check      # har bir view nechta qator berayotganini ko'rsatadi
```

## 4. Vercel muhit o'zgaruvchilari

| Nomi | Qiymat |
|---|---|
| `BOT_DB` | `1` |
| `DATABASE_URL` | 1-bosqichdagi Neon URL |
| `BOT_TOKEN` | botning tokeni (faqat rasmlarni ko'rsatish uchun) |
| `WEB_PASSWORD`, `SECRET_KEY` | avvalgidek |

Keyin **Redeploy**. Token hech qachon repo'ga yozilmasin (repo public).

## 5. Botni ishga tushirish

Bot doimiy ishlaydigan jarayon (polling). Hozircha Mac'da: `python -m src.main`
(`caffeinate -dis python -m src.main` uxlab qolmasligi uchun). Keyinchalik Render/Koyeb/Railway
worker'iga ko'chirsa bo'ladi — baza Neon'da bo'lgani uchun web'ga ta'sir qilmaydi.

## Web'da nima qanday ko'rinadi

| Botda | Web'da |
|---|---|
| `Truck.serial_number` | truck seriyasi (kartochka/ro'yxat/qidiruv) |
| `Truck.model`, `customer` | "Model T1", buyurtmachi |
| `TruckStep` (1–6) | bosqichlar: kutilmoqda → QC kutmoqda → tasdiqlandi / qaytarildi |
| ishchi/QC/admin (`users`) | Ishchilar, QC sahifalari |
| `worker_comment`, `qc_comment` | izohlar, qaytarish sabablari |
| step media | Fayllar va truck sahifasi (rasm Telegram'dan olinadi) |

## Cheklovlar

- Botda **o'lcham, rang, liniya va QC tekshiruv ro'yxati (checklist)** yo'q — web'da bu maydonlar yashiriladi.
- Bot bosqichni qaytarilganda bitta qatorni qayta ishlatadi, shuning uchun "necha marta qaytgan"
  tarixi yo'q — "Ogohlantirishlar"da hozir qaytarilgan trucklar ko'rsatiladi.
- **Bir yuborishda ko'p fayl.** Ishchi bir bosqichga 10 tagacha rasm va 5 tagacha video (va 3 tagacha fayl) yuboradi.
  Fayllar `truck_step_media` jadvalida (`deploy/bot-compat.sql` yaratadi); botning eski `truck_steps.media_*` ustunlarida asosiy fayl turadi.
  QC botda hammasini albom bo'lib ko'radi, web'dagi truck sahifasi va Fayllarda ham hammasi chiqadi.
- Video 4 MB dan katta bo'lsa (Vercel javob limiti) o'rniga rasm-belgi chiqadi. Rasmlarda muammo yo'q.

## Web'dan buyurtma berish va Telegram xabari
Bot rejimida web endi **yozadi ham**: `web.create_truck(...)` SQL funksiyasi botning `create_truck` servisi bilan bir xil
ishni qiladi (truck + 6 ta `pending` bosqich), shuning uchun bot truckni darrov o'z ro'yxatida ko'radi (prioritet/muddat
bo'yicha tartiblab). Model katalogi (`web.model_cards`) — web'ning o'z jadvali; bot jadvallariga tegilmaydi.
Yangi buyurtmada web `BOT_TOKEN` bilan botdagi hamma faol foydalanuvchiga xabar yuboradi (model rasmi bilan).
Cheklov: ishchi botda vazifani ochganda model rasmi hozircha chiqmaydi — rasm faqat «yangi buyurtma» xabarida keladi
(bot kodida `web.model_cards.tg_file_id` dan foydalanib qo'shish mumkin).

## Ko'rsatkichlar qanday hisoblanadi (aniq hisob)
Bot bitta bosqichni rad etilgach qayta ishlatadi va eski rad etish izini o'chiradi. Shuning uchun baza triggeri
(`app/bot_events.sql`) har bir holat o'zgarishini `truck_step_events` jurnaliga yozib boradi (yuborildi / tasdiqlandi / rad etildi).
Barcha ko'rsatkichlar shu jurnaldan hisoblanadi (`web.stage_runs` — har bir yuborish alohida «urinish»):

| Ko'rsatkich | Hisob |
|---|---|
| Sifat darajasi | tasdiqlangan / (tasdiqlangan + qaytarilgan) — QC qarorlari bo'yicha |
| Qaytarishlar | QC rad etgan urinishlar soni (bir truck necha marta qaytgan bo'lsa, shuncha) |
| Tayyor bo'ldi | oxirgi bosqichi tasdiqlangan trucklar soni (davr bo'yicha) |
| O'rtacha bosqich vaqti | bosqich ishchiga kelgan paytdan (oldingi bosqich tasdiqlangan; 1-bosqich — buyurtma yaratilgan) tasdiqlangunicha; qaytarishlar vaqti ham ichida |
| Jamoa natijasi | bosqichdagi barcha tasdiq/qaytarishlar (kim yuborganidan qat'i nazar) |
| Ishchining «Yuborgan ishlari» | faqat o'zi yuborgan urinishlar |
| Muddat | buyurtmada belgilangan haqiqiy muddat; belgilanmagan bo'lsa ko'rsatilmaydi |

O'zgarish foizlari (↑/↓) oldingi shunday davr bilan solishtiriladi; oldingi davrda ma'lumot bo'lmasa ko'rsatilmaydi.
Jurnal yoqilishidan OLDINGI rad etishlar tiklanmaydi (faqat oxirgi holat).

## Production'dan oldin test ma'lumotlarini tozalash
`deploy/reset-data.sh` — faqat adminlar qoladi (ishchilar, QC, trucklar, takliflar, rasm/videolar o'chadi; model katalogi qoladi).
Avval `./reset-data.sh --dry` bilan nimalar o'chishini ko'ring; haqiqiy tozalashdan oldin avtomatik zaxira olinadi va «TOZALASH» yozish so'raladi.

## Telegram chatdagi "axlat"ni tozalash
Pastdagi menyu tugmalari («📋 Vazifalarim», «📤 Ish yuborish», «📜 Tarixim», «📊 Statistika», «🔔 Sozlamalar», «🏠 Asosiy menyu» va h.k.)
bosilganda, bot javobi endi OLDINGI shunday javobning o'rnini oladi — eski ekran avtomatik o'chiriladi, chatda faqat oxirgi
ekran qoladi (`deploy/bot-fixes/nav_cleanup.py`, `NavCleanupMiddleware`). Bildirishnomalar (yangi ish keldi, tasdiqlandi/rad etildi)
va foydalanuvchining o'z yozgan xabarlari (masalan rad etish sababi) tegilmaydi — ular alohida yo'l bilan yuboriladi, tarix
sifatida chatda qolaveradi. Xotira ichida saqlanadi (chat_id -> oxirgi ekran xabar id'si), bot qayta ishga tushsa tozalanadi
(zararsiz — birinchi tugma bosilganda hech narsa o'chirilmaydi, shunchaki qayta hisoblanadi).

