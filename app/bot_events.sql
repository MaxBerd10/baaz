-- Bosqich voqealari jurnali: bot bitta `truck_steps` qatorini qayta ishlatadi (rad etilgach ishchi qayta yuborsa,
-- eski rad etish izi yo'qoladi). Shu sababli statistikada "necha marta qaytarilgan" aniq bo'lmasdi.
-- Bu jurnal har bir holat o'zgarishini (yuborildi / tasdiqlandi / rad etildi) botga tegmasdan, baza triggeri
-- orqali yozib boradi. Web ko'rsatkichlari (sifat darajasi, qaytarishlar, ishchi natijasi, bosqich vaqti) shundan hisoblanadi.
--
-- Skript IDEMPOTENT: `deploy/bot-compat.sql` bilan birga (migrate) va web ishga tushganda (app.botdb) bajariladi.

CREATE TABLE IF NOT EXISTS truck_step_events (
    id          serial PRIMARY KEY,
    step_id     integer NOT NULL REFERENCES truck_steps(id) ON DELETE CASCADE,
    truck_id    integer NOT NULL,
    step_number integer NOT NULL,
    event       varchar(16) NOT NULL,          -- submitted | approved | rejected
    worker_id   integer,                       -- ishni yuborgan ishchi
    qc_id       integer,                       -- qaror chiqargan QC (approved / rejected)
    comment     text,                          -- submitted: ishchi izohi; rejected: rad etish sababi
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_truck_step_events_step ON truck_step_events (step_id, id);
CREATE INDEX IF NOT EXISTS ix_truck_step_events_time ON truck_step_events (created_at);

CREATE OR REPLACE FUNCTION log_truck_step_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NEW.status::text = 'in_review' THEN
            INSERT INTO truck_step_events (step_id, truck_id, step_number, event, worker_id, comment, created_at)
            VALUES (NEW.id, NEW.truck_id, NEW.step_number, 'submitted', NEW.worker_id,
                    NEW.worker_comment, COALESCE(NEW.submitted_at, now()));
        ELSIF NEW.status::text = 'approved' THEN
            INSERT INTO truck_step_events (step_id, truck_id, step_number, event, worker_id, qc_id, created_at)
            VALUES (NEW.id, NEW.truck_id, NEW.step_number, 'approved', NEW.worker_id, NEW.qc_id,
                    COALESCE(NEW.reviewed_at, now()));
        ELSIF NEW.status::text = 'rejected' THEN
            INSERT INTO truck_step_events (step_id, truck_id, step_number, event, worker_id, qc_id, comment, created_at)
            VALUES (NEW.id, NEW.truck_id, NEW.step_number, 'rejected', NEW.worker_id, NEW.qc_id,
                    NEW.qc_comment, COALESCE(NEW.reviewed_at, now()));
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_truck_step_events ON truck_steps;
CREATE TRIGGER trg_truck_step_events
    AFTER UPDATE OF status ON truck_steps
    FOR EACH ROW EXECUTE FUNCTION log_truck_step_event();

-- Jurnal yoqilishidan oldingi ishlar uchun eng so'nggi holatdan bir martalik tiklash (jurnal bo'sh bo'lsa).
INSERT INTO truck_step_events (step_id, truck_id, step_number, event, worker_id, comment, created_at)
SELECT ts.id, ts.truck_id, ts.step_number, 'submitted', ts.worker_id, ts.worker_comment, ts.submitted_at
FROM truck_steps ts
WHERE ts.submitted_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM truck_step_events);

INSERT INTO truck_step_events (step_id, truck_id, step_number, event, worker_id, qc_id, comment, created_at)
SELECT ts.id, ts.truck_id, ts.step_number,
       CASE ts.status::text WHEN 'approved' THEN 'approved' ELSE 'rejected' END,
       ts.worker_id, ts.qc_id,
       CASE WHEN ts.status::text = 'rejected' THEN ts.qc_comment END,
       ts.reviewed_at
FROM truck_steps ts
WHERE ts.reviewed_at IS NOT NULL AND ts.status::text IN ('approved', 'rejected')
  AND NOT EXISTS (
      SELECT 1 FROM truck_step_events e
      WHERE e.step_id = ts.id AND e.event IN ('approved', 'rejected')
  )
  AND EXISTS (SELECT 1 FROM truck_step_events e2 WHERE e2.step_id = ts.id AND e2.event = 'submitted');
