import datetime as dt
import os
from pathlib import Path

# --- Vercel (yoki boshqa read-only serverless) muhitini config yuklanishidan
#     OLDIN to'g'rilaymiz: faqat /tmp yoziladi, SQLite'ni o'sha yerga olamiz. ---
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    _db = os.environ.get("DATABASE_URL", "").strip()
    if not _db.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")):
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/baaz.db"
        os.environ["AUTO_SEED"] = "1"
        os.environ.pop("SKIP_INIT_DB", None)
        # Tayyor demo bazani /tmp ga nusxalash — har cold-start'da qaytadan
        # seed qilishdan ancha tez (fayl nusxasi vs yuzlab INSERT).
        import shutil

        _seed = Path(__file__).resolve().parents[2] / "seed.sqlite3"
        if _seed.is_file() and not os.path.exists("/tmp/baaz.db"):
            try:
                shutil.copy(_seed, "/tmp/baaz.db")
            except OSError:
                pass
    os.environ["MEDIA_ROOT"] = "/tmp/media"
    os.environ.setdefault("SHOW_ERRORS", "1")

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal, init_db
from app.enums import PRODUCT_STATUS_LABEL, ROLE_LABEL, ProductStatus, Role, StageRunStatus
from app.models import AuditLog, Media, ModelCard, Product, StageRun, User
from app.services import dashboard as dash_svc
from app.services import factory as factory_svc
from app.services import telegram_notify
from app.services import products as products_svc
from app.services import stages as stages_svc
from app.services import stats as stats_svc
from app.services.media_store import abs_path, ensure_root, guess_type, resolve_local, telegram_cached
from app.web import charts
from app.web.auth import (
    COOKIE_NAME,
    install_redirect_handler,
    make_token,
    require_login,
    valid,
)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

try:
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo(settings.timezone)
except Exception:  # pragma: no cover
    _TZ = dt.timezone.utc

_ACTION_LABEL = {
    "product_created": "yaratildi",
    "media_added": "media",
    "submitted_to_qc": "QC ga yubordi",
    "qc_approved": "tasdiqladi",
    "qc_returned": "qaytardi",
    "stage_advanced": "keyingi bosqich",
    "product_finished": "tayyor",
}


_UZ_WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
_UZ_MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
              "sentabr", "oktabr", "noyabr", "dekabr"]


def _today_uz() -> tuple[str, str]:
    """('Juma', '25 sentabr 2026') — sarlavhadagi «bugun» kartasi uchun."""
    n = dt.datetime.now(_TZ)
    return _UZ_WEEKDAYS[n.weekday()], f"{n.day} {_UZ_MONTHS[n.month - 1]} {n.year}"


def _fmt_dt(value):
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(_TZ).strftime("%d.%m.%Y %H:%M")


def _fmt_time(value):
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(_TZ).strftime("%d.%m %H:%M")


def _avatar_seed(name: str | None) -> int:
    import hashlib

    return int.from_bytes(hashlib.md5((name or "?").strip().encode("utf-8")).digest()[:4], "big")


_AV_SKIN = ["#f3c9a3", "#eab98b", "#dda06f", "#c98b52", "#a9713f", "#8a5a34"]
_AV_HAIR = ["#2b2b2b", "#1c1c1c", "#3b2a1c", "#4a3626", "#5a4433", "#6b4f3a"]
_AV_SHIRT = ["#4f6b8a", "#5a7d5a", "#7a5c8a", "#8a6a4a", "#6a6f7a", "#8a5a5a"]


