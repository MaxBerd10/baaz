"""Telegram Mini App uchun marshrutlar: `/app` (ilova sahifasi) va `/app/api/*` (JSON), `/app/media/*` (fayllar).

Kirish — Telegram'ning imzolangan `initData` si (parol yo'q): `POST /app/api/auth` uni tekshirib, qisqa muddatli token beradi;
keyingi so'rovlarda `Authorization: Bearer <token>` (rasm/video uchun `?k=<token>`) yuboriladi. Foydalanuvchi har so'rovda
bazadan qayta o'qiladi, shuning uchun rol o'zgarsa yoki faolsizlantirilsa darrov kuchga kiradi.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.services import factory as factory_svc
from app.services import miniapp as mini
from app.services import miniapp_notify as notify
from app.services import tg_auth
from app.services.media_store import MEDIA_ROOT, guess_type, resolve_local, telegram_cached

_log = logging.getLogger("miniapp")
router = APIRouter()
_INDEX = Path(__file__).with_name("miniapp") / "index.html"
_PLACEHOLDER = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 90"><rect width="120" height="90" fill="#eef0f6"/>'
                b'<path d="M30 60l18-20 14 14 10-9 18 15z" fill="#c9cfdd"/></svg>')


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


def _token_from(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("k", "")


async def current_user(request: Request, session: AsyncSession = Depends(get_db)) -> dict:
    tg = tg_auth.read_session_token(_token_from(request), settings.secret_key)
    if tg is None:
        raise mini.AppError("auth", 401)
    user = await mini.get_user(session, tg)
    if user is None or not user["is_active"]:
        raise mini.AppError("inactive", 403)
    return user


def _public_user(u: dict) -> dict:
    return {"id": u["id"], "name": u["full_name"], "role": u["role"], "step": u["step_number"],
            "lang": u["language"] if u["language"] in ("uz", "uz_cyrl", "ru") else "uz", "photo": bool(u["has_photo"])}


# --------------------------------------------------------------------------- #
# Sahifa va kirish
# --------------------------------------------------------------------------- #
@router.get("/app", response_class=HTMLResponse)
async def app_page():
    # Har safar yangi: Telegram WebView eski JS ni keshda saqlab qolmasin.
    return HTMLResponse(_INDEX.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.post("/app/api/auth")
async def api_auth(request: Request, session: AsyncSession = Depends(get_db)):
    if not settings.bot_token:
        raise mini.AppError("not_configured", 503)
    try:
        body = await request.json()
        tg_user = tg_auth.validate_init_data(str(body.get("init_data", "")), settings.bot_token)
    except (tg_auth.InitDataError, ValueError):
        raise mini.AppError("bad_init", 401)
    user = await mini.get_user(session, tg_user["id"])
    if user is None:
        return JSONResponse({"error": "not_registered", "name": tg_user.get("first_name", "")}, status_code=403)
    if not user["is_active"]:
        return JSONResponse({"error": "inactive", "name": user["full_name"]}, status_code=403)
    return {"token": tg_auth.make_session_token(user["telegram_id"], settings.secret_key), "user": _public_user(user),
            "counts": await mini.counts(session, user)}


@router.get("/app/api/home")
async def api_home(user: dict = Depends(current_user), session: AsyncSession = Depends(get_db)):
    out = {"user": _public_user(user), "counts": await mini.counts(session, user)}
    if user["role"] == "admin":
        out["deadlines"] = await mini.deadlines(session, user)
    return out


# --------------------------------------------------------------------------- #
# Ro'yxatlar
# --------------------------------------------------------------------------- #
@router.get("/app/api/tasks")
async def api_tasks(user: dict = Depends(current_user), session: AsyncSession = Depends(get_db)):
    return {"items": await mini.worker_tasks(session, user)}


@router.get("/app/api/queue")
async def api_queue(user: dict = Depends(current_user), session: AsyncSession = Depends(get_db)):
    return {"items": await mini.qc_queue(session, user)}


@router.get("/app/api/history")
async def api_history(user: dict = Depends(current_user), session: AsyncSession = Depends(get_db)):
    return {"items": await mini.history(session, user)}


@router.get("/app/api/step/{step_id}")
async def api_step(step_id: int, user: dict = Depends(current_user), session: AsyncSession = Depends(get_db)):
    return await mini.step_detail(session, user, step_id)


# --------------------------------------------------------------------------- #
# Ishchi: yuklash va yuborish
# --------------------------------------------------------------------------- #
@router.post("/app/api/step/{step_id}/upload")
async def api_upload(step_id: int, file: UploadFile = File(...), user: dict = Depends(current_user),
                     session: AsyncSession = Depends(get_db)):
    head = await file.read(32)
    sniffed = mini.sniff_media(head)
    if sniffed is None:
        raise mini.AppError("bad_file", 415)
    kind, ext = sniffed
    prep = await mini.prepare_upload(session, user, step_id, kind)
    rel, full = mini.new_media_path(prep["truck_id"], prep["step_number"], ext)
    limit = mini.MAX_VIDEO_BYTES if kind == "video" else mini.MAX_PHOTO_BYTES
    size = len(head)
    try:
        with open(full, "wb") as out:
            out.write(head)
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise mini.AppError("too_big", 413)
                await asyncio.to_thread(out.write, chunk)
        item = await mini.register_upload(session, user, step_id, kind, rel, size)
        await session.commit()
    except BaseException:
        try:
            full.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return item


@router.delete("/app/api/step/{step_id}/media/{media_id}")
async def api_delete_media(step_id: int, media_id: str, user: dict = Depends(current_user),
                           session: AsyncSession = Depends(get_db)):
    await mini.delete_draft(session, user, step_id, media_id)
    await session.commit()
    return {"ok": True}


@router.post("/app/api/step/{step_id}/submit")
async def api_submit(step_id: int, request: Request, bg: BackgroundTasks, user: dict = Depends(current_user),
                     session: AsyncSession = Depends(get_db)):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    info = await mini.submit(session, user, step_id, str(body.get("comment") or ""))
    qcs = await mini.recipients_for(session, role="qc")
    await session.commit()
    bg.add_task(_after_submit, info, qcs, dict(user))
    return {"ok": True, "files": info["files"]}


async def _after_submit(info: dict, qcs: list[dict], worker: dict) -> None:
    try:
        file_id = await notify.on_submitted(info, qcs, worker)
        if file_id:  # bot orqali tekshiradigan QC rasmni ko'ra olishi uchun Telegram file_id ni saqlab qo'yamiz
            async with SessionLocal() as s:
                await s.execute(text("UPDATE public.truck_steps SET media_file_id = :f WHERE id = :i AND media_local_path = :p"),
                                {"f": file_id, "i": info["step_id"], "p": info["primary_path"]})
                await s.execute(text("UPDATE public.truck_step_media SET file_id = :f WHERE id = :m"),
                                {"f": file_id, "m": info["primary_id"]})
                await s.commit()
    except Exception:  # noqa: BLE001 — xabar yuborilmasa ham ish saqlangan
        _log.exception("submit xabarlari yuborilmadi")


# --------------------------------------------------------------------------- #
# QC: tasdiqlash / rad etish
# --------------------------------------------------------------------------- #
@router.post("/app/api/step/{step_id}/approve")
async def api_approve(step_id: int, bg: BackgroundTasks, user: dict = Depends(current_user),
                      session: AsyncSession = Depends(get_db)):
    info = await mini.approve(session, user, step_id)
    worker = (await mini.recipients_for(session, user_id=info["worker_id"]) or [None])[0] if info["worker_id"] else None
    nxt = [] if info["completed"] else await mini.recipients_for(session, role="worker", step=info["next_step"])
    admins = await mini.recipients_for(session, role="admin") if info["completed"] else []
    await session.commit()
    bg.add_task(_safe, notify.on_approved, info, worker, nxt, admins)
    return {"ok": True, "completed": info["completed"]}


@router.post("/app/api/step/{step_id}/reject")
async def api_reject(step_id: int, request: Request, bg: BackgroundTasks, user: dict = Depends(current_user),
                     session: AsyncSession = Depends(get_db)):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    info = await mini.reject(session, user, step_id, str(body.get("reason") or ""))
    worker = (await mini.recipients_for(session, user_id=info["worker_id"]) or [None])[0] if info["worker_id"] else None
    await session.commit()
    bg.add_task(_safe, notify.on_rejected, info, worker)
    return {"ok": True}


async def _safe(fn, *args) -> None:
    try:
        await fn(*args)
    except Exception:  # noqa: BLE001
        _log.exception("xabar yuborilmadi")


# --------------------------------------------------------------------------- #
# Fayllar (rasm/video, model rasmi, selfi) — token `?k=` orqali
# --------------------------------------------------------------------------- #
def _send(path: Path, *, small: bool, key: str) -> Response:
    headers = {"Cache-Control": "private, max-age=86400"}
    if small and path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        thumb = MEDIA_ROOT / "thumbs" / f"{key}_640.jpg"
        if not thumb.is_file():
            try:
                from PIL import Image, ImageOps

                with Image.open(path) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    im.thumbnail((640, 640))
                    thumb.parent.mkdir(parents=True, exist_ok=True)
                    im.save(thumb, "JPEG", quality=80, optimize=True)
            except Exception:  # noqa: BLE001
                thumb = path
        return FileResponse(str(thumb), media_type=guess_type(thumb), headers=headers)
    return FileResponse(str(path), media_type=guess_type(path), headers=headers)


@router.get("/app/media/{mid}")
async def app_media(mid: str, s: str | None = None, user: dict = Depends(current_user),
                    session: AsyncSession = Depends(get_db)):
    local = file_id = None
    if mid[:1] == "m" and mid[1:].isdigit():
        row = (await session.execute(text(
            "SELECT step_id, local_path, file_id, draft, added_by_id FROM public.truck_step_media WHERE id = :i"),
            {"i": int(mid[1:])})).first()
        if row is None:
            raise mini.AppError("not_found", 404)
        step_id, local, file_id, draft, owner = row
        if draft and owner != user["id"]:
            raise mini.AppError("forbidden", 403)
    elif mid[:1] == "s" and mid[1:].isdigit():
        step_id = int(mid[1:])
        row = (await session.execute(text("SELECT media_local_path, media_file_id FROM public.truck_steps WHERE id = :i"),
                                     {"i": step_id})).first()
        if row is None:
            raise mini.AppError("not_found", 404)
        local, file_id = row
    else:
        raise mini.AppError("not_found", 404)
    if not mini._can_see(user, await mini._step_row(session, step_id)):
        raise mini.AppError("forbidden", 403)
    path = resolve_local(local) if local else None
    if path is None and file_id:
        path = await telegram_cached(file_id)
    if path is None:
        return Response(_PLACEHOLDER, media_type="image/svg+xml")
    return _send(path, small=bool(s), key=f"mini_{mid}")


@router.get("/app/model/{model_id}")
async def app_model(model_id: int, user: dict = Depends(current_user), session: AsyncSession = Depends(get_db)):
    card = await factory_svc.get_model(session, model_id)
    if card is None or not card.image_file:
        return Response(_PLACEHOLDER, media_type="image/svg+xml")
    small = await asyncio.to_thread(factory_svc.make_thumb, card.image_file)
    if small is not None:
        return FileResponse(str(small), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
    path = MEDIA_ROOT / card.image_file
    return FileResponse(str(path)) if path.is_file() else Response(_PLACEHOLDER, media_type="image/svg+xml")


@router.get("/app/user/{user_id}")
async def app_user_photo(user_id: int, user: dict = Depends(current_user), session: AsyncSession = Depends(get_db)):
    row = (await session.execute(text("SELECT photo_path, photo_file_id FROM public.users WHERE id = :i"),
                                 {"i": user_id})).first()
    path = resolve_local(row[0]) if row and row[0] else None
    if path is None and row and row[1]:
        path = await telegram_cached(row[1])
    if path is None:
        return Response(_PLACEHOLDER, media_type="image/svg+xml")
    return _send(path, small=True, key=f"mini_user_{user_id}")


# --------------------------------------------------------------------------- #
def register(app: FastAPI) -> None:
    app.include_router(router)

    @app.exception_handler(mini.AppError)
    async def _app_error(_: Request, exc: mini.AppError):
        return JSONResponse({"error": exc.code}, status_code=exc.status)
