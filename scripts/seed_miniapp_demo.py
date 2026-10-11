"""Mini App ko'rinishini sinash uchun soxta ma'lumot (FAQAT lokal demo bazaga).

    DEMO_DSN=postgresql://postgres@127.0.0.1:5544/truck_demo DEMO_MEDIA=/tmp/baaz_demo_media \\
    .venv/bin/python scripts/seed_miniapp_demo.py

Foydalanuvchilar: 920001-920009 (har bosqichga ishchi, 2 QC, 1 admin). Haqiqiy serverda ISHLATMANG.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

DSN = os.environ.get("DEMO_DSN", "")
MEDIA = Path(os.environ.get("DEMO_MEDIA", "/tmp/baaz_demo_media"))
SRC = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "trucks"
assert "truck_demo" in DSN, "Faqat truck_demo bazasi uchun"

USERS = [  # tg, ism, rol, bosqich
    (920001, "Sardor Karimov", "worker", 1), (920002, "Bobur Aliyev", "worker", 1),
    (920003, "Jasur Toshmatov", "worker", 2), (920004, "Aziz Rahimov", "worker", 3),
    (920005, "Dilshod Yusupov", "worker", 4), (920006, "Otabek Nazarov", "worker", 5),
    (920007, "Rustam Saidov", "worker", 6),
    (920008, "Malika Qodirova", "qc", None), (920009, "Admin Demo", "admin", None),
]
MODELS = ["Baaz Classic", "Baaz Mini", "Baaz Pro", "Baaz Family"]
CUSTOMERS = ["Anvar Ismoilov", "Fresh Food MChJ", "Nilufar Hamidova", "Street Burger", "Coffee Time", None, "Doner King"]
REJECT = ["Payvand choklari notekis, qayta ko'rib chiqing", "Rasm xira, ish ko'rinmayapti. Yaxshiroq yoritib suratga oling",
          "O'lchamlar chizmaga mos kelmayapti"]
PHOTOS = ["trailer-orange.jpg", "trailer-blue.jpg", "trailer-green.jpg", "trailer-cream.jpg"]

# (serial, model, joriy bosqich, shu bosqich holati, muddat (kun, None), muhimlik, mijoz idx)
# holat: pending | in_review | rejected | done (barcha bosqich tayyor)
TRUCKS = [
    ("T1-2026-001", 0, 6, "done", -20, "normal", 0), ("T1-2026-002", 1, 6, "done", -12, "high", 1),
    ("T1-2026-003", 2, 6, "done", -5, "normal", 2),
    ("T1-2026-004", 0, 5, "in_review", 2, "urgent", 3), ("T1-2026-005", 1, 4, "pending", 6, "normal", 4),
    ("T1-2026-006", 2, 4, "rejected", -1, "high", 5), ("T1-2026-007", 3, 3, "in_review", 9, "normal", 6),
    ("T1-2026-008", 0, 3, "pending", 14, "low", 0), ("T1-2026-009", 1, 2, "rejected", 3, "urgent", 1),
    ("T1-2026-010", 2, 2, "pending", None, "normal", 2), ("T1-2026-011", 3, 2, "in_review", 12, "normal", 3),
    ("T1-2026-012", 0, 1, "pending", 20, "normal", 4), ("T1-2026-013", 1, 1, "in_review", 0, "high", 5),
    ("T1-2026-014", 2, 1, "pending", 30, "low", 6),
]


async def main() -> None:
    c = await asyncpg.connect(DSN)
    now = datetime.now(timezone.utc)
    await c.execute("TRUNCATE truck_step_media, truck_step_events, truck_steps, trucks, users RESTART IDENTITY CASCADE")
    uid = {}
    for tg, name, role, step in USERS:
        uid[tg] = await c.fetchval(
            "INSERT INTO users (telegram_id, full_name, phone, role, step_number, is_active, language) "
            "VALUES ($1,$2,$3,$4::user_role,$5,true,'uz') RETURNING id", tg, name, f"+99890{tg % 10_000_000:07d}", role, step)
    workers = {s: [uid[t] for t, _, r, st in USERS if r == "worker" and st == s] for s in range(1, 7)}
    qc = uid[920008]
    try:
        for m in MODELS:
            await c.execute("INSERT INTO web.model_cards (name, description, is_active, created_at) VALUES ($1,'Demo model',true,now()) "
                            "ON CONFLICT (name) DO NOTHING", m)
    except asyncpg.PostgresError:
        pass

    for n, (serial, mi, cur, state, dl, prio, ci) in enumerate(TRUCKS):
        created = now - timedelta(days=22 - n)
        done = state == "done"
        tid = await c.fetchval(
            "INSERT INTO trucks (serial_number, model, current_step, status, completed_at, created_at, customer, deadline, priority, source) "
            "VALUES ($1,$2,$3,$4::truck_status,$5,$6,$7,$8,$9::truck_priority,'admin') RETURNING id",
            serial, MODELS[mi], cur, "completed" if done else "in_progress", (now - timedelta(days=2)) if done else None, created,
            CUSTOMERS[ci], (now + timedelta(days=dl, hours=3)) if dl is not None else None, prio)
        t = created
        for s in range(1, 7):
            w = workers[s][(n + s) % len(workers[s])]
            if s > cur:
                await c.execute("INSERT INTO truck_steps (truck_id, step_number, status, created_at) VALUES ($1,$2,'pending',$3)", tid, s, created)
                continue
            final = "approved" if (s < cur or done) else {"pending": "pending", "in_review": "in_review", "rejected": "rejected"}[state]
            start = t + timedelta(hours=2)
            sub = start + timedelta(hours=6 + (n % 5))
            rev = sub + timedelta(hours=1 + (n % 3))
            sid = await c.fetchval(
                "INSERT INTO truck_steps (truck_id, step_number, status, worker_id, started_at, created_at) VALUES ($1,$2,'pending',$3,$4,$5) RETURNING id",
                tid, s, w if final != "pending" else None, start, created)
            if final == "pending":
                continue
            photos = [PHOTOS[(n + s + k) % 4] for k in range(1 + (n + s) % 3)]
            rels = []
            for k, ph in enumerate(photos):
                rel = f"trucks/{tid}/step_{s}/{k}_{ph}"
                (MEDIA / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(SRC / ph, MEDIA / rel)
                rels.append(rel)
                await c.execute("INSERT INTO truck_step_media (step_id, media_type, local_path, added_by_id, draft, size_bytes, created_at) "
                                "VALUES ($1,'photo',$2,$3,false,$4,$5)", sid, rel, w, (SRC / ph).stat().st_size, sub)
            await c.execute("UPDATE truck_steps SET media_type='photo', media_local_path=$2, worker_comment=$3, submitted_at=$4 WHERE id=$1",
                            sid, rels[0], "Ish tugadi, rasmlarni yubordim" if (n + s) % 2 else None, sub)
            await c.execute("UPDATE truck_steps SET status='in_review' WHERE id=$1", sid)
            if final == "approved":
                await c.execute("UPDATE truck_steps SET qc_id=$2, reviewed_at=$3 WHERE id=$1", sid, qc, rev)
                await c.execute("UPDATE truck_steps SET status='approved' WHERE id=$1", sid)
                t = rev
            elif final == "rejected":
                await c.execute("UPDATE truck_steps SET qc_id=$2, reviewed_at=$3, qc_comment=$4 WHERE id=$1", sid, qc, rev, REJECT[n % 3])
                await c.execute("UPDATE truck_steps SET status='rejected' WHERE id=$1", sid)
    # Hozirgi ishlar "yaqinda" bo'lsin: kutish soatlarda (kunlarda emas). Tugaganlar o'z holicha qoladi.
    for n, (serial, *_rest) in enumerate(TRUCKS):
        if _rest[2] == "done":
            continue
        tid = await c.fetchval("SELECT id FROM trucks WHERE serial_number=$1", serial)
        delta = await c.fetchval(
            "SELECT max(coalesce(reviewed_at, submitted_at, started_at)) - ($2::timestamptz - make_interval(hours => $3)) "
            "FROM truck_steps WHERE truck_id=$1", tid, now, 1 + (n * 7) % 23)
        await c.execute("UPDATE truck_steps SET started_at=started_at-$2::interval, submitted_at=submitted_at-$2::interval, reviewed_at=reviewed_at-$2::interval, created_at=created_at-$2::interval WHERE truck_id=$1", tid, delta)
        await c.execute("UPDATE truck_step_media SET created_at=created_at-$2::interval WHERE step_id IN (SELECT id FROM truck_steps WHERE truck_id=$1)", tid, delta)
        await c.execute("UPDATE truck_step_events SET created_at=created_at-$2::interval WHERE truck_id=$1", tid, delta)
        await c.execute("UPDATE trucks SET created_at=(SELECT min(created_at) FROM truck_steps WHERE truck_id=$1) WHERE id=$1", tid)
    print("tayyor:", await c.fetchval("select count(*) from trucks"), "truck,", await c.fetchval("select count(*) from truck_steps"), "bosqich")
    await c.close()


asyncio.run(main())
