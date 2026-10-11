"""Telegram Mini App (ishchi va QC uchun ilova) ning biznes mantiqi.

Botning o'zi bilan BIR XIL qoidalar (bot: src/services/truck_step_service.py, qc_service.py):
  * ishchi faqat o'z bosqichidagi, hozirgi bosqichga yetgan truck vazifalarini ko'radi (pending / rejected);
  * yuborilganda bosqich `in_review` bo'ladi; QC tasdiqlasa keyingi bosqichga o'tadi (oxirgisida truck tayyor),
    rad etsa sabab bilan `rejected` bo'ladi va ishchi qayta yuboradi;
  * holat o'zgarishlarini baza triggeri (`truck_step_events`) jurnalga yozadi — statistika aniq qoladi.
Hammasi `public.*` jadvallarida to'g'ridan-to'g'ri SQL bilan; bir vaqtda ikki kishi bir ishni olmasligi uchun
qator `FOR UPDATE` bilan qulflanadi.
"""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.media_store import MEDIA_ROOT, ensure_root

TOTAL_STEPS = 6
MAX_PHOTOS, MAX_VIDEOS = 10, 5
MAX_PHOTO_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 95 * 1024 * 1024        # Cloudflare (bepul reja) bitta so'rov uchun 100 MB gacha ruxsat beradi
DRAFT_TTL_HOURS = 24


class AppError(Exception):
    """Ilovaga ko'rsatiladigan xato. `code` — frontend tarjima kaliti, `status` — HTTP kodi."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def iso(v):
    if isinstance(v, (dt.datetime, dt.date)):
        if isinstance(v, dt.datetime) and v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        return v.isoformat()
    return v


def clean(row) -> dict:
    return {k: iso(v) for k, v in dict(row).items()}


# --------------------------------------------------------------------------- #
# Foydalanuvchi
# --------------------------------------------------------------------------- #
async def get_user(session: AsyncSession, telegram_id: int) -> dict | None:
    row = (await session.execute(text(
        "SELECT id, telegram_id, full_name, role::text AS role, step_number, language, is_active, "
        "(photo_file_id IS NOT NULL OR photo_path IS NOT NULL) AS has_photo "
        "FROM public.users WHERE telegram_id = :t"), {"t": telegram_id})).mappings().first()
    return dict(row) if row else None


def _need_role(user: dict, *roles: str) -> None:
    if not user["is_active"] or user["role"] not in roles:
        raise AppError("forbidden", 403)


# --------------------------------------------------------------------------- #
# Ro'yxatlar
# --------------------------------------------------------------------------- #
_TASK_SELECT = """
SELECT ts.id AS step_id, ts.step_number, ts.status::text AS status, ts.qc_comment, ts.submitted_at,
       t.id AS truck_id, t.serial_number, t.model, t.customer, t.deadline, t.priority::text AS priority,
       mc.id AS model_id, (mc.image_file IS NOT NULL) AS has_image,
       w.full_name AS worker_name, w.id AS worker_id, (w.photo_file_id IS NOT NULL OR w.photo_path IS NOT NULL) AS worker_photo,
       (SELECT count(*) FROM public.truck_step_media m WHERE m.step_id = ts.id AND NOT m.draft) AS media_count
