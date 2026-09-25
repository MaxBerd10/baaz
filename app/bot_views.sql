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
       u.full_name,
       u.username,
       u.role::text                              AS role,
       u.step_number                             AS stage_id,
       u.is_active,
       (u.created_at AT TIME ZONE 'UTC')         AS created_at,
       u.photo_file_id,
       u.photo_path
FROM public.users u;

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

-- truck_steps -> "bosqich sikli" (bot bitta qatorni qayta ishlatadi, urinishlar tarixi yo'q)
CREATE OR REPLACE VIEW web.stage_runs AS
SELECT ts.id,
       ts.truck_id                           AS product_id,
       ts.step_number                        AS stage_id,
       ts.step_number                        AS stage_order,
       1                                     AS attempt_no,
       ts.worker_id,
       ts.qc_id,
       (CASE ts.status::text
             WHEN 'in_review' THEN 'qc_pending'
             WHEN 'approved'  THEN 'approved'
             WHEN 'rejected'  THEN 'returned'
             ELSE 'in_progress' END)::varchar(32) AS status,
       ts.worker_comment,
       ts.qc_comment,
       (COALESCE(ts.started_at, ts.submitted_at, ts.created_at) AT TIME ZONE 'UTC') AS started_at,
       (ts.submitted_at AT TIME ZONE 'UTC')  AS submitted_at,
       (ts.reviewed_at  AT TIME ZONE 'UTC')  AS decided_at
FROM public.truck_steps ts
WHERE ts.status::text <> 'pending' OR ts.started_at IS NOT NULL;

-- Bot bitta bosqichga bitta media saqlaydi. Hujjatlar (document) web'da ko'rsatilmaydi.
CREATE OR REPLACE VIEW web.media AS
SELECT ts.id,
       ts.id                                             AS stage_run_id,
       ts.truck_id                                       AS product_id,
       (CASE WHEN ts.media_type::text = 'video' THEN 'video' ELSE 'photo' END)::varchar(16) AS type,
       COALESCE(ts.media_local_path, '')::varchar(512)   AS file_path,
       ts.media_file_id::varchar(512)                    AS telegram_file_id,
       ts.worker_id                                      AS uploaded_by_id,
       (COALESCE(ts.submitted_at, ts.updated_at) AT TIME ZONE 'UTC') AS created_at
FROM public.truck_steps ts
WHERE ts.media_file_id IS NOT NULL
  AND ts.media_type::text IN ('photo', 'video');

-- Faoliyat lentasi: botning audit_logs'iga bog'lanmay, aniq voqealardan yig'iladi.
CREATE OR REPLACE VIEW web.audit_logs AS
SELECT ts.id * 10 + 1                                AS id,
       ts.worker_id                                  AS actor_id,
       w.full_name                                   AS actor_name,
       'submitted_to_qc'::varchar(64)                AS action,
       ts.truck_id                                   AS product_id,
       ts.id                                         AS stage_run_id,
       ('Model ' || COALESCE(NULLIF(t.model, ''), t.serial_number) || ' — '
          || ts.step_number || '-bosqich')::text     AS details,
       (ts.submitted_at AT TIME ZONE 'UTC')          AS created_at
FROM public.truck_steps ts
JOIN public.trucks t ON t.id = ts.truck_id
LEFT JOIN public.users w ON w.id = ts.worker_id
WHERE ts.submitted_at IS NOT NULL
UNION ALL
SELECT ts.id * 10 + 2,
       ts.qc_id,
       q.full_name,
       (CASE ts.status::text WHEN 'approved' THEN 'qc_approved' ELSE 'qc_returned' END)::varchar(64),
       ts.truck_id,
       ts.id,
       ('Model ' || COALESCE(NULLIF(t.model, ''), t.serial_number) || ' — '
          || ts.step_number || '-bosqich'
          || COALESCE(': ' || ts.qc_comment, ''))::text,
       (ts.reviewed_at AT TIME ZONE 'UTC')
FROM public.truck_steps ts
JOIN public.trucks t ON t.id = ts.truck_id
LEFT JOIN public.users q ON q.id = ts.qc_id
WHERE ts.reviewed_at IS NOT NULL AND ts.status::text IN ('approved', 'rejected')
UNION ALL
SELECT t.id * 10 + 3,
       cu.id,
       cu.full_name,
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
