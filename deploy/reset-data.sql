-- Production'dan oldin test ma'lumotlarini tozalash: FAQAT ADMINLAR qoladi.
-- O'chadi: hamma truck, bosqichlar, voqealar jurnali, rasm/video yozuvlari, takliflar, ishchilar va QC.
-- Qoladi: adminlar, model katalogi (web.model_cards) va uning rasmlari.
BEGIN;

TRUNCATE trucks, truck_steps, truck_step_events, truck_step_media, invites RESTART IDENTITY;
DELETE FROM users WHERE role::text <> 'admin';

COMMIT;
