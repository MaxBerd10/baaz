-- Botning alembic migratsiyalari modellardan orqada qolgan: `users.language` ustuni va
-- `notification_settings` jadvali hech bir migratsiyada yo'q (bot shularsiz yiqiladi).
-- Bu skript ularni IDEMPOTENT tarzda qo'shadi.
--
-- ⚠️ Bot repo'sida shu narsalar uchun haqiqiy migratsiya yozilgach, bu faylni va
--    docker-compose.yml dagi `psql ... /compat.sql` qadamini olib tashlang
--    (aks holda alembic "column already exists" deb yiqilishi mumkin).
ALTER TABLE users ADD COLUMN IF NOT EXISTS language varchar(10) NOT NULL DEFAULT 'uz';

CREATE TABLE IF NOT EXISTS notification_settings (
    id           serial PRIMARY KEY,
    user_id      integer NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    on_new_task  boolean NOT NULL DEFAULT true,
    on_approved  boolean NOT NULL DEFAULT true,
    on_rejected  boolean NOT NULL DEFAULT true,
    on_next_step boolean NOT NULL DEFAULT true,
    daily_report boolean NOT NULL DEFAULT false
);

-- Ro'yxatdan o'tishda yuborilgan selfi (yuz rasmi): Telegram file_id + serverdagi nusxa yo'li
ALTER TABLE users ADD COLUMN IF NOT EXISTS photo_file_id varchar(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS photo_path varchar(512);