FROM public.truck_steps ts
JOIN public.trucks t ON t.id = ts.truck_id
LEFT JOIN web.model_cards mc ON mc.name = t.model
LEFT JOIN public.users w ON w.id = ts.worker_id
"""


async def worker_tasks(session: AsyncSession, user: dict) -> list[dict]:
    _need_role(user, "worker")
    if not user["step_number"]:
        return []
    rows = (await session.execute(text(
        _TASK_SELECT + """
        WHERE ts.step_number = :s AND ts.status IN ('pending', 'rejected')
          AND t.status = 'in_progress' AND t.current_step = :s
        ORDER BY t.priority DESC, t.deadline ASC NULLS LAST, t.id DESC LIMIT 100"""),
        {"s": user["step_number"]})).mappings().all()
    return [clean(r) for r in rows]


async def qc_queue(session: AsyncSession, user: dict) -> list[dict]:
    _need_role(user, "qc")
    rows = (await session.execute(text(
        _TASK_SELECT + """
        WHERE ts.status = 'in_review'
        ORDER BY t.priority DESC, t.deadline ASC NULLS LAST, ts.submitted_at ASC NULLS LAST LIMIT 100"""))).mappings().all()
    return [clean(r) for r in rows]


async def history(session: AsyncSession, user: dict) -> list[dict]:
    _need_role(user, "worker", "qc")
    col, statuses = (("ts.worker_id", "('in_review','approved','rejected')") if user["role"] == "worker"
                     else ("ts.qc_id", "('approved','rejected')"))
    rows = (await session.execute(text(
        _TASK_SELECT + f"""
        WHERE {col} = :u AND ts.status IN {statuses}
        ORDER BY COALESCE(ts.reviewed_at, ts.submitted_at) DESC NULLS LAST LIMIT 40"""),
        {"u": user["id"]})).mappings().all()
    return [clean(r) for r in rows]


async def counts(session: AsyncSession, user: dict) -> dict:
    """Bosh ekrandagi sanoqlar."""
    if user["role"] == "worker" and user["step_number"]:
        n = await session.scalar(text(
            "SELECT count(*) FROM public.truck_steps ts JOIN public.trucks t ON t.id = ts.truck_id "
            "WHERE ts.step_number = :s AND ts.status IN ('pending','rejected') "
            "AND t.status = 'in_progress' AND t.current_step = :s"), {"s": user["step_number"]})
        return {"tasks": int(n or 0)}
    if user["role"] == "qc":
        n = await session.scalar(text("SELECT count(*) FROM public.truck_steps WHERE status = 'in_review'"))
        return {"queue": int(n or 0)}
    rows = (await session.execute(text(
        "SELECT (SELECT count(*) FROM public.trucks WHERE status = 'in_progress') AS active, "
        "(SELECT count(*) FROM public.trucks WHERE status = 'completed') AS done, "
        "(SELECT count(*) FROM public.truck_steps WHERE status = 'in_review') AS review, "
        "(SELECT count(*) FROM public.truck_steps WHERE status = 'rejected') AS returned"))).mappings().first()
    return dict(rows)


# --------------------------------------------------------------------------- #
# Bitta vazifa / ish
# --------------------------------------------------------------------------- #
async def _step_row(session: AsyncSession, step_id: int, *, lock: bool = False) -> dict:
    sql = _TASK_SELECT.replace("SELECT ts.id AS step_id,", "SELECT ts.id AS step_id, t.status::text AS truck_status, t.current_step AS truck_step, "
                               "mc.description AS model_desc, ts.worker_comment, ts.media_type::text AS media_type,")
    sql += " WHERE ts.id = :i" + (" FOR UPDATE OF ts, t" if lock else "")
    row = (await session.execute(text(sql), {"i": step_id})).mappings().first()
    if row is None:
        raise AppError("not_found", 404)
    return dict(row)


def _can_see(user: dict, row: dict) -> bool:
    if user["role"] in ("qc", "admin"):
        return True
    return user["role"] == "worker" and (row["worker_id"] == user["id"] or row["step_number"] == user["step_number"])


async def media_list(session: AsyncSession, step_id: int, *, drafts_for: int | None = None) -> list[dict]:
    """Ishga biriktirilgan fayllar. drafts_for=user_id bo'lsa — shu ishchining hali yuborilmagan (qoralama) fayllari."""
    if drafts_for is not None:
        rows = (await session.execute(text(
            "SELECT id, media_type AS kind, size_bytes FROM public.truck_step_media "
            "WHERE step_id = :s AND draft AND added_by_id = :u ORDER BY id"), {"s": step_id, "u": drafts_for})).mappings().all()
        return [{"id": f"m{r['id']}", "kind": r["kind"], "size": r["size_bytes"]} for r in rows]
    rows = (await session.execute(text(
        "SELECT id, media_type AS kind, size_bytes FROM public.truck_step_media "
        "WHERE step_id = :s AND NOT draft AND media_type IN ('photo','video') ORDER BY id"), {"s": step_id})).mappings().all()
    out = [{"id": f"m{r['id']}", "kind": r["kind"], "size": r["size_bytes"]} for r in rows]
    if not out:  # botning eski bitta-media yozuvi
        legacy = (await session.execute(text(
            "SELECT media_type::text AS kind FROM public.truck_steps WHERE id = :s "
            "AND (media_file_id IS NOT NULL OR media_local_path IS NOT NULL) AND media_type::text IN ('photo','video')"),
            {"s": step_id})).first()
        if legacy:
            out = [{"id": f"s{step_id}", "kind": legacy[0], "size": None}]
    return out


async def step_detail(session: AsyncSession, user: dict, step_id: int) -> dict:
    row = await _step_row(session, step_id)
    if not _can_see(user, row):
        raise AppError("forbidden", 403)
    d = clean(row)
    d["media"] = await media_list(session, step_id)
    d["drafts"] = await media_list(session, step_id, drafts_for=user["id"]) if user["role"] == "worker" else []
    d["can_work"] = (user["role"] == "worker" and user["is_active"] and row["step_number"] == user["step_number"]
                     and row["status"] in ("pending", "rejected") and row["truck_status"] == "in_progress"
                     and row["truck_step"] == row["step_number"])
    d["can_review"] = user["role"] == "qc" and user["is_active"] and row["status"] == "in_review"
    d["limits"] = {"photos": MAX_PHOTOS, "videos": MAX_VIDEOS}
    return d