def _avatar_svg(name: str | None) -> str:
    """Ishchi uchun barqaror, erkak ko'rinishidagi avatar — to'liq offline (data URI)."""
    import base64

    s = _avatar_seed(name)
    hue = s % 360
    bg = f"hsl({hue},42%,90%)"
    skin = _AV_SKIN[(s >> 3) % len(_AV_SKIN)]
    hair = _AV_HAIR[(s >> 7) % len(_AV_HAIR)]
    shirt = _AV_SHIRT[(s >> 11) % len(_AV_SHIRT)]
    style = (s >> 15) % 3          # soqol turi
    hard_hat = (s >> 18) % 5 == 0  # ba'zida kaska

    p = [f'<rect width="64" height="64" fill="{bg}"/>']
    # yelka / ko'ylak
    p.append(f'<path d="M12 64c0-13 9-21 20-21s20 8 20 21z" fill="{shirt}"/>')
    p.append(f'<rect x="27" y="37" width="10" height="10" fill="{skin}"/>')
    # soqol asosi (yuzdan bir oz pastroq, keyin yuz ustiga chiziladi -> soqol jiyagi)
    p.append(f'<circle cx="32" cy="30" r="14" fill="{hair}"/>')
    p.append(f'<circle cx="32" cy="27" r="14" fill="{skin}"/>')
    if style == 0:      # to'liq soqol
        p.append(f'<path d="M19 30c2 9 7 15 13 15s11-6 13-15c-3 4-8 6-13 6s-10-2-13-6z" fill="{hair}"/>')
        p.append(f'<rect x="26" y="31" width="12" height="3" rx="1.5" fill="{hair}"/>')
    elif style == 1:    # echki soqol + mo'ylov
        p.append(f'<path d="M28 39h8c0 4-2 7-4 7s-4-3-4-7z" fill="{hair}"/>')
        p.append(f'<rect x="26" y="31" width="12" height="3" rx="1.5" fill="{hair}"/>')
    else:               # qisqa soqol (stubble) + mo'ylov
        p.append(f'<path d="M20 32c2 7 6 12 12 12s10-5 12-12c-3 3-7 4-12 4s-9-1-12-4z" fill="{hair}" opacity=".45"/>')
        p.append(f'<rect x="26" y="31" width="12" height="2.6" rx="1.3" fill="{hair}"/>')
    # ko'zlar + qosh
    p.append('<rect x="24.5" y="24" width="6" height="1.8" rx=".9" fill="#4a4a4a"/>')
    p.append('<rect x="33.5" y="24" width="6" height="1.8" rx=".9" fill="#4a4a4a"/>')
    p.append('<circle cx="27.5" cy="27" r="1.7" fill="#37474f"/><circle cx="36.5" cy="27" r="1.7" fill="#37474f"/>')
    # soch yoki kaska
    if hard_hat:
        p.append('<path d="M16 24a16 16 0 0 1 32 0v2H16z" fill="#f5a623"/>')
        p.append('<rect x="30" y="8" width="4" height="8" rx="2" fill="#f5a623"/>')
        p.append('<rect x="13" y="24" width="38" height="4" rx="2" fill="#e0951a"/>')
    else:
        p.append(f'<path d="M18 25c0-10 6-16 14-16s14 6 14 16c-2-5-6-8-9-8 0-3-3-4-5-3-2-2-6-2-9 1-3 0-5 4-5 10z" fill="{hair}"/>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{"".join(p)}</svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


_AVATAR_DIR = BASE_DIR / "static" / "avatars"


_PHOTO_BY_NAME: dict[str, str] = {}   # ism -> /media/user/<id>?v=...  (bot rejimida, ro'yxatdan o'tishda yuborilgan selfi)


def _avatar_url(name: str | None) -> str:
    """Ishchi surati: haqiqiy selfi (bot rejimida) → static/avatars/1..N → offline SVG avatar."""
    real = _PHOTO_BY_NAME.get((name or "").strip())
    if real:
        return real
    files = sorted(
        f.name for f in _AVATAR_DIR.glob("*")
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    ) if _AVATAR_DIR.is_dir() else []
    if not files:
        return _avatar_svg(name)
    return "/static/avatars/" + files[_avatar_seed(name) % len(files)]


import re as _re

_PR_RE = _re.compile(r"\bPR-\d{4,}\s*(?:[—–-]\s*)?")


def _nopr(text):
    """Matndan 'PR-000123 —' kabi ichki kodlarni olib tashlaydi."""
    return _PR_RE.sub("", text or "")


templates.env.filters["dt"] = _fmt_dt
templates.env.filters["tm"] = _fmt_time
templates.env.filters["nopr"] = _nopr
def _spec(size=None, color=None, code=None):
    """'5 metr · Oq · T1-2026-001' — bo'sh qismlar tashlanadi. Seriya raqami faqat
    bot rejimida (haqiqiy zavod raqami) ko'rsatiladi; demo'dagi ichki PR-kod emas."""
    parts = []
    if size:
        parts.append(f"{size} metr")
    if color and color != "—":
        parts.append(color)
    if settings.bot_db and code:
        parts.append(code)
    return " · ".join(parts) or "—"


templates.env.filters["dur"] = stats_svc.fmt_hours
templates.env.globals["spec"] = _spec
templates.env.globals["bot_db"] = settings.bot_db
templates.env.globals["RUN_STATUS_LABEL"] = {
    "in_progress": "Ishlanmoqda", "qc_pending": "Sifat nazoratida",
    "approved": "Tasdiqlangan", "returned": "Qaytarilgan",
}
templates.env.globals["avatar_url"] = _avatar_url
templates.env.globals["avatar_svg"] = _avatar_svg
templates.env.globals["PRODUCT_STATUS_LABEL"] = PRODUCT_STATUS_LABEL
templates.env.globals["ROLE_LABEL"] = ROLE_LABEL
templates.env.globals["ProductStatus"] = ProductStatus
templates.env.globals["ACTION_LABEL"] = _ACTION_LABEL

# Production: API hujjatlari (/docs, /redoc, /openapi.json) tashqariga ochiq bo'lmasin.
app = FastAPI(title="Baaz — Ishlab chiqarish nazorati", docs_url=None, redoc_url=None, openapi_url=None)
install_redirect_handler(app)

_static = BASE_DIR / "static"
try:
    _static.mkdir(exist_ok=True)
except OSError:  # read-only FS (Vercel)
    pass
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return resp


@app.middleware("http")
async def _static_cache(request: Request, call_next):
    """Statik fayllarga uzoq cache — CDN chekkasida keshlansin, funksiya har safar
    chaqirilmasin (Vercel'da tezlik uchun muhim)."""
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/static/"):
        resp.headers["Cache-Control"] = "public, max-age=604800, s-maxage=604800, immutable"
    elif path.startswith("/media/"):
        # Login talab qiladi — CDN'da umumiy keshlanmasin, faqat brauzerda.
        resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp

_SKIP_INIT = os.getenv("SKIP_INIT_DB", "").lower() in ("1", "true", "yes")
_AUTO_SEED = os.getenv("AUTO_SEED", "").lower() in ("1", "true", "yes")
_log = __import__("logging").getLogger("web")

# Production (bot rejimi) xavfsizlik tekshiruvi: standart maxfiy kalit bilan sessiyalarni soxtalash mumkin bo'ladi.
if settings.bot_db:
    if settings.secret_key in ("", "change-me"):
        raise RuntimeError("SECRET_KEY o'rnatilmagan (standart qiymat). `openssl rand -hex 32` bilan yangi kalit yarating.")
    if settings.web_password.strip().lower() in ("", "admin", "password", "123456", "12345678"):
        _log.warning("⚠️  WEB_PASSWORD juda oddiy! Production uchun uzun va noyob parol qo'ying.")

_BOOTSTRAPPED = False


async def _bootstrap_once() -> None:
    """Birinchi so'rovda: jadvallarni yaratish va (AUTO_SEED bo'lsa) demo to'ldirish.
    Xatolar sahifani buzmasligi uchun yutib yuboriladi."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    try:
        ensure_root()
    except Exception:  # pragma: no cover
        pass
    if not _SKIP_INIT:
        try:
            await init_db()
        except Exception as exc:  # pragma: no cover
            _log.warning("init_db: %s", exc)
    if _AUTO_SEED and not settings.bot_db:
        try:
            from app.demo import is_empty, seed_demo

            async with SessionLocal() as s:
                if await is_empty(s):
                    await seed_demo(s)
                    await s.commit()
                    _log.info("demo seeded")
        except Exception as exc:  # pragma: no cover
            _log.warning("seed_demo: %s", exc)


@app.on_event("startup")
async def _startup() -> None:
    try:
        await _bootstrap_once()
    except Exception as exc:  # pragma: no cover
        _log.warning("startup: %s", exc)


# Xato tafsilotlarini (traceback) brauzerga faqat SHOW_ERRORS=1 bo'lsa ko'rsatamiz (demo). Standart — o'chiq.
_SHOW_ERRORS = os.getenv("SHOW_ERRORS", "0").lower() in ("1", "true", "yes")


@app.middleware("http")
async def _ensure_bootstrap(request: Request, call_next):
    # Lifespan startup Vercel'da ishlamasligi mumkin — birinchi so'rovda ham urinamiz.
    if not _BOOTSTRAPPED:
        await _bootstrap_once()
    try:
        return await call_next(request)
    except Exception:  # pragma: no cover
        import traceback

        tb = traceback.format_exc()
        _log.error("request failed: %s", tb)
        if _SHOW_ERRORS:
            return Response("REQUEST ERROR\n\n" + tb, status_code=500,
                            media_type="text/plain; charset=utf-8")
        raise


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


async def _side_counts(session: AsyncSession) -> dict:
    rows = dict(
        (
            await session.execute(
                select(Product.status, func.count()).group_by(Product.status)
            )
        ).all()
    )
    return {s.value: int(rows.get(s, 0)) for s in ProductStatus}


# Yon panel / qo'ng'iroq ma'lumotlari har bir sahifada kerak, lekin kam o'zgaradi —
# qisqa muddatli (jarayon ichidagi) kesh bilan har so'rovdagi 3 ta qo'shimcha
# so'rovni olib tashlaymiz (demo bazasi statik bo'lgani uchun xavfsiz).
_SIDE_CACHE: dict = {"t": 0.0, "alerts": [], "counts": None}
_SIDE_TTL = 20.0


async def _side_data(session: AsyncSession) -> tuple[list, dict]:
    import time as _t

    now = _t.monotonic()
    if _SIDE_CACHE["counts"] is None or now - _SIDE_CACHE["t"] > _SIDE_TTL:
        _SIDE_CACHE["alerts"] = await dash_svc.alerts(session)
        _SIDE_CACHE["counts"] = await _side_counts(session)
        _SIDE_CACHE["t"] = now
        if settings.bot_db:
            try:
                from sqlalchemy import text as _text

                rows = (await session.execute(_text(
                    "SELECT id, full_name, COALESCE(photo_path, photo_file_id) AS k "
                    "FROM web.users WHERE photo_file_id IS NOT NULL OR photo_path IS NOT NULL"
                ))).all()
                import hashlib as _h

                _PHOTO_BY_NAME.clear()
                for uid_, nm, k in rows:
                    _PHOTO_BY_NAME[(nm or "").strip()] = f"/media/user/{uid_}?v={_h.md5((k or '').encode()).hexdigest()[:8]}"
            except Exception:  # noqa: BLE001 — selfi ustunlari hali yo'q bo'lsa, oddiy avatarlar qoladi
                pass
    return _SIDE_CACHE["alerts"], _SIDE_CACHE["counts"]


async def page(name: str, request: Request, session: AsyncSession, **ctx):
    ctx.setdefault("now_str", dt.datetime.now(_TZ).strftime("%d.%m.%Y"))
    ctx.setdefault("today_wd", _today_uz()[0])
    ctx.setdefault("today_dt", _today_uz()[1])
    _al, _counts = await _side_data(session)
    if "alerts_list" not in ctx or "alerts_count" not in ctx:
        ctx.setdefault("alerts_count", len(_al))
        ctx.setdefault("alerts_list", _al[:6])
    ctx.setdefault("side_counts", _counts)
    return templates.TemplateResponse(name, {"request": request, **ctx})


def render(name: str, request: Request, **ctx):
    ctx.setdefault("now_str", dt.datetime.now(_TZ).strftime("%d.%m.%Y"))
    ctx.setdefault("today_wd", _today_uz()[0])
    ctx.setdefault("today_dt", _today_uz()[1])
    ctx.setdefault("alerts_count", 0)
    ctx.setdefault("alerts_list", [])
    return templates.TemplateResponse(name, {"request": request, **ctx})


def spark(data, color="var(--brand)"):
    return Markup(charts.sparkline(data, color=color))


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return render("login.html", request, error=None)


_LOGIN_FAILS: dict[str, list[float]] = {}
_LOGIN_MAX, _LOGIN_WINDOW = 5, 300.0   # 5 daqiqada 5 ta noto'g'ri urinishdan keyin bloklanadi


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")) or "?"


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    import hmac
    import time

    ip, now = _client_ip(request), time.monotonic()
    fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_WINDOW]
    if len(fails) >= _LOGIN_MAX:
        _LOGIN_FAILS[ip] = fails
        resp = render("login.html", request, error="Juda ko'p noto'g'ri urinish. 5 daqiqadan keyin qayta urinib ko'ring.")
        resp.status_code = 429
        return resp
    if not hmac.compare_digest(password.encode(), settings.web_password.encode()):
        fails.append(now)
        _LOGIN_FAILS[ip] = fails
        return render("login.html", request, error="Parol noto'g'ri")
    _LOGIN_FAILS.pop(ip, None)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE_NAME, make_token(), httponly=True, samesite="lax",
                    secure=request.url.scheme == "https", max_age=60 * 60 * 12)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
_KPI_SPARK_COLOR = {
    "violet": "var(--c-violet)", "green": "var(--c-green)", "blue": "var(--c-blue)",
    "amber": "var(--c-amber)", "red": "var(--c-red)", "teal": "var(--c-teal)",
}


@app.get("/", response_class=HTMLResponse)
async def overview(
    request: Request, sel: str | None = None, period: str = "7d",
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    if period not in dash_svc.PERIODS:
        period = "7d"
    d = await dash_svc.home(session, sel_code=sel or None, period=period)
    truck_images = [
        "/static/trucks/trailer-orange.jpg",
        "/static/trucks/trailer-blue.jpg",
        "/static/trucks/trailer-green.jpg",
        "/static/trucks/trailer-cream.jpg",
    ]
    image_by_code = {
        truck["code"]: truck_images[index % len(truck_images)]
        for index, truck in enumerate(d["trucks"])
    }
    for truck in d["trucks"]:
        truck["image"] = image_by_code[truck["code"]]
    if d["sel"]:
        d["sel"]["image"] = image_by_code.get(d["sel"]["code"], truck_images[0])
    if settings.bot_db:  # model katalogidagi haqiqiy rasm bo'lsa — shuni ko'rsatamiz
        imgs = await factory_svc.image_map(session)
        for truck in d["trucks"]:
            truck["image"] = imgs.get(truck["model"], truck["image"])
        if d["sel"]:
            d["sel"]["image"] = imgs.get(d["sel"]["model"], d["sel"]["image"])

    for c in d["kpi5"]:
        col = _KPI_SPARK_COLOR.get(c["tone"], "var(--brand)")
        c["spark_svg"] = Markup(charts.sparkline(c["spark"], width=240, height=40, color=col, fill=True))
    for m in d["summary4"]:
        m["spark_svg"] = Markup(charts.sparkline(m["spark"], width=150, height=28, color=m["color"], fill=True))

    donut_svg = Markup(charts.donut(
        [(g["color"], g["value"]) for g in d["donut"]["segments"]],
        center_top=f"{d['donut']['pct']}%", center_bottom="progress",
        size=108, stroke=14,
    ))
    return await page("index.html", request, session, active="dash", d=d, donut_svg=donut_svg,
                      period=period, periods=dash_svc.PERIODS)


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
_TRUCK_IMAGES = [
    "/static/trucks/trailer-orange.jpg",
    "/static/trucks/trailer-blue.jpg",
    "/static/trucks/trailer-green.jpg",
    "/static/trucks/trailer-cream.jpg",
]
_FLEET_ST = {
    "in_production": "Ishlab chiqarishda",
    "qc_pending": "QC kutmoqda",
    "returned": "Qaytarilgan",
    "done": "Tayyor",
    "cancelled": "Bekor qilingan",
}


@app.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request, status: str | None = None, q: str | None = None, view: str | None = None,
    sort: str | None = None,
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    sort = "deadline" if sort == "deadline" else ""
    view = "list" if (view == "list" or sort) else "line"
    status_enum = None
    if status:
        try:
            status_enum = ProductStatus(status)
        except ValueError:
            status_enum = None

    all_items = await products_svc.list_products(session, limit=300)
    stages = await stages_svc.list_stages(session)
    stage_total = len(stages) or 1
    stage_names = {s.order_no: s.name for s in stages}

    # approved bosqichlar soni — har bir truck uchun
    done_by_id: dict[int, int] = {}
    for pid, cnt in await session.execute(
        select(StageRun.product_id, func.count(func.distinct(StageRun.stage_order)))
        .where(StageRun.status == StageRunStatus.approved)
        .group_by(StageRun.product_id)
    ):
        done_by_id[pid] = cnt

    # mas'ul ishchi — eng oxirgi bosqich yozuvi bo'yicha
    worker_by_id: dict[int, str] = {}
    for pid, name in await session.execute(
        select(StageRun.product_id, User.full_name)
        .join(User, User.id == StageRun.worker_id)
        .order_by(StageRun.id.desc())
    ):
        worker_by_id.setdefault(pid, name)

    imgs = await factory_svc.image_map(session) if settings.bot_db else {}
    # Bot rejimida: hozir shu bosqichga biriktirilgan ishchilar (ish qilinadigan/qayta qilinadigan trucklar uchun mas'ul)
    wk_by_order: dict[int, list[str]] = {}
    if settings.bot_db:
        sid2order = {s.id: s.order_no for s in stages}
        for w in (await session.scalars(
            select(User).where(User.role == Role.worker, User.is_active.is_(True)).order_by(User.full_name)
        )).all():
            if w.stage_id in sid2order:
                wk_by_order.setdefault(sid2order[w.stage_id], []).append(w.full_name)
    today = dt.datetime.now(_TZ).date()
    real_dl: dict[int, dt.datetime] = {}
    if settings.bot_db:  # haqiqiy muddat — buyurtmada belgilangan (trucks.deadline)
        from sqlalchemy import text as _sql

        real_dl = {
            int(r[0]): r[1]
            for r in await session.execute(_sql("SELECT id, deadline FROM web.products WHERE deadline IS NOT NULL"))
        }
    rows = []
    for idx, p in enumerate(all_items):
        done = stage_total if p.status == ProductStatus.done else done_by_id.get(p.id, 0)
        if settings.bot_db:
            due = real_dl.get(p.id)
        else:
            due = p.created_at + dt.timedelta(days=int(stage_total * 1.6)) if p.created_at else None
        due_day = (due.astimezone(_TZ).date() if due and due.tzinfo else (due.date() if due else None))
        overdue = bool(
            due_day and due_day < today
            and p.status not in (ProductStatus.done, ProductStatus.cancelled)
        )
        worker, worker_more, worker_note = worker_by_id.get(p.id, "—"), 0, ""
        if settings.bot_db and p.status in (ProductStatus.in_production, ProductStatus.returned):
            # ish hali bajarilishi kerak: mas'ul — shu bosqichning hozirgi ishchilari (oldingi bosqich ishchisi emas)
            cur_workers = wk_by_order.get(p.current_stage_order, [])
            worker = cur_workers[0] if cur_workers else "—"
            worker_more = max(len(cur_workers) - 1, 0)
        elif settings.bot_db and p.status == ProductStatus.qc_pending:
            worker_note = "yubordi"  # QC tekshirmoqda: ko'rsatilgan ishchi — ishni yuborgan kishi
        rows.append({
            "worker_more": worker_more, "worker_note": worker_note,
            "overdue": overdue,
            "code": p.code, "model": p.model or "—", "size": p.size_m,
            "color": p.color or "—", "hex": dash_svc.color_hex(p.color),
            "customer": p.note or "—",
            "image": imgs.get(p.model or "", _TRUCK_IMAGES[idx % len(_TRUCK_IMAGES)]),
            "status": p.status.value, "status_label": _FLEET_ST.get(p.status.value, p.status.value),
            "cur": p.current_stage_order,
            "cur_name": "Yakunlandi" if p.status == ProductStatus.done
                        else stage_names.get(p.current_stage_order, "—"),
            "done": done, "pct": round(done / stage_total * 100),
            "worker": worker,
            "due": due, "created": p.created_at,
            "due_str": due_day.strftime("%d.%m.%Y") if (settings.bot_db and due_day) else None,
        })

    ql = (q or "").lower().strip()
    filtered = [
        r for r in rows
        if (status_enum is None or r["status"] == status_enum.value)
        and (not ql or ql in f'{r["code"]} {r["model"]} {r["color"]} {r["customer"]}'.lower())
    ]
    status_counts = {s.value: sum(r["status"] == s.value for r in rows) for s in ProductStatus}

    # ---- liniya kanban ustunlari ----
    _stage_icons = ["chassiscar", "truckbody", "layers", "spray", "window", "wrench",
                    "gauge", "hammer", "shieldcheck"]
    cycle_by_stage = {r["order_no"]: r["hours"] for r in await stats_svc.stage_cycle_times(session)}
    board = []
    for s in stages:
        board.append({
            "order": s.order_no,
            "name": s.name,
            "icon": _stage_icons[(s.order_no - 1) % len(_stage_icons)],
            "avg_h": cycle_by_stage.get(s.order_no, 0),
            "cards": [r for r in filtered
                      if r["cur"] == s.order_no and r["status"] in ("in_production", "qc_pending", "returned")],
        })
    done_cards = [r for r in filtered if r["status"] == "done"]
    if settings.bot_db:
        for col in board:
            col["workers"] = wk_by_order.get(col["order"], [])
            # ogohlantirish: ish qilinishi kerak bo'lgan truck bor, lekin bosqichda ishchi yo'q
            col["need_worker"] = not col["workers"] and any(
                c["status"] in ("in_production", "returned") for c in col["cards"]
            )

    def _pct(x: int) -> int:
        return round(x / len(rows) * 100) if rows else 0

    kpi5 = [
        {"label": "Jami trucklar", "value": len(rows), "sub": "100% jami", "icon": "foodtruck", "tone": "violet"},
        {"label": "Ishlab chiqarishda", "value": status_counts["in_production"],
         "sub": f"{_pct(status_counts['in_production'])}% jami", "icon": "gear", "tone": "blue"},
        {"label": "QC kutmoqda", "value": status_counts["qc_pending"],
         "sub": f"{_pct(status_counts['qc_pending'])}% jami", "icon": "shield", "tone": "amber"},
        {"label": "Qaytarilgan", "value": status_counts["returned"],
         "sub": f"{_pct(status_counts['returned'])}% jami", "icon": "back", "tone": "red"},
        {"label": "Tayyor", "value": status_counts["done"],
         "sub": f"{_pct(status_counts['done'])}% jami", "icon": "check", "tone": "green"},
    ]
    fleet_kpis = await stats_svc.extra_kpis(session)

    if sort == "deadline":  # tayyor bo'lmaganlar, muddati eng yaqini birinchi; muddatsizlar oxirida
        _far = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
        list_rows = sorted(
            [r for r in filtered if r["status"] not in ("done", "cancelled")],
            key=lambda r: ((r["due"] is None), (r["due"].astimezone(dt.timezone.utc) if r["due"] and r["due"].tzinfo
                                                else (r["due"].replace(tzinfo=dt.timezone.utc) if r["due"] else _far)), r["code"]),
        )
    else:
        list_rows = sorted(filtered, key=lambda r: (r["status"] == "done", r["cur"], r["code"]))

    return await page(
        "products.html", request, session,
        active="products", view=view, sort=sort, board=board, done_cards=done_cards, kpi5=kpi5,
        rows=list_rows, stage_total=stage_total,
        total_count=len(rows), shown=len(filtered),
        status_counts=status_counts, cur_status=status or "", query=q or "",
        fleet_kpis=fleet_kpis,
    )



# --------------------------------------------------------------------------- #
# Model katalogi va web'dan truck yaratish (faqat bot rejimida)
# --------------------------------------------------------------------------- #
import re as _re2
import urllib.parse as _urlp

_SERIAL_RE = _re2.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


def _redir(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


@app.get("/models", response_class=HTMLResponse)
async def models_page(
    request: Request, edit: int | None = None, msg: str = "",
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    models = await factory_svc.list_models(session)
    usage = {}
    if settings.bot_db:
        usage = {m: c for m, c in (await session.execute(
            select(Product.model, func.count()).group_by(Product.model))).all()}
    editing = next((m for m in models if m.id == edit), None)
    return await page("models.html", request, session, active="models", models=models,
                      usage=usage, editing=editing, msg=msg)


@app.post("/models")
async def models_save(
    id: int | None = Form(None), name: str = Form(""), description: str = Form(""),
    size_m: str = Form(""), color: str = Form(""), remove_image: str = Form(""),
    image: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    name = name.strip()
    if not name:
        return _redir("/models?msg=" + _urlp.quote("Model nomini kiriting"))
    card = await factory_svc.get_model(session, id) if id else None
    dup = await factory_svc.get_model_by_name(session, name)
    if dup is not None and (card is None or dup.id != card.id):
        return _redir("/models?msg=" + _urlp.quote(f"«{name}» nomli model allaqachon bor"))
    if card is None:
        card = ModelCard(name=name)
        session.add(card)
    card.name = name
    card.description = description.strip() or None
    card.size_m = int(size_m) if size_m.strip().isdigit() else None
    card.color = color.strip() or None

    data = await image.read() if image is not None and image.filename else b""
    if data:
        try:
            new_file = factory_svc.save_image(data)
        except ValueError as exc:
            await session.rollback()
            return _redir("/models?msg=" + _urlp.quote(str(exc)))
        factory_svc.delete_image(card.image_file)
        card.image_file, card.tg_file_id = new_file, None
    elif remove_image and card.image_file:
        factory_svc.delete_image(card.image_file)
        card.image_file, card.tg_file_id = None, None
    await session.commit()
    return _redir("/models?msg=" + _urlp.quote("Saqlandi ✅"))


@app.post("/models/{model_id}/toggle")
async def models_toggle(model_id: int, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    card = await factory_svc.get_model(session, model_id)
    if card is not None:
        card.is_active = not card.is_active
        await session.commit()
    return _redir("/models")


@app.post("/models/{model_id}/delete")
async def models_delete(model_id: int, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    card = await factory_svc.get_model(session, model_id)
    if card is not None:
        factory_svc.delete_image(card.image_file)
        await session.delete(card)
        await session.commit()
    return _redir("/models?msg=" + _urlp.quote("O‘chirildi"))


@app.get("/media/model/{model_id}")
async def model_image(model_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    if not valid(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/login", status_code=302)
    card = await factory_svc.get_model(session, model_id)
    path = abs_path(card.image_file) if card and card.image_file else None
    if path is not None and path.is_file():
        return FileResponse(str(path))
    return Response(content=_MEDIA_PLACEHOLDER, media_type="image/svg+xml")


@app.get("/media/user/{user_id}")
async def user_photo(user_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    """Ishchining ro'yxatdan o'tishda yuborgan selfisi (botning diskidan yoki Telegram'dan)."""
    if not valid(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/login", status_code=302)
    from sqlalchemy import text as _text

    row = (await session.execute(
        _text("SELECT photo_path, photo_file_id FROM web.users WHERE id = :i"), {"i": user_id}
    )).first() if settings.bot_db else None
    path = resolve_local(row[0]) if row and row[0] else None
    if path is None and row and row[1]:
        path = await telegram_cached(row[1])
    if path is not None:
        return FileResponse(str(path), media_type=guess_type(path))
    return Response(content=_MEDIA_PLACEHOLDER, media_type="image/svg+xml")


async def _new_truck_ctx(session: AsyncSession) -> dict:
    models = await factory_svc.list_models(session, only_active=True)
    serials = {m.name: await factory_svc.suggest_serial(session, m.name) for m in models}
    imgs = await factory_svc.image_map(session)
    meta = {m.name: {"img": imgs.get(m.name), "ds": m.description or "", "serial": serials[m.name]}
            for m in models}
    return {"models": models, "serials": serials, "imgs": imgs, "meta": meta,
            "priorities": factory_svc.PRIORITIES, "priority_label": factory_svc.PRIORITY_LABEL}


@app.get("/products/new", response_class=HTMLResponse)
async def product_new_form(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    if not settings.bot_db:
        return RedirectResponse("/products", status_code=302)
    ctx = await _new_truck_ctx(session)
    return await page("product_new.html", request, session, active="products", error="", form={}, **ctx)


@app.post("/products/new")
async def product_create(
    request: Request, model: str = Form(""), serial: str = Form(""), customer: str = Form(""),
    priority: str = Form("normal"), deadline: str = Form(""), notify: str = Form(""),
    count: str = Form("1"),
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    if not settings.bot_db:
        return RedirectResponse("/products", status_code=302)
    form = {"model": model, "serial": serial, "customer": customer, "priority": priority,
            "deadline": deadline, "notify": notify, "count": count}

    async def fail(msg: str):
        ctx = await _new_truck_ctx(session)
        return await page("product_new.html", request, session, active="products",
                          error=msg, form=form, **ctx)

    card = await factory_svc.get_model_by_name(session, model)
    if card is None or not card.is_active:
        return await fail("Modelni tanlang (avval «Modellar» bo‘limida model qo‘shing)")
    model_name = card.name   # rollback'dan keyin card "eskiradi" — nomini oldindan saqlab qo'yamiz
    n = int(count) if count.strip().isdigit() else 1
    if not 1 <= n <= 10:
        return await fail("Soni 1 dan 10 gacha bo‘lishi kerak")
    manual = serial.strip()
    if manual and n > 1:
        return await fail("Bir nechta truck buyurtma qilinganda seriya raqamini bo‘sh qoldiring — har biriga avtomatik noyob raqam beriladi")
    if manual and not _SERIAL_RE.match(manual):
        return await fail("Seriya raqami: faqat harf, raqam, nuqta, tire (32 belgigacha)")
    try:
        due = dt.date.fromisoformat(deadline) if deadline.strip() else None
    except ValueError:
        return await fail("Muddat sanasi noto‘g‘ri")
    serials: list[str] = []
    try:
        for _i in range(n):
            s_i = manual or await factory_svc.suggest_serial(session, model_name)
            await factory_svc.create_truck(session, serial=s_i, model=model_name,
                                           customer=customer.strip() or None, priority=priority, deadline=due)
            serials.append(s_i)
    except factory_svc.DuplicateSerial:
        nxt = await factory_svc.suggest_serial(session, model_name)
        if serials:  # bir nechtasi yaratilib, keyingisi to'qnashdi (kamdan-kam)
            return await fail(f"{len(serials)} ta yaratildi, lekin «{s_i}» raqami band bo‘lib qoldi. Sahifani yangilab qayta urinib ko‘ring.")
        return await fail(
            f"«{manual}» seriyali truck allaqachon bor. Har bir truckning seriya raqami noyob bo‘ladi. "
            f"Bir xil modeldan yana buyurtma berish uchun seriya maydonini bo‘sh qoldiring — tizim o‘zi «{nxt}» kabi keyingi raqamni beradi."
        )
    _SIDE_CACHE["counts"] = None  # yon paneldagi sanoqlar darrov yangilansin
    serial = serials[0] if n == 1 else f"{serials[0]} … {serials[-1]}"

    q = {"created": 1, "n": n, "sent": 0, "failed": 0}
    if notify:
        recips = await factory_svc.recipients(session)
        res = await telegram_notify.notify_new_order(
            recips, model=card.name, serial=serial, customer=customer.strip() or None,
            priority=priority, deadline=due.isoformat() if due else None, description=card.description,
            count=n, image=factory_svc.read_image(card),
            image_name=(card.image_file or "model.jpg").rsplit("/", 1)[-1], tg_file_id=card.tg_file_id)
        if res["file_id"] and res["file_id"] != card.tg_file_id:
            card.tg_file_id = res["file_id"]
            await session.commit()
        q.update(sent=res["sent"], failed=res["failed"])
        if res.get("error"):
            q["err"] = str(res["error"])[:120]
    else:
        q["notified"] = 0
    return _redir(f"/products/{_urlp.quote(serials[0])}?" + _urlp.urlencode(q))


@app.get("/products/{code}", response_class=HTMLResponse)
async def product_detail(
    code: str, request: Request, created: int = 0, n: int = 1, sent: int = 0, failed: int = 0, err: str = "",
    notified: int = 1, session: AsyncSession = Depends(get_session), _=Depends(require_login)
):
    product = await products_svc.get_by_code(session, code)
    if product is None:
        return HTMLResponse("Topilmadi", status_code=404)
    runs = await products_svc.timeline(session, product)
    total = await stages_svc.active_count(session)
    all_stages = await stages_svc.list_stages(session)
    by_stage: dict[int, list] = {}
    for r in runs:
        by_stage.setdefault(r.stage_order, []).append(r)
    return await page(
        "product_detail.html", request, session,
        active="products", heading=product.code,
        product=product, runs=runs, total=total, stages=all_stages, by_stage=by_stage,
        flash={"created": created, "n": n, "sent": sent, "failed": failed, "err": err, "notified": notified},
        model_card=(await factory_svc.get_model_by_name(session, product.model)) if settings.bot_db else None,
        model_img=(await factory_svc.image_map(session)).get(product.model or "") if settings.bot_db else None,
    )


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #
@app.get("/stages", response_class=HTMLResponse)
async def stages_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    if settings.bot_db:  # bot rejimida ma'lumot Trucklar (ustunlar) va Ishchilar sahifalarida
        return RedirectResponse("/products", status_code=302)
    stages = await stages_svc.list_stages(session)
    checks = {s.id: await stages_svc.list_check_items(session, s.id) for s in stages}
    info: dict[int, dict] = {}
    if settings.bot_db:  # botda tekshiruv ro'yxati yo'q — o'rniga ishchilar va hozirgi yuklama
        workers = (await session.scalars(
            select(User).where(User.role == Role.worker, User.is_active.is_(True)).order_by(User.full_name)
        )).all()
        live = (await session.execute(
            select(Product.current_stage_order, Product.status, func.count())
            .where(Product.status != ProductStatus.done)
            .group_by(Product.current_stage_order, Product.status)
        )).all()
        done = dict((await session.execute(
            select(StageRun.stage_order, func.count(func.distinct(StageRun.product_id)))
            .where(StageRun.status == StageRunStatus.approved).group_by(StageRun.stage_order)
        )).all())
        for s in stages:
            counts = {st.value: c for o, st, c in live if o == s.order_no}
            info[s.id] = {
                "workers": [w.full_name for w in workers if w.stage_id == s.id],
                "work": counts.get("in_production", 0), "qc": counts.get("qc_pending", 0),
                "ret": counts.get("returned", 0), "done": int(done.get(s.order_no, 0)),
            }
    return await page("stages.html", request, session, active="stages", stages=stages, checks=checks, info=info)


# --------------------------------------------------------------------------- #
# Workers
# --------------------------------------------------------------------------- #
@app.get("/workers", response_class=HTMLResponse)
async def workers_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    rows = await stats_svc.worker_productivity(session)
    groups: list[dict] = []
    if settings.bot_db:
        # Jamoa (bosqich) bo'yicha: natija shu bosqichdagi barcha tasdiq/qaytarishlardan olinadi,
        # ishchi qatorlarida esa faqat ishni yuborgan kishi hisobiga tushgan ishlar.
        stages = await stages_svc.list_stages(session)
        team = {(o, st): c for o, st, c in (await session.execute(
            select(StageRun.stage_order, StageRun.status, func.count())
            .where(StageRun.status.in_((StageRunStatus.approved, StageRunStatus.returned)))
            .group_by(StageRun.stage_order, StageRun.status)
        )).all()}
        for s in stages:
            ap = int(team.get((s.order_no, StageRunStatus.approved), 0))
            rt = int(team.get((s.order_no, StageRunStatus.returned), 0))
            groups.append({
                "order": s.order_no, "name": s.name, "approved": ap, "returned": rt,
                "pct": round(ap / (ap + rt) * 100) if ap + rt else None,
                "members": [r for r in rows if r["stage_order"] == s.order_no],
            })
        loose = [r for r in rows if r["stage_order"] is None]
        if loose:
            groups.append({"order": None, "name": "Bosqichga biriktirilmagan", "approved": None,
                           "returned": None, "pct": None, "members": loose})
    return await page("workers.html", request, session, active="workers", rows=rows, groups=groups)


# --------------------------------------------------------------------------- #
# Sifat nazorati
# --------------------------------------------------------------------------- #
@app.get("/qc", response_class=HTMLResponse)
async def qc_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    queue = await products_svc.qc_queue(session)
    recent = await products_svc.qc_recent(session, limit=30)
    return await page("qc.html", request, session, active="qc", queue=queue, recent=recent)


# --------------------------------------------------------------------------- #
# Hisobotlar
# --------------------------------------------------------------------------- #
@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    defects = await stats_svc.defects(session, limit=100)
    top_failed = await stats_svc.top_failed_checks(session, limit=15)
    max_fail = max([f["count"] for f in top_failed] + [1])
    workers = await stats_svc.worker_productivity(session)
    audit = list(
        (await session.scalars(
            select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(60)
        )).all()
    )
    # audit qatorlarida ichki raqam o'rniga truckning modeli/seriyasi ko'rsatilsin
    pids = {a.product_id for a in audit if a.product_id}
    prod_map = {
        p.id: p for p in (await session.scalars(select(Product).where(Product.id.in_(pids)))).all()
    } if pids else {}
    return await page(
        "reports.html", request, session, active="reports",
        defects=defects, top_failed=top_failed, max_fail=max_fail, workers=workers, audit=audit,
        prod_map=prod_map,
    )


@app.get("/defects", response_class=HTMLResponse)
async def defects_redirect():
    return RedirectResponse("/reports", status_code=302)


@app.get("/audit", response_class=HTMLResponse)
async def audit_redirect():
    return RedirectResponse("/reports", status_code=302)


# --------------------------------------------------------------------------- #
# Ogohlantirishlar
# --------------------------------------------------------------------------- #
@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    rows = await dash_svc.alerts(session)
    return await page("alerts.html", request, session, active="alerts", rows=rows)


# --------------------------------------------------------------------------- #
# KPI va tahlillar
# --------------------------------------------------------------------------- #
@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    d = await dash_svc.build(session)
    dy = d["dyn"]
    dyn_svg = Markup(charts.dynamics(dy["labels"], dy["plan"], dy["fact"], dy["ready"], width=900, height=280))
    trend = await stats_svc.daily_throughput(session, days=30)
    # Nol kunlarni yashiramiz: bo'sh oralig'i katta line grafik o'rniga faol kunlar trendi.
    active_days = [
        (label, created, finished)
        for label, created, finished in zip(trend["labels"], trend["created"], trend["finished"])
        if created or finished
    ]
    if not active_days:
        active_days = list(zip(trend["labels"][-7:], trend["created"][-7:], trend["finished"][-7:]))
    bar_svg = Markup(charts.stacked_bars(
        [label for label, _, _ in active_days],
        [
            {"name": "Yaratilgan", "color": "var(--c-blue)", "values": [x[1] for x in active_days]},
            {"name": "Tayyor", "color": "var(--c-green)", "values": [x[2] for x in active_days]},
        ],
        height=185,
    ))
    cyc = await stats_svc.stage_cycle_times(session)
    max_cyc = max([c["hours"] for c in cyc] + [1])
    bottleneck = max(cyc, key=lambda c: c["hours"], default=None)
    return await page(
        "analytics.html", request, session, active="analytics",
        d=d, dyn_svg=dyn_svg, bar_svg=bar_svg, cyc=cyc, max_cyc=max_cyc,
        bottleneck=bottleneck,
    )


# --------------------------------------------------------------------------- #
# Kalendar
# --------------------------------------------------------------------------- #
_MONTHS_UZ = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul",
              "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]
_WD_UZ = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(
    request: Request, month: str | None = None, day: str | None = None,
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    today = dt.datetime.now(_TZ).date()
    try:
        y, m = (int(x) for x in month.split("-")) if month else (today.year, today.month)
        dt.date(y, m, 1)
    except (ValueError, AttributeError):
        y, m = today.year, today.month

    cal = await stats_svc.month_calendar(session, y, m)
    events = await dash_svc.day_feed(session, day) if day else []
    prev_m = dt.date(y, m, 1) - dt.timedelta(days=1)
    next_m = dt.date(y, m, 1) + dt.timedelta(days=32)
    return await page(
        "calendar.html", request, session, active="calendar",
        cal=cal, sel_day=day, events=events, today=today.isoformat(),
        month_label=f"{_MONTHS_UZ[m - 1]} {y}",
        prev_month=f"{prev_m.year}-{prev_m.month:02d}",
        next_month=f"{next_m.year}-{next_m.month:02d}",
        weekdays=_WD_UZ,
    )


# --------------------------------------------------------------------------- #
# Fayllar
# --------------------------------------------------------------------------- #
@app.get("/files", response_class=HTMLResponse)
async def files_page(
    request: Request, stage: int | None = None, type: str | None = None,
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    items = await stats_svc.media_library(session, stage_order=stage, mtype=type)
    counts = await stats_svc.media_counts(session)
    stages = await stages_svc.list_stages(session)
    return await page(
        "files.html", request, session, active="files",
        items=items, counts=counts, stages=stages,
        cur_stage=stage or "", cur_type=type or "",
    )


# --------------------------------------------------------------------------- #
# Sozlamalar
# --------------------------------------------------------------------------- #
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    cfg = await stats_svc.config_overview(session)
    bot_name = await telegram_notify.bot_username() if settings.bot_db else None
    return await page("settings.html", request, session, active="settings", cfg=cfg, bot_name=bot_name)


_MEDIA_PLACEHOLDER = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="180" viewBox="0 0 240 180">'
    '<rect width="240" height="180" fill="#eef1f5"/>'
    '<g fill="none" stroke="#9aa3b4" stroke-width="3">'
    '<rect x="70" y="58" width="100" height="72" rx="8"/>'
    '<circle cx="120" cy="94" r="20"/><path d="M96 58l10-14h28l10 14"/></g>'
    '<text x="120" y="158" text-anchor="middle" font-family="Arial" font-size="13" fill="#9aa3b4">rasm</text>'
    "</svg>"
)


@app.get("/media/{media_id}")
async def media_file(media_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    if not valid(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/login", status_code=302)
    m = await session.get(Media, media_id)
    path = resolve_local(m.file_path) if m else None
    if path is None and m is not None and m.telegram_file_id:
        path = await telegram_cached(m.telegram_file_id)
    if path is not None:
        # FileResponse Range so'rovlarini qo'llaydi — video brauzerda to'g'ridan-to'g'ri o'ynaydi.
        return FileResponse(str(path), media_type=guess_type(path))
    # Fayl yo'q (masalan Vercel'da media saqlanmaydi) — chiroyli o'rin egallovchi.
    return Response(content=_MEDIA_PLACEHOLDER, media_type="image/svg+xml")
