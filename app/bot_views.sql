-- Baaz web  <->  truck-factory-bot  moslashuv qatlami (FAQAT O'QISH).
--
-- Bot o'z jadvallarini `public` sxemasida yuritadi (users, trucks, truck_steps).
-- Web esa boshqa shakldagi jadvallarni kutadi (products, stage_runs, media, ...).
-- Shuning uchun `web` sxemasida bot jadvallarini web kutgan shaklga o'giradigan
-- VIEW'lar yaratamiz. Web `schema_translate_map` orqali shu sxemadan o'qiydi;
-- bot jadvallariga hech qachon yozmaydi.
--
-- Vaqtlar: web SQLite'dagi kabi "naive UTC" kutadi -> `AT TIME ZONE 'UTC'`.
-- Skript idempotent: qayta ishga tushirsa bo'ladi (botga migratsiya kirganda ham).

CREATE SCHEMA IF NOT EXISTS web;

-- 6 ta ishlab chiqarish bosqichi (botdagi src/utils/constants.py bilan bir xil)
CREATE OR REPLACE VIEW web.stages AS
SELECT s.n::int                       AS id,
       s.n::int                       AS order_no,
       s.name::varchar(255)           AS name,
       NULL::text                     AS description,
       true                           AS is_active,
       (now() AT TIME ZONE 'UTC')     AS created_at
FROM (VALUES (1, 'Karkas'),
             (2, 'Kuzov o''rnatish'),
             (3, 'Ichki qoplama'),
             (4, 'Bo''yash'),
             (5, 'Eshik-deraza'),
             (6, 'Yig''ish')) AS s(n, name);

-- Ro'yxatdan o'tishda yuborilgan selfi ustunlari (bot yamoqlari shularni ishlatadi)
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS photo_file_id varchar(255);
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS photo_path varchar(512);

CREATE OR REPLACE VIEW web.users AS
SELECT u.id,
       u.telegram_id,
       -- Bir xil ismli ishchilar web'da adashtirilmasin (rasm, "mas'ul ishchi"): ismga telefonning oxirgi 4 raqami
       -- (telefon yo'q bo'lsa — #id) qo'shiladi. Ism yagona bo'lsa — o'zgarishsiz.
       (CASE WHEN count(*) OVER (PARTITION BY lower(btrim(u.full_name))) > 1
             THEN btrim(u.full_name) || ' (…' ||
                  CASE WHEN u.p4 <> '' AND count(*) OVER (PARTITION BY lower(btrim(u.full_name)), u.p4) = 1
                       THEN u.p4 ELSE '#' || u.id::text END || ')'
             ELSE u.full_name END)::varchar(255)  AS full_name,
       u.username,
       u.role::text                              AS role,
       u.step_number                             AS stage_id,
       u.is_active,
       (u.created_at AT TIME ZONE 'UTC')         AS created_at,
       u.photo_file_id,
       u.photo_path
FROM (SELECT x.*, right(regexp_replace(COALESCE(x.phone, ''), '\D', '', 'g'), 4) AS p4 FROM public.users x) u;

-- Truck -> "mahsulot". Holat botdagi joriy bosqich holatidan chiqariladi.
CREATE OR REPLACE VIEW web.products AS
SELECT t.id,
       t.serial_number::varchar(32)                                AS code,
       t.serial_number::varchar(255)                               AS name,
       COALESCE(NULLIF(t.model, ''), t.serial_number)::varchar(64) AS model,
       NULL::int                                                   AS size_m,
       NULL::varchar(64)                                           AS color,
       NULL::varchar(64)                                           AS line,
       t.customer                                                  AS note,
       (CASE WHEN t.status::text = 'completed' THEN 'done'
             WHEN cs.status::text = 'in_review' THEN 'qc_pending'
             WHEN cs.status::text = 'rejected'  THEN 'returned'
             ELSE 'in_production' END)::varchar(32)                AS status,
       t.current_step                                              AS current_stage_order,
       (SELECT cu.id FROM public.users cu
         WHERE cu.telegram_id = t.created_by LIMIT 1)              AS created_by_id,
       (t.created_at AT TIME ZONE 'UTC')                           AS created_at,
       (t.completed_at AT TIME ZONE 'UTC')                         AS finished_at,
       (t.deadline AT TIME ZONE 'UTC')                             AS deadline
FROM public.trucks t
LEFT JOIN public.truck_steps cs
       ON cs.truck_id = t.id AND cs.step_number = t.current_step;

-- Ustun turlari o'zgargani uchun (CREATE OR REPLACE ruxsat bermaydi) eski ko'rinishlar o'chirib qayta yaratiladi.
DROP VIEW IF EXISTS web.audit_logs, web.media, web.stage_runs;

-- Bosqich urinishlari. Botda bitta `truck_steps` qatori qayta ishlatiladi, shuning uchun urinishlar tarixi
-- `truck_step_events` jurnalidan (app/bot_events.sql) olinadi: har «yuborildi» voqeasi — bitta urinish,
-- uning natijasi (tasdiqlandi/rad etildi) keyingi qaror voqeasidan. Hali yuborilmagan (ishlanayotgan) bosqich
-- alohida `in_progress` qator bo'ladi. id: urinishlar 1_000_000 + voqea id, ishlanayotganlar — truck_steps.id.
--
-- started_at = ish shu bosqichga kelgan payt: oldingi bosqich tasdiqlangan vaqt (1-bosqichda — buyurtma yaratilgan payt).
-- (Botdagi started_at — ishchi «Ish yuborish»ni bosgan payt, ya'ni ish tugagach; u bilan o'lchasak faqat QC kutish vaqti chiqadi.)
-- Shu sababli tasdiqlangan urinishning (decided_at - started_at) — qaytarishlar bilan birga BUTUN bosqich davomiyligi.
CREATE OR REPLACE VIEW web.stage_runs AS
SELECT (1000000 + s.id)::int                 AS id,
       s.truck_id                            AS product_id,
       s.step_number                         AS stage_id,
       s.step_number                         AS stage_order,
       s.attempt_no::int                     AS attempt_no,
       s.worker_id,
       d.qc_id,
       (CASE d.event WHEN 'approved' THEN 'approved'
                     WHEN 'rejected' THEN 'returned'
                     ELSE 'qc_pending' END)::varchar(32) AS status,
       s.comment                             AS worker_comment,
       CASE WHEN d.event = 'rejected' THEN d.comment END AS qc_comment,
       (COALESCE(CASE WHEN s.step_number = 1 THEN t0.created_at ELSE prev.reviewed_at END,
                 ts.started_at, s.created_at) AT TIME ZONE 'UTC') AS started_at,
       (s.created_at AT TIME ZONE 'UTC')     AS submitted_at,
       (d.created_at AT TIME ZONE 'UTC')     AS decided_at
FROM (SELECT e.*, row_number() OVER (PARTITION BY e.step_id ORDER BY e.id) AS attempt_no
        FROM public.truck_step_events e WHERE e.event = 'submitted') s
JOIN public.truck_steps ts ON ts.id = s.step_id
JOIN public.trucks t0 ON t0.id = s.truck_id
LEFT JOIN public.truck_steps prev ON prev.truck_id = s.truck_id AND prev.step_number = s.step_number - 1
LEFT JOIN LATERAL (
    SELECT d0.event, d0.qc_id, d0.comment, d0.created_at
    FROM public.truck_step_events d0
    WHERE d0.step_id = s.step_id AND d0.id > s.id AND d0.event IN ('approved', 'rejected')
      AND NOT EXISTS (SELECT 1 FROM public.truck_step_events n
                       WHERE n.step_id = s.step_id AND n.event = 'submitted' AND n.id > s.id AND n.id < d0.id)
    ORDER BY d0.id LIMIT 1
) d ON true
UNION ALL
SELECT ts.id,
       ts.truck_id, ts.step_number, ts.step_number,
       ((SELECT count(*) FROM public.truck_step_events e WHERE e.step_id = ts.id AND e.event = 'submitted') + 1)::int,
       ts.worker_id, NULL::int,
       'in_progress'::varchar(32),
       NULL::text, NULL::text,
       (COALESCE(CASE WHEN ts.step_number = 1 THEN t0.created_at ELSE prev.reviewed_at END,
                 ts.started_at, ts.created_at) AT TIME ZONE 'UTC'),
       NULL::timestamp, NULL::timestamp
FROM public.truck_steps ts
JOIN public.trucks t0 ON t0.id = ts.truck_id
LEFT JOIN public.truck_steps prev ON prev.truck_id = ts.truck_id AND prev.step_number = ts.step_number - 1
WHERE ts.started_at IS NOT NULL
  AND ( ts.status::text = 'pending'
        OR (ts.status::text = 'rejected'
            AND ts.started_at > COALESCE((SELECT max(e.created_at) FROM public.truck_step_events e
                                           WHERE e.step_id = ts.id AND e.event = 'rejected'), '-infinity')) );

-- Bir bosqichga bir nechta rasm/video: `truck_step_media` (bot yozadi; deploy/bot-compat.sql ham shuni yaratadi).
-- Hujjatlar (document) web'da ko'rsatilmaydi.
CREATE TABLE IF NOT EXISTS public.truck_step_media (
    id          serial PRIMARY KEY,
    step_id     integer NOT NULL REFERENCES public.truck_steps(id) ON DELETE CASCADE,
    media_type  varchar(16) NOT NULL,
    file_id     varchar(512) NOT NULL,
    local_path  varchar(512),
    added_by_id integer REFERENCES public.users(id) ON DELETE SET NULL,
    draft       boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_truck_step_media_step ON public.truck_step_media (step_id);

-- id: yangi fayllar 1_000_000_000 + id (eski bitta-media qatorlari id'si bilan to'qnashmasligi uchun).
-- Eski (jadvalgacha yuborilgan) ishlar uchun truck_steps.media_* ishlatiladi.
CREATE OR REPLACE VIEW web.media AS
SELECT ts.id,
       COALESCE((SELECT 1000000 + max(e.id) FROM public.truck_step_events e
                  WHERE e.step_id = ts.id AND e.event = 'submitted'), ts.id) AS stage_run_id,
       ts.truck_id                                       AS product_id,
       (CASE WHEN ts.media_type::text = 'video' THEN 'video' ELSE 'photo' END)::varchar(16) AS type,
       COALESCE(ts.media_local_path, '')::varchar(512)   AS file_path,
       ts.media_file_id::varchar(512)                    AS telegram_file_id,
       ts.worker_id                                      AS uploaded_by_id,
       (COALESCE(ts.submitted_at, ts.updated_at) AT TIME ZONE 'UTC') AS created_at
FROM public.truck_steps ts
WHERE ts.media_file_id IS NOT NULL
  AND ts.media_type::text IN ('photo', 'video')
  AND NOT EXISTS (SELECT 1 FROM public.truck_step_media m WHERE m.step_id = ts.id AND NOT m.draft)
UNION ALL
SELECT (1000000000 + m.id)::int                          AS id,
       COALESCE((SELECT 1000000 + max(e.id) FROM public.truck_step_events e
                  WHERE e.step_id = m.step_id AND e.event = 'submitted'), m.step_id) AS stage_run_id,
       ts.truck_id                                       AS product_id,
       (CASE WHEN m.media_type = 'video' THEN 'video' ELSE 'photo' END)::varchar(16) AS type,
       COALESCE(m.local_path, '')::varchar(512)          AS file_path,
       m.file_id::varchar(512)                           AS telegram_file_id,
       COALESCE(m.added_by_id, ts.worker_id)             AS uploaded_by_id,
       (COALESCE(ts.submitted_at, m.created_at) AT TIME ZONE 'UTC') AS created_at
FROM public.truck_step_media m
JOIN public.truck_steps ts ON ts.id = m.step_id
WHERE NOT m.draft
  AND m.media_type IN ('photo', 'video');

-- Faoliyat lentasi: `truck_step_events` jurnalidan (har yuborish, tasdiq va rad etish alohida qator) + truck yaratilishi/tugashi.
CREATE OR REPLACE VIEW web.audit_logs AS
SELECT (1000000 + e.id)::int                         AS id,
       COALESCE(e.qc_id, e.worker_id)                AS actor_id,
       COALESCE(qu.full_name, wu.full_name)          AS actor_name,
       (CASE e.event WHEN 'submitted' THEN 'submitted_to_qc'
                     WHEN 'approved'  THEN 'qc_approved'
                     ELSE 'qc_returned' END)::varchar(64) AS action,
       e.truck_id                                    AS product_id,
       NULL::int                                     AS stage_run_id,
       ('Model ' || COALESCE(NULLIF(t.model, ''), t.serial_number) || ' — '
          || e.step_number || '-bosqich'
          || CASE WHEN e.event = 'rejected' AND e.comment IS NOT NULL THEN ': ' || e.comment ELSE '' END)::text AS details,
       (e.created_at AT TIME ZONE 'UTC')             AS created_at
FROM public.truck_step_events e
JOIN public.trucks t ON t.id = e.truck_id
LEFT JOIN public.users wu ON wu.id = e.worker_id
LEFT JOIN public.users qu ON qu.id = e.qc_id
UNION ALL
SELECT t.id * 10 + 3,
       cu.id,
       COALESCE(cu.full_name, CASE WHEN t.created_by IS NULL THEN 'Web panel' END),
       'product_created'::varchar(64),
       t.id,
       NULL::int,
       ('Model ' || COALESCE(NULLIF(t.model, ''), t.serial_number))::text,
       (t.created_at AT TIME ZONE 'UTC')
FROM public.trucks t
LEFT JOIN public.users cu ON cu.telegram_id = t.created_by
UNION ALL
SELECT t.id * 10 + 4,
       NULL::int,
       NULL::text,
       'product_finished'::varchar(64),
       t.id,
       NULL::int,
       ('Model ' || COALESCE(NULLIF(t.model, ''), t.serial_number))::text,
       (t.completed_at AT TIME ZONE 'UTC')
FROM public.trucks t
WHERE t.completed_at IS NOT NULL;

-- Botda QC tekshiruv punktlari (checklist) yo'q -> bo'sh
CREATE OR REPLACE VIEW web.stage_check_items AS
SELECT NULL::int AS id, NULL::int AS stage_id, NULL::int AS order_no, NULL::varchar(500) AS text,
       NULL::boolean AS is_active, NULL::timestamp AS created_at
WHERE false;

CREATE OR REPLACE VIEW web.stage_run_checks AS
SELECT NULL::int AS id, NULL::int AS stage_run_id, NULL::int AS check_item_id, NULL::boolean AS ok,
       NULL::varchar(500) AS note, NULL::int AS checked_by_id, NULL::timestamp AS created_at
WHERE false;

-- Modellar ro'yxati: trucklarda uchraydigan model nomlaridan
CREATE OR REPLACE VIEW web.truck_models AS
SELECT (dense_rank() OVER (ORDER BY m.model))::int AS id,
       m.model::varchar(64)                        AS name,
       true                                        AS is_active,
       (now() AT TIME ZONE 'UTC')                  AS created_at
FROM (SELECT DISTINCT model FROM public.trucks WHERE model IS NOT NULL AND model <> '') m;

-- Web'dan truck yaratish: botning `create_truck` servisi bilan bir xil ish
-- (truck + 6 ta 'pending' bosqich). Bot shu truckni o'z ro'yxatida darrov ko'radi.
-- Seriya takrorlansa unique_violation ko'tariladi.
CREATE OR REPLACE FUNCTION web.create_truck(
    p_serial   text,
    p_model    text,
    p_customer text,
    p_priority text,
    p_deadline timestamptz
) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    tid integer;
BEGIN
    INSERT INTO public.trucks
           (serial_number, model, customer, deadline, priority, current_step, status, source)
    VALUES (p_serial, NULLIF(p_model, ''), NULLIF(p_customer, ''), p_deadline,
            p_priority::public.truck_priority, 1,
            'in_progress'::public.truck_status, 'admin'::public.truck_source)
    RETURNING id INTO tid;

    INSERT INTO public.truck_steps (truck_id, step_number, status)
    SELECT tid, n, 'pending'::public.step_status FROM generate_series(1, 6) AS n;

    RETURN tid;
END;
$$;
