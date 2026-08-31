import datetime as dt
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal, init_db
from app.enums import PRODUCT_STATUS_LABEL, ROLE_LABEL, ProductStatus
from app.models import AuditLog, Media, Product
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


templates.env.filters["dt"] = _fmt_dt
templates.env.filters["tm"] = _fmt_time
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
    ctx.setdefault("alerts_count", await dash_svc.alerts_count(session))
    ctx.setdefault("side_counts", await _side_counts(session))
    return templates.TemplateResponse(name, {"request": request, **ctx})


def render(name: str, request: Request, **ctx):
    ctx.setdefault("now_str", dt.datetime.now(_TZ).strftime("%d.%m.%Y"))
    ctx.setdefault("alerts_count", 0)
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

    for c in d["kpi5"]:
        col = _KPI_SPARK_COLOR.get(c["tone"], "var(--brand)")
        c["spark_svg"] = Markup(charts.sparkline(c["spark"], width=140, height=44, color=col, fill=True))
    for m in d["summary4"]:
        m["spark_svg"] = Markup(charts.sparkline(m["spark"], width=150, height=28, color=m["color"], fill=True))

    donut_svg = Markup(charts.donut(
        [(g["color"], g["value"]) for g in d["donut"]["segments"]],
        center_top=f"{d['donut']['pct']}%", center_bottom="Umumiy progress",
    ))
    return await page("index.html", request, session, active="dash", d=d, donut_svg=donut_svg)


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
@app.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request, status: str | None = None, stage: int | None = None, q: str | None = None,
    session: AsyncSession = Depends(get_session), _=Depends(require_login),
):
    status_enum = None
    if status:
        try:
            status_enum = ProductStatus(status)
        except ValueError:
            status_enum = None
    all_items = await products_svc.list_products(session, limit=300)
    items = [
        item for item in all_items
        if (status_enum is None or item.status == status_enum)
        and (stage is None or item.current_stage_order == stage)
        and (not q or q.lower() in " ".join(filter(None, [item.code, item.model, item.color])).lower())
    ]
    status_counts = {s.value: sum(item.status == s for item in all_items) for s in ProductStatus}
    stage_total = await stages_svc.active_count(session)
    return await page(
        "products.html", request, session,
        active="products", items=items, cur_status=status or "", cur_stage=stage or "", query=q or "",
        status_counts=status_counts, total_count=len(all_items), stage_total=stage_total or 1,
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