# --------------------------------------------------------------------------- #
# Ishchi: fayl yuklash (qoralama) va yuborish
# --------------------------------------------------------------------------- #
def sniff_media(head: bytes) -> tuple[str, str] | None:
    """Fayl boshidan turini aniqlaydi: ('photo'|'video', kengaytma). Noma'lum bo'lsa None."""
    if head[:3] == b"\xff\xd8\xff":
        return "photo", "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "photo", "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "photo", "webp"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
            return "photo", "heic"
        return "video", "mov" if brand == b"qt  " else "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video", "webm"
    return None


async def _work_step(session: AsyncSession, user: dict, step_id: int, *, lock: bool = False) -> dict:
    _need_role(user, "worker")
    row = await _step_row(session, step_id, lock=lock)
    if not (row["step_number"] == user["step_number"] and row["status"] in ("pending", "rejected")
            and row["truck_status"] == "in_progress" and row["truck_step"] == row["step_number"]):
        raise AppError("not_available", 409)
    return row


async def prepare_upload(session: AsyncSession, user: dict, step_id: int, kind: str) -> dict:
    """Yuklashdan oldingi tekshiruv. Chegara to'lgan bo'lsa AppError. Eski qoralamalarni tozalaydi."""
    row = await _work_step(session, user, step_id)
    stale = (await session.execute(text(
        "DELETE FROM public.truck_step_media WHERE draft AND created_at < now() - make_interval(hours => :h) "
        "RETURNING local_path"), {"h": DRAFT_TTL_HOURS})).all()
    for (p,) in stale:
        _unlink(p)
    cnt = {k: int(n) for k, n in (await session.execute(text(
        "SELECT media_type, count(*) FROM public.truck_step_media WHERE draft AND step_id = :s AND added_by_id = :u "
        "GROUP BY 1"), {"s": step_id, "u": user["id"]})).all()}
    if kind == "photo" and cnt.get("photo", 0) >= MAX_PHOTOS:
        raise AppError("limit_photos", 409)
    if kind == "video" and cnt.get("video", 0) >= MAX_VIDEOS:
        raise AppError("limit_videos", 409)
    if not cnt:  # yangi urinish boshlandi — «ishlanmoqda» holati
        await session.execute(text(
            "UPDATE public.truck_steps SET worker_id = :u, started_at = now(), updated_at = now() WHERE id = :s"),
            {"u": user["id"], "s": step_id})
    return {"truck_id": row["truck_id"], "step_number": row["step_number"]}


async def register_upload(session: AsyncSession, user: dict, step_id: int, kind: str, rel_path: str, size: int) -> dict:
    rid = (await session.execute(text(
        "INSERT INTO public.truck_step_media (step_id, media_type, file_id, local_path, size_bytes, added_by_id, draft) "
        "VALUES (:s, :k, NULL, :p, :z, :u, true) RETURNING id"),
        {"s": step_id, "k": kind, "p": rel_path, "z": size, "u": user["id"]})).scalar()
    return {"id": f"m{rid}", "kind": kind, "size": size}


async def delete_draft(session: AsyncSession, user: dict, step_id: int, media_id: str) -> None:
    _need_role(user, "worker")
    if not media_id.startswith("m") or not media_id[1:].isdigit():
        raise AppError("not_found", 404)
    row = (await session.execute(text(
        "DELETE FROM public.truck_step_media WHERE id = :i AND step_id = :s AND added_by_id = :u AND draft "
        "RETURNING local_path"), {"i": int(media_id[1:]), "s": step_id, "u": user["id"]})).first()
    if row is None:
        raise AppError("not_found", 404)
    _unlink(row[0])


def _unlink(rel: str | None) -> None:
    if not rel:
        return
    try:
        (MEDIA_ROOT / rel).unlink(missing_ok=True)
    except OSError:
        pass


def new_media_path(truck_id: int, step_number: int, ext: str) -> tuple[str, Path]:
    ensure_root()
    rel = f"trucks/{truck_id}/step_{step_number}/{uuid.uuid4().hex}.{ext}"
    full = MEDIA_ROOT / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    return rel, full


