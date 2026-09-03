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
    os.environ["MEDIA_ROOT"] = "/tmp/media"
    os.environ.setdefault("SHOW_ERRORS", "1")

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal, init_db
from app.enums import PRODUCT_STATUS_LABEL, ROLE_LABEL, ProductStatus, StageRunStatus
from app.models import AuditLog, Media, Product, StageRun, User
from app.services import dashboard as dash_svc
from app.services import products as products_svc
from app.services import stages as stages_svc
from app.services import stats as stats_svc
from app.services.media_store import abs_path, ensure_root
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


def _avatar_url(name: str | None) -> str:
    """Ishchi surati: static/avatars/1..N.(jpg|png|webp) fayllardan biri (ism bo'yicha barqaror).
    Fayllar bo'lmasa — offline generatsiya qilingan SVG avatar."""
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
templates.env.globals["avatar_url"] = _avatar_url
templates.env.globals["avatar_svg"] = _avatar_svg
templates.env.globals["PRODUCT_STATUS_LABEL"] = PRODUCT_STATUS_LABEL
templates.env.globals["ROLE_LABEL"] = ROLE_LABEL
templates.env.globals["ProductStatus"] = ProductStatus
templates.env.globals["ACTION_LABEL"] = _ACTION_LABEL

app = FastAPI(title="Baaz — Ishlab chiqarish nazorati")
install_redirect_handler(app)

_static = BASE_DIR / "static"
try:
    _static.mkdir(exist_ok=True)
except OSError:  # read-only FS (Vercel)
    pass
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

_SKIP_INIT = os.getenv("SKIP_INIT_DB", "").lower() in ("1", "true", "yes")
_AUTO_SEED = os.getenv("AUTO_SEED", "").lower() in ("1", "true", "yes")
_log = __import__("logging").getLogger("web")

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
    if _AUTO_SEED:
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


_SHOW_ERRORS = os.getenv("SHOW_ERRORS", "1").lower() in ("1", "true", "yes")


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


async def page(name: str, request: Request, session: AsyncSession, **ctx):
    ctx.setdefault("now_str", dt.datetime.now(_TZ).strftime("%d.%m.%Y"))
    if "alerts_list" not in ctx or "alerts_count" not in ctx:
        _al = await dash_svc.alerts(session)
        ctx.setdefault("alerts_count", len(_al))
        ctx.setdefault("alerts_list", _al[:6])
    ctx.setdefault("side_counts", await _side_counts(session))
    return templates.TemplateResponse(name, {"request": request, **ctx})


def render(name: str, request: Request, **ctx):
    ctx.setdefault("now_str", dt.datetime.now(_TZ).strftime("%d.%m.%Y"))
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


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    if password != settings.web_password:
        return render("login.html", request, error="Parol noto'g'ri")
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE_NAME, make_token(), httponly=True, samesite="lax", max_age=60 * 60 * 12)
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
    request: Request, sel: str | None = None,
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    d = await dash_svc.home(session, sel_code=sel or None)
    truck_images = [
        "/static/trucks/trailer-orange.png",
        "/static/trucks/trailer-blue.png",
        "/static/trucks/trailer-green.png",
        "/static/trucks/trailer-cream.png",
    ]
    image_by_code = {
        truck["code"]: truck_images[index % len(truck_images)]
        for index, truck in enumerate(d["trucks"])
    }
    for truck in d["trucks"]:
        truck["image"] = image_by_code[truck["code"]]
    if d["sel"]:
        d["sel"]["image"] = image_by_code.get(d["sel"]["code"], truck_images[0])

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
    return await page("index.html", request, session, active="dash", d=d, donut_svg=donut_svg)


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
_TRUCK_IMAGES = [
    "/static/trucks/trailer-orange.png",
    "/static/trucks/trailer-blue.png",
    "/static/trucks/trailer-green.png",
    "/static/trucks/trailer-cream.png",
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
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    view = "list" if view == "list" else "line"
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

    today = dt.datetime.now(_TZ).date()
    rows = []
    for idx, p in enumerate(all_items):
        done = stage_total if p.status == ProductStatus.done else done_by_id.get(p.id, 0)
        due = p.created_at + dt.timedelta(days=int(stage_total * 1.6)) if p.created_at else None
        overdue = bool(
            due and due.date() < today
            and p.status not in (ProductStatus.done, ProductStatus.cancelled)
        )
        rows.append({
            "overdue": overdue,
            "code": p.code, "model": p.model or "—", "size": p.size_m,
            "color": p.color or "—", "hex": dash_svc.color_hex(p.color),
            "image": _TRUCK_IMAGES[idx % len(_TRUCK_IMAGES)],
            "status": p.status.value, "status_label": _FLEET_ST.get(p.status.value, p.status.value),
            "cur": p.current_stage_order,
            "cur_name": "Yakunlandi" if p.status == ProductStatus.done
                        else stage_names.get(p.current_stage_order, "—"),
            "done": done, "pct": round(done / stage_total * 100),
            "worker": worker_by_id.get(p.id, "—"),
            "due": due, "created": p.created_at,
        })

    ql = (q or "").lower().strip()
    filtered = [
        r for r in rows
        if (status_enum is None or r["status"] == status_enum.value)
        and (not ql or ql in f'{r["code"]} {r["model"]} {r["color"]}'.lower())
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

    list_rows = sorted(filtered, key=lambda r: (r["status"] == "done", r["cur"], r["code"]))

    return await page(
        "products.html", request, session,
        active="products", view=view, board=board, done_cards=done_cards, kpi5=kpi5,
        rows=list_rows, stage_total=stage_total,
        total_count=len(rows), shown=len(filtered),
        status_counts=status_counts, cur_status=status or "", query=q or "",
        fleet_kpis=fleet_kpis,
    )


@app.get("/products/{code}", response_class=HTMLResponse)
async def product_detail(
    code: str, request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)
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
    )


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #
@app.get("/stages", response_class=HTMLResponse)
async def stages_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    stages = await stages_svc.list_stages(session)
    checks = {s.id: await stages_svc.list_check_items(session, s.id) for s in stages}
    return await page("stages.html", request, session, active="stages", stages=stages, checks=checks)


# --------------------------------------------------------------------------- #
# Workers
# --------------------------------------------------------------------------- #
@app.get("/workers", response_class=HTMLResponse)
async def workers_page(request: Request, session: AsyncSession = Depends(get_session), _=Depends(require_login)):
    rows = await stats_svc.worker_productivity(session)
    return await page("workers.html", request, session, active="workers", rows=rows)


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
        (await session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(60))).all()
    )
    return await page(
        "reports.html", request, session, active="reports",
        defects=defects, top_failed=top_failed, max_fail=max_fail, workers=workers, audit=audit,
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
    return await page("settings.html", request, session, active="settings", cfg=cfg)


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
    path = abs_path(m.file_path) if m else None
    if path is not None and path.exists():
        return FileResponse(str(path))
    # Fayl yo'q (masalan Vercel'da media saqlanmaydi) — chiroyli o'rin egallovchi.
    return Response(content=_MEDIA_PLACEHOLDER, media_type="image/svg+xml")