async def submit(session: AsyncSession, user: dict, step_id: int, comment: str | None) -> dict:
    """Qoralama fayllarni yakunlab, ishni QC ga yuboradi."""
    row = await _work_step(session, user, step_id, lock=True)
    drafts = (await session.execute(text(
        "SELECT id, media_type, local_path FROM public.truck_step_media "
        "WHERE draft AND step_id = :s AND added_by_id = :u ORDER BY id"), {"s": step_id, "u": user["id"]})).mappings().all()
    if not drafts:
        raise AppError("no_media", 422)
    primary = next((d for d in drafts if d["media_type"] == "photo"), drafts[0])
    # avvalgi (rad etilgan) urinishning fayllari almashtiriladi
    old = (await session.execute(text(
        "DELETE FROM public.truck_step_media WHERE step_id = :s AND NOT draft RETURNING local_path"), {"s": step_id})).all()
    for (p,) in old:
        _unlink(p)
    await session.execute(text(
        "UPDATE public.truck_step_media SET draft = false WHERE draft AND step_id = :s AND added_by_id = :u"),
        {"s": step_id, "u": user["id"]})
    await session.execute(text(
        "UPDATE public.truck_steps SET status = 'in_review', worker_id = :u, media_type = CAST(:mt AS media_type), "
        "media_local_path = :lp, media_file_id = NULL, worker_comment = :c, submitted_at = now(), "
        "started_at = COALESCE(started_at, now()), updated_at = now() WHERE id = :s"),
        {"u": user["id"], "mt": primary["media_type"], "lp": primary["local_path"],
         "c": (comment or "").strip()[:1000] or None, "s": step_id})
    return {"step_id": step_id, "truck_id": row["truck_id"], "serial": row["serial_number"], "step_number": row["step_number"],
            "worker": user["full_name"], "comment": (comment or "").strip()[:1000] or None, "files": len(drafts),
            "primary_path": primary["local_path"], "primary_kind": primary["media_type"], "primary_id": primary["id"]}


# --------------------------------------------------------------------------- #
# QC: tasdiqlash / rad etish
# --------------------------------------------------------------------------- #
async def _review_step(session: AsyncSession, user: dict, step_id: int) -> dict:
    _need_role(user, "qc")
    row = await _step_row(session, step_id, lock=True)
    if row["status"] != "in_review":
        raise AppError("not_in_review", 409)
    return row


async def approve(session: AsyncSession, user: dict, step_id: int) -> dict:
    row = await _review_step(session, user, step_id)
    await session.execute(text(
        "UPDATE public.truck_steps SET status = 'approved', qc_id = :q, reviewed_at = now(), updated_at = now() WHERE id = :s"),
        {"q": user["id"], "s": step_id})
    last = row["step_number"] >= TOTAL_STEPS
    if last:
        await session.execute(text(
            "UPDATE public.trucks SET status = 'completed', completed_at = now(), updated_at = now() WHERE id = :t"),
            {"t": row["truck_id"]})
    else:
        await session.execute(text(
            "UPDATE public.trucks SET current_step = :n, updated_at = now() WHERE id = :t"),
            {"n": row["step_number"] + 1, "t": row["truck_id"]})
    next_id = None if last else await session.scalar(text(
        "SELECT id FROM public.truck_steps WHERE truck_id = :t AND step_number = :n"),
        {"t": row["truck_id"], "n": row["step_number"] + 1})
    return {"next_step_id": next_id, "step_id": step_id, "truck_id": row["truck_id"], "serial": row["serial_number"], "model": row["model"],
            "step_number": row["step_number"], "next_step": None if last else row["step_number"] + 1,
            "completed": last, "worker_id": row["worker_id"], "priority": row["priority"], "deadline": iso(row["deadline"])}


async def reject(session: AsyncSession, user: dict, step_id: int, reason: str) -> dict:
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise AppError("reason_short", 422)
    row = await _review_step(session, user, step_id)
    await session.execute(text(
        "UPDATE public.truck_steps SET status = 'rejected', qc_id = :q, qc_comment = :r, reviewed_at = now(), "
        "updated_at = now() WHERE id = :s"), {"q": user["id"], "r": reason[:1000], "s": step_id})
    return {"step_id": step_id, "truck_id": row["truck_id"], "serial": row["serial_number"], "step_number": row["step_number"],
            "worker_id": row["worker_id"], "reason": reason[:1000]}


# --------------------------------------------------------------------------- #
# Xabar oluvchilar (commitdan oldin so'raladi, fon vazifasiga oddiy ma'lumot sifatida beriladi)
# --------------------------------------------------------------------------- #
async def recipients_for(session: AsyncSession, *, role: str | None = None, step: int | None = None,
                         user_id: int | None = None) -> list[dict]:
    where, params = ["is_active", "telegram_id IS NOT NULL"], {}
    if role:
        where.append("role::text = :role"); params["role"] = role
    if step is not None:
        where.append("step_number = :step"); params["step"] = step
    if user_id is not None:
        where.append("id = :uid"); params["uid"] = user_id
    rows = (await session.execute(text(
        f"SELECT id, telegram_id, language, full_name FROM public.users WHERE {' AND '.join(where)}"), params)).mappings().all()
    return [dict(r) for r in rows]
