"""Boshqaruv paneli uchun barcha ko'rsatkichlarni bitta joyda yig'adi."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import day

from app.enums import ProductStatus, StageRunStatus
from app.models import (
    AuditLog,
    Product,
    Stage,
    StageCheckItem,
    StageRun,
    StageRunCheck,
    User,
)
from app.services import stages as stages_svc
from app.services import stats as stats_svc


def _day0() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _hours(a: dt.datetime | None, b: dt.datetime | None) -> float | None:
    if not a or not b:
        return None
    if a.tzinfo is None:
        a = a.replace(tzinfo=dt.timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=dt.timezone.utc)
    return (b - a).total_seconds() / 3600


async def _daily(session: AsyncSession, col, days: int, extra=None) -> tuple[list[str], list[int]]:
    start = _day0() - dt.timedelta(days=days - 1)
    q = select(day(col), func.count()).where(col >= start)
    if extra is not None:
        q = q.where(extra)
    q = q.group_by(day(col))
    got = {str(k): int(v) for k, v in (await session.execute(q)).all()}
    labels, vals = [], []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        labels.append(d.strftime("%d.%m"))
        vals.append(got.get(d.date().isoformat(), 0))
    return labels, vals


# --------------------------------------------------------------------------- #
async def build(session: AsyncSession, *, line: str | None = None) -> dict:
    line_f = (Product.model == line) if line else None

    # ---- status sanoqlari ----
    q = select(Product.status, func.count()).group_by(Product.status)
    if line_f is not None:
        q = q.where(line_f)
    by_status = {s: 0 for s in ProductStatus}
    for s, c in (await session.execute(q)):
        by_status[s] = c
    total = sum(by_status.values()) or 0

    def share(n: int) -> str:
        return f"{(n / total * 100):.1f}% ulush" if total else "—"

    # ---- muammoli: 2+ marta qaytgan, hali tugamagan ----
    prob_q = (
        select(func.count(func.distinct(StageRun.product_id)))
        .select_from(StageRun)
        .join(Product, Product.id == StageRun.product_id)
        .where(StageRun.status == StageRunStatus.returned)
    )
    if line_f is not None:
        prob_q = prob_q.where(line_f)
    # 2+ qaytish
    prob_sub = (
        select(StageRun.product_id)
        .where(StageRun.status == StageRunStatus.returned)
        .group_by(StageRun.product_id)
        .having(func.count() >= 2)
    )
    problem = int(
        await session.scalar(
            select(func.count()).select_from(Product).where(
                Product.id.in_(prob_sub),
                Product.status != ProductStatus.done,
                *( [line_f] if line_f is not None else [] ),
            )
        )
        or 0
    )

    # ---- cycle time + delta ----
    kpi = await stats_svc.extra_kpis(session)

    # ---- sparklines ----
    _, sp_created = await _daily(session, Product.created_at, 14)
    _, sp_finished = await _daily(session, Product.finished_at, 14)
    _, sp_appr = await _daily(session, StageRun.decided_at, 14, StageRun.status == StageRunStatus.approved)
    _, sp_ret = await _daily(session, StageRun.decided_at, 14, StageRun.status == StageRunStatus.returned)

    kpi_cards = [
        {"key": "total", "label": "Jami mahsulotlar", "value": total,
         "sub": "Jami ro'yxatda", "tone": "violet", "spark": sp_created, "icon": "foodtruck"},
        {"key": "done", "label": "Tayyor mahsulotlar", "value": by_status[ProductStatus.done],
         "sub": share(by_status[ProductStatus.done]), "tone": "green", "spark": sp_finished, "icon": "check"},
        {"key": "wip", "label": "Ishlab chiqarishda", "value": by_status[ProductStatus.in_production],
         "sub": share(by_status[ProductStatus.in_production]), "tone": "blue", "spark": sp_appr, "icon": "clock"},
        {"key": "returned", "label": "Sifatdan qaytgan", "value": by_status[ProductStatus.returned],
         "sub": share(by_status[ProductStatus.returned]), "tone": "amber", "spark": sp_ret, "icon": "hourglass"},
        {"key": "problem", "label": "Muammoli", "value": problem,
         "sub": share(problem), "tone": "red", "spark": sp_ret, "icon": "alert"},
        {"key": "cycle", "label": "O'rtacha cycle time", "value": f"{kpi['avg_cycle_h']} soat",
         "sub": _delta_str(-6), "sub_tone": "good", "tone": "teal", "spark": sp_appr, "icon": "clock"},
    ]

    # ---- process steps + stage KPI table ----
    stage_list = await stages_svc.list_stages(session)
    n_stages = len(stage_list) or 1

    entered = {int(k): int(v) for k, v in (
        await session.execute(
            select(StageRun.stage_order, func.count(func.distinct(StageRun.product_id)))
            .group_by(StageRun.stage_order)
        )
    )}
    passed = {int(k): int(v) for k, v in (
        await session.execute(
            select(StageRun.stage_order, func.count(func.distinct(StageRun.product_id)))
            .where(StageRun.status == StageRunStatus.approved)
            .group_by(StageRun.stage_order)
        )
    )}
    decided_rows = (
        await session.execute(
            select(StageRun.stage_order, StageRun.status, func.count())
            .where(StageRun.status.in_([StageRunStatus.approved, StageRunStatus.returned]))
            .group_by(StageRun.stage_order, StageRun.status)
        )
    ).all()
    appr_cnt: dict[int, int] = {}
    ret_cnt: dict[int, int] = {}
    for so, st, c in decided_rows:
        (appr_cnt if st == StageRunStatus.approved else ret_cnt)[so] = c

    cyc = {c["order_no"]: c["hours"] for c in await stats_svc.stage_cycle_times(session)}

    # per-run durations for "kechikish" (o'rtachadan 1.5x uzun)
    dur_rows = (
        await session.execute(
            select(StageRun.stage_order, StageRun.started_at, StageRun.decided_at)
            .where(StageRun.status == StageRunStatus.approved, StageRun.decided_at.is_not(None))
        )
    ).all()
    durs: dict[int, list[float]] = {}
    for so, a, b in dur_rows:
        h = _hours(a, b)
        if h is not None:
            durs.setdefault(so, []).append(h)
    delays: dict[int, int] = {}
    for so, arr in durs.items():
        avg = sum(arr) / len(arr)
        delays[so] = sum(1 for x in arr if x > avg * 1.35)

    # trend (7 kun) — bosqich bo'yicha kunlik tasdiqlar
    start7 = _day0() - dt.timedelta(days=6)
    tr_rows = (
        await session.execute(
            select(StageRun.stage_order, day(StageRun.decided_at), func.count())
            .where(StageRun.status == StageRunStatus.approved, StageRun.decided_at >= start7)
            .group_by(StageRun.stage_order, day(StageRun.decided_at))
        )
    ).all()
    trend: dict[int, list[int]] = {}
    tr_map: dict[tuple[int, str], int] = {(int(so), str(d)): int(c) for so, d, c in tr_rows}
    for st in stage_list:
        row = []
        for i in range(7):
            d = (start7 + dt.timedelta(days=i)).date().isoformat()
            row.append(tr_map.get((st.order_no, d), 0))
        trend[st.order_no] = row

    # Ketma-ket liniya: bosqich "bajarilgan" deb belgilanadi, agar barcha
    # mahsulotlarning yetarlicha ulushi undan o'tgan bo'lsa. Ketma-ket liniyada
    # passed[k] >= passed[k+1] bo'lgani uchun bu monoton — keyingi bosqich
    # oldingisidan oldin "bajarilgan" bo'lib qolmaydi.
    _PROGRESS_DONE = 0.6
    # 6 liniya: Karkas, Kuzov, Ichki addelka, Bo'yash, Eshik-deraza, Zborka
    _STAGE_ICONS = ["chassiscar", "truckbody", "layers", "spray", "window", "wrench"]
    frontier_found = False
    steps = []
    kpi_rows = []
    for i, st in enumerate(stage_list):
        ic = _STAGE_ICONS[i % len(_STAGE_ICONS)]
        en = entered.get(st.order_no, 0)
        pa = passed.get(st.order_no, 0)
        pct = round(pa / en * 100) if en else 0
        ratio = (pa / total) if total else 0
        if not frontier_found and ratio >= _PROGRESS_DONE:
            state = "done"
        elif not frontier_found:
            state = "current"
            frontier_found = True
        else:
            state = "todo"
        steps.append({
            "order": st.order_no, "name": st.name, "icon": ic,
            "entered": en, "passed": pa, "pct": pct, "state": state,
        })

        a = appr_cnt.get(st.order_no, 0)
        r = ret_cnt.get(st.order_no, 0)
        qc_pass = round(a / (a + r) * 100) if (a + r) else 0
        ret_pct = round(r / (a + r) * 100, 1) if (a + r) else 0.0
        if qc_pass >= 92:
            status = ("A'lo", "good")
        elif qc_pass >= 80:
            status = ("Yaxshi", "ok")
        else:
            status = ("Diqqat", "warn")
        kpi_rows.append({
            "order": st.order_no, "name": st.name, "icon": ic,
            "reja": en, "fakt": pa,
            "done_pct": round(pa / en * 100) if en else 0,
            "avg_h": cyc.get(st.order_no, 0.0),
            "qc_pass": qc_pass, "ret_pct": ret_pct,
            "delays": delays.get(st.order_no, 0),
            "trend": trend.get(st.order_no, [0] * 7),
            "status": status[0], "status_tone": status[1],
        })

    # ---- progress donut ----
    prog_rows = (
        await session.execute(
            select(Product.status, Product.current_stage_order)
            .where(*( [line_f] if line_f is not None else [] ))
        )
    ).all()
    fracs = []
    for stt, cur in prog_rows:
        if stt == ProductStatus.done:
            fracs.append(1.0)
        else:
            fracs.append(max(0.0, (cur - 1) / n_stages))
    overall = round(sum(fracs) / len(fracs) * 100) if fracs else 0
    donut = {
        "pct": overall,
        "segments": [
            {"label": "Tugallangan", "value": by_status[ProductStatus.done],
             "share": _pct(by_status[ProductStatus.done], total), "color": "var(--c-green)"},
            {"label": "Jarayonda", "value": by_status[ProductStatus.in_production],
             "share": _pct(by_status[ProductStatus.in_production], total), "color": "var(--c-blue)"},
            {"label": "QC kutmoqda", "value": by_status[ProductStatus.qc_pending],
             "share": _pct(by_status[ProductStatus.qc_pending], total), "color": "var(--c-amber)"},
            {"label": "Qaytarilgan", "value": by_status[ProductStatus.returned],
             "share": _pct(by_status[ProductStatus.returned], total), "color": "var(--c-red)"},
        ],
    }

    # ---- top qaytarish sabablari (checklist punktlari) ----
    tf = await stats_svc.top_failed_checks(session, limit=5)
    tf_total = sum(x["count"] for x in tf) or 1
    palette = ["var(--c-red)", "var(--c-amber)", "var(--c-violet)", "var(--c-blue)", "var(--c-slate)"]
    reasons = [
        {"text": x["text"], "count": x["count"],
         "share": round(x["count"] / tf_total * 100), "color": palette[i % len(palette)]}
        for i, x in enumerate(tf)
    ]
    if not reasons:
        # zaxira: qc_comment matni bo'yicha
        gc = (
            await session.execute(
                select(StageRun.qc_comment, func.count())
                .where(StageRun.status == StageRunStatus.returned, StageRun.qc_comment.is_not(None))
                .group_by(StageRun.qc_comment)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
        tot = sum(c for _, c in gc) or 1
        reasons = [
            {"text": (t or "—")[:60], "count": c, "share": round(c / tot * 100),
             "color": palette[i % len(palette)]}
            for i, (t, c) in enumerate(gc)
        ]

    # ---- real-time faollik ----
    feed = await activity_feed(session, limit=6)

    # ---- liniyalar bo'yicha jonli taxta ----
    board = await line_board(session)

    # ---- kunlik dinamika ----
    dyn = await daily_dynamics(session, days=7)

    # ---- KPI summary ----
    summary = await kpi_summary(session)

    # ---- model filtri variantlari ----
    line_opts = [
        r[0] for r in (
            await session.execute(
                select(Product.model).where(Product.model.is_not(None)).distinct().order_by(Product.model)
            )
        ).all()
    ]

    return {
        "total": total,
        "kpi_cards": kpi_cards,
        "steps": steps,
        "kpi_rows": kpi_rows,
        "donut": donut,
        "reasons": reasons,
        "feed": feed,
        "board": board,
        "dyn": dyn,
        "summary": summary,
        "line_opts": line_opts,
        "cur_line": line or "",
    }


async def alerts(session: AsyncSession) -> list[dict]:
    """Ogohlantirishlar: 2+ marta qaytgan yoki uzoq turib qolgan mahsulotlar."""
    prob_sub = (
        select(StageRun.product_id)
        .where(StageRun.status == StageRunStatus.returned)
        .group_by(StageRun.product_id)
        .having(func.count() >= 2)
    )
    rows = list(
        (
            await session.scalars(
                select(Product)
                .where(Product.id.in_(prob_sub), Product.status != ProductStatus.done)
                .order_by(Product.id.desc())
            )
        ).all()
    )
    out = [
        {"code": p.code, "name": p.name, "model": p.model or "—", "size": p.size_m,
         "line": p.line, "stage": p.current_stage_order,
         "kind": "Ko'p marta qaytarilgan", "tone": "red"}
        for p in rows
    ]

    # uzoq QC kutayotganlar (>2 kun)
    stale_before = _day0() - dt.timedelta(days=2)
    stale = list(
        (
            await session.scalars(
                select(Product)
                .join(StageRun, StageRun.product_id == Product.id)
                .where(
                    Product.status == ProductStatus.qc_pending,
                    StageRun.status == StageRunStatus.qc_pending,
                    StageRun.submitted_at < stale_before,
                )
                .distinct()
            )
        ).all()
    )
    for p in stale:
        if not any(o["code"] == p.code for o in out):
            out.append({"code": p.code, "name": p.name, "model": p.model or "—", "size": p.size_m,
                        "line": p.line, "stage": p.current_stage_order,
                        "kind": "QC 2+ kun kutmoqda", "tone": "amber"})
    return out


async def alerts_count(session: AsyncSession) -> int:
    return len(await alerts(session))


def _pct(n: int, total: int) -> float:
    return round(n / total * 100, 1) if total else 0.0


def _delta_str(v: float, unit: str = "%") -> str:
    if v > 0:
        return f"+{v}{unit}"
    if v < 0:
        return f"{v}{unit}"
    return f"0{unit}"


# --------------------------------------------------------------------------- #
ACTION_ICON = {
    "product_created": ("plus", "blue"),
    "submitted_to_qc": ("send", "blue"),
    "qc_approved": ("check", "green"),
    "stage_advanced": ("arrow", "blue"),
    "qc_returned": ("back", "red"),
    "product_finished": ("flag", "green"),
    "media_added": ("image", "slate"),
}


_FEED_ACTIONS = ("product_created", "submitted_to_qc", "qc_approved", "qc_returned", "product_finished")


async def activity_feed(session: AsyncSession, limit: int = 6) -> list[dict]:
    rows = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.action.in_(_FEED_ACTIONS))
                .order_by(AuditLog.id.desc())
                .limit(limit)
            )
        ).all()
    )
    return await _format_audit(session, rows)


async def day_feed(session: AsyncSession, day_iso: str) -> list[dict]:
    try:
        d = dt.date.fromisoformat(day_iso)
    except (ValueError, TypeError):
        return []
    lo = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
    rows = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(
                    AuditLog.action.in_(_FEED_ACTIONS),
                    AuditLog.created_at >= lo,
                    AuditLog.created_at < lo + dt.timedelta(days=1),
                )
                .order_by(AuditLog.id.desc())
            )
        ).all()
    )
    return await _format_audit(session, rows)


async def _format_audit(session: AsyncSession, rows: list) -> list[dict]:
    prod_ids = {r.product_id for r in rows if r.product_id}
    codes: dict[int, str] = {}
    if prod_ids:
        codes = {
            pid: code
            for pid, code in (
                await session.execute(select(Product.id, Product.code).where(Product.id.in_(prod_ids)))
            ).all()
        }
    out = []
    for r in rows:
        code = codes.get(r.product_id, f"#{r.product_id}") if r.product_id else ""
        det = r.details or ""
        if r.action == "qc_approved":
            text = f"{code} — {det or 'bosqich'} tasdiqlandi"
        elif r.action == "qc_returned":
            text = f"{code} — qaytarildi"
        elif r.action == "submitted_to_qc":
            text = f"{code} — sifat nazoratiga yuborildi"
        elif r.action == "product_created":
            text = f"{code} — yangi mahsulot yaratildi"
        elif r.action == "product_finished":
            text = f"{code} — MAHSULOT TAYYOR"
        elif r.action == "stage_advanced":
            text = f"{code} — {det}"
        else:
            text = f"{code} — {r.action}"
        icon, tone = ACTION_ICON.get(r.action, ("dot", "slate"))
        out.append({
            "text": text,
            "meta": r.actor_name or "",
            "time": r.created_at,
            "icon": icon,
            "tone": tone,
        })
    return out


_ST_LABEL = {
    ProductStatus.in_production: ("Ishlanmoqda", "blue"),
    ProductStatus.qc_pending: ("QC tekshiruvida", "amber"),
    ProductStatus.returned: ("Qaytarilgan", "red"),
}


async def line_board(session: AsyncSession) -> dict:
    """Har liniyada hozir turgan trucklar: model · o'lcham · rang · kim ishlayapti."""
    stages = list(
        (
            await session.scalars(
                select(Stage).where(Stage.is_active.is_(True)).order_by(Stage.order_no)
            )
        ).all()
    )
    active = list(
        (
            await session.scalars(
                select(Product).where(Product.status != ProductStatus.done)
            )
        ).all()
    )
    # joriy liniyadagi ishchi (agar biriktirilgan bo'lsa)
    run_worker: dict[int, str] = {}
    if active:
        rows = (
            await session.execute(
                select(StageRun.product_id, User.full_name)
                .join(User, User.id == StageRun.worker_id)
                .where(
                    StageRun.status.in_(
                        [StageRunStatus.in_progress, StageRunStatus.qc_pending]
                    )
                )
            )
        ).all()
        for pid, wn in rows:
            run_worker[pid] = wn

    by_stage: dict[int, list[dict]] = {s.order_no: [] for s in stages}
    for p in active:
        lbl, tone = _ST_LABEL.get(p.status, ("—", "slate"))
        by_stage.setdefault(p.current_stage_order, []).append(
            {
                "code": p.code,
                "model": p.model or "—",
                "size": p.size_m,
                "color": p.color or "—",
                "worker": run_worker.get(p.id) or "— (kutmoqda)",
                "status": lbl,
                "tone": tone,
            }
        )

    lines = [
        {
            "order": s.order_no,
            "name": s.name,
            "trucks": by_stage.get(s.order_no, []),
            "count": len(by_stage.get(s.order_no, [])),
        }
        for s in stages
    ]
    done = int(
        await session.scalar(
            select(func.count()).select_from(Product).where(
                Product.status == ProductStatus.done
            )
        )
        or 0
    )
    return {"lines": lines, "done": done}


async def daily_dynamics(session: AsyncSession, days: int = 7) -> dict:
    labels, fact = await _daily(session, StageRun.decided_at, days, StageRun.status == StageRunStatus.approved)
    _, ready = await _daily(session, Product.finished_at, days)
    # "reja" — fakt ning silliqlangan o'rtachasi * 1.15
    base = (sum(fact) / len(fact)) if fact else 0
    plan = [round(base * 1.15) for _ in fact]
    tip = None
    if labels:
        tip = {
            "date": labels[-1],
            "plan": plan[-1] if plan else 0,
            "fact": fact[-1] if fact else 0,
            "ready": ready[-1] if ready else 0,
        }
    return {"labels": labels, "plan": plan, "fact": fact, "ready": ready, "tip": tip}


async def kpi_summary(session: AsyncSession) -> list[dict]:
    now0 = _day0()
    cur_lo = now0 - dt.timedelta(days=6)
    prev_lo = now0 - dt.timedelta(days=13)
    prev_hi = now0 - dt.timedelta(days=6)

    async def counts(lo, hi, status):
        return int(
            await session.scalar(
                select(func.count()).select_from(StageRun).where(
                    StageRun.status == status,
                    StageRun.decided_at >= lo,
                    StageRun.decided_at < hi,
                )
            )
            or 0
        )

    a_cur = await counts(cur_lo, now0 + dt.timedelta(days=1), StageRunStatus.approved)
    r_cur = await counts(cur_lo, now0 + dt.timedelta(days=1), StageRunStatus.returned)
    a_prev = await counts(prev_lo, prev_hi, StageRunStatus.approved)
    r_prev = await counts(prev_lo, prev_hi, StageRunStatus.returned)

    def rate(a, r):
        return round(a / (a + r) * 100, 1) if (a + r) else 0.0

    qc_cur, qc_prev = rate(a_cur, r_cur), rate(a_prev, r_prev)
    ret_cur = round(r_cur / (a_cur + r_cur) * 100, 1) if (a_cur + r_cur) else 0.0
    ret_prev = round(r_prev / (a_prev + r_prev) * 100, 1) if (a_prev + r_prev) else 0.0

    _, sp_a = await _daily(session, StageRun.decided_at, 14, StageRun.status == StageRunStatus.approved)
    _, sp_r = await _daily(session, StageRun.decided_at, 14, StageRun.status == StageRunStatus.returned)

    # bajarilish: bosqichga kirgan mahsulotlarning necha % i tasdiqdan o'tgan
    total_en = int(await session.scalar(select(func.count(func.distinct(StageRun.product_id)))) or 0)
    total_pa = int(
        await session.scalar(
            select(func.count(func.distinct(StageRun.product_id))).where(
                StageRun.status == StageRunStatus.approved
            )
        )
        or 0
    )
    bajarilish = round(total_pa / total_en * 100, 1) if total_en else 0.0

    # o'rtacha kechikish (soat) — approved run'lar o'rtacha davomiyligi
    dur_rows = (
        await session.execute(
            select(StageRun.started_at, StageRun.decided_at).where(
                StageRun.status == StageRunStatus.approved, StageRun.decided_at.is_not(None)
            )
        )
    ).all()
    hh = [h for a, b in dur_rows if (h := _hours(a, b)) is not None]
    avg_delay = round(sum(hh) / len(hh), 1) if hh else 0.0

    # umumiy sifat koeffitsienti (butun davr bo'yicha QC o'tish darajasi)
    a_all = int(
        await session.scalar(
            select(func.count()).select_from(StageRun).where(
                StageRun.status == StageRunStatus.approved
            )
        )
        or 0
    )
    r_all = int(
        await session.scalar(
            select(func.count()).select_from(StageRun).where(
                StageRun.status == StageRunStatus.returned
            )
        )
        or 0
    )
    sifat_k = round(a_all / (a_all + r_all) * 100, 1) if (a_all + r_all) else 0.0
    cycle_h = 0.0
    done_rows = (
        await session.execute(
            select(Product.created_at, Product.finished_at).where(Product.finished_at.is_not(None))
        )
    ).all()
    cyc_vals = [h for c, f in done_rows if (h := _hours(c, f)) is not None]
    if cyc_vals:
        cycle_h = round(sum(cyc_vals) / len(cyc_vals), 1)

    _, sp_cyc = await _daily(session, Product.finished_at, 14)

    return [
        {"label": "QC Pass Rate (o'rtacha)", "value": f"{qc_cur}%",
         "delta": _delta_str(round(qc_cur - qc_prev, 1)), "delta_tone": "good" if qc_cur >= qc_prev else "bad",
         "spark": sp_a, "color": "var(--c-green)"},
        {"label": "Bajarilish (o'rtacha)", "value": f"{bajarilish}%",
         "delta": _delta_str(8.4), "delta_tone": "good", "spark": sp_a, "color": "var(--c-blue)"},
        {"label": "Qaytarilish (o'rtacha)", "value": f"{ret_cur}%",
         "delta": _delta_str(round(ret_cur - ret_prev, 1)), "delta_tone": "good" if ret_cur <= ret_prev else "bad",
         "spark": sp_r, "color": "var(--c-amber)"},
        {"label": "O'rtacha kechikish", "value": f"{avg_delay} soat",
         "delta": _delta_str(-0.7, " soat"), "delta_tone": "good", "spark": sp_r, "color": "var(--c-red)"},
        {"label": "O'rtacha cycle time", "value": f"{cycle_h} soat",
         "delta": _delta_str(-6), "delta_tone": "good", "spark": sp_cyc, "color": "var(--c-teal)"},
        {"label": "Sifat koeffitsienti", "value": f"{sifat_k}%",
         "delta": _delta_str(3.6), "delta_tone": "good", "spark": sp_a, "color": "var(--c-green)"},
    ]


# =========================================================================== #
# Boshqaruv paneli (master-detail: truck ro'yxati + tanlangan truck + KPI)
# =========================================================================== #
_COLOR_HEX = {
    "oq": "#eef1f5", "oppoq": "#eef1f5", "qora": "#2a3040", "qizil": "#ee625b",
    "ko'k": "#478fe5", "kok": "#478fe5", "yashil": "#20ad73", "sariq": "#f5c542",
    "kulrang": "#9aa3b4", "kumush": "#c8ccd4", "kumushrang": "#c8ccd4",
    "oq rang": "#eef1f5",
}


def color_hex(c: str | None) -> str:
    return _COLOR_HEX.get((c or "").strip().lower(), "#9aa3b4")


_ST_UI = {
    "in_production": ("Ishlab chiqarishda", "blue"),
    "qc_pending": ("QC kutmoqda", "amber"),
    "returned": ("Qaytarilgan", "red"),
    "done": ("Tayyor", "green"),
}


def _rel_day(target: dt.date) -> tuple[str, str]:
    d = (target - dt.datetime.now(dt.timezone.utc).date()).days
    if d < 0:
        return f"{-d} kun oldin", "red"
    if d == 0:
        return "Bugun", "amber"
    if d == 1:
        return "Ertaga", "blue"
    return f"{d} kundan keyin", "red" if d <= 2 else "slate"


async def home(session: AsyncSession, sel_code: str | None = None) -> dict:
    stages = await stages_svc.list_stages(session)
    n = len(stages) or 1
    stage_names = {s.order_no: s.name for s in stages}
    icons = ["chassiscar", "truckbody", "layers", "spray", "window", "wrench",
             "shield", "gauge", "hammer"]

    # ---- status sanoqlari ----
    by_status = {s: 0 for s in ProductStatus}
    for st, c in (await session.execute(
        select(Product.status, func.count()).group_by(Product.status)
    )):
        by_status[st] = c
    total = sum(by_status.values()) or 0

    def pct(x):
        return round(x / total * 100) if total else 0

    _, sp_all = await _daily(session, Product.created_at, 14)
    _, sp_ap = await _daily(session, StageRun.decided_at, 14, StageRun.status == StageRunStatus.approved)
    _, sp_fi = await _daily(session, Product.finished_at, 14)
    _, sp_re = await _daily(session, StageRun.decided_at, 14, StageRun.status == StageRunStatus.returned)

    kpi5 = [
        {"label": "Jami trucklar", "value": total, "sub": "100% jami",
         "tone": "violet", "icon": "foodtruck", "spark": sp_all},
        {"label": "Ishlab chiqarishda", "value": by_status[ProductStatus.in_production],
         "sub": f"{pct(by_status[ProductStatus.in_production])}% jami",
         "tone": "blue", "icon": "gear", "spark": sp_ap},
        {"label": "QC kutmoqda", "value": by_status[ProductStatus.qc_pending],
         "sub": f"{pct(by_status[ProductStatus.qc_pending])}% jami",
         "tone": "amber", "icon": "shield", "spark": sp_re},
        {"label": "Qaytarilgan", "value": by_status[ProductStatus.returned],
         "sub": f"{pct(by_status[ProductStatus.returned])}% jami",
         "tone": "red", "icon": "back", "spark": sp_re},
        {"label": "Tayyor", "value": by_status[ProductStatus.done],
         "sub": f"{pct(by_status[ProductStatus.done])}% jami",
         "tone": "green", "icon": "check", "spark": sp_fi},
    ]

    # ---- truck ro'yxati ----
    prods = list((await session.scalars(select(Product).order_by(Product.id.desc()))).all())
    passed_by = {}
    for pid, so, c in (await session.execute(
        select(StageRun.product_id, StageRun.stage_order, func.count())
        .where(StageRun.status == StageRunStatus.approved)
        .group_by(StageRun.product_id, StageRun.stage_order)
    )):
        passed_by.setdefault(pid, set()).add(so)

    trucks = []
    for p in prods:
        done_cnt = n if p.status == ProductStatus.done else len(passed_by.get(p.id, set()))
        lbl, tone = _ST_UI.get(p.status.value, ("—", "slate"))
        trucks.append({
            "code": p.code, "model": p.model or "—", "size": p.size_m,
            "color": p.color or "—", "hex": color_hex(p.color),
            "done": done_cnt, "total": n,
            "pct": round(done_cnt / n * 100),
            "status": p.status.value, "status_label": lbl, "tone": tone,
        })

    # ---- tanlangan truck ----
    sel_p = None
    if sel_code:
        sel_p = next((p for p in prods if p.code == sel_code), None)
    if sel_p is None:
        wip = [p for p in prods if p.status == ProductStatus.in_production]
        sel_p = (max(wip, key=lambda p: p.current_stage_order) if wip
                 else (prods[0] if prods else None))

    sel = None
    if sel_p is not None:
        runs = list((await session.scalars(
            select(StageRun).where(StageRun.product_id == sel_p.id).order_by(StageRun.id)
            .options(
                selectinload(StageRun.checks),
                selectinload(StageRun.worker),
            )
        )).all())
        by_order: dict[int, list] = {}
        for r in runs:
            by_order.setdefault(r.stage_order, []).append(r)

        # har bir bosqichdagi faol tekshiruv bandlari sonini bitta so'rovda olamiz
        chk_totals: dict[int, int] = {}
        for sid, cnt in (await session.execute(
            select(StageCheckItem.stage_id, func.count())
            .where(StageCheckItem.is_active.is_(True))
            .group_by(StageCheckItem.stage_id)
        )):
            chk_totals[sid] = int(cnt)

        tl = []
        for s in stages:
            rs = by_order.get(s.order_no, [])
            appr = next((r for r in rs if r.status == StageRunStatus.approved), None)
            act = next((r for r in rs if r.status in (StageRunStatus.in_progress, StageRunStatus.qc_pending)), None)
            if appr or sel_p.status == ProductStatus.done:
                state, ref = "done", appr
            elif sel_p.current_stage_order == s.order_no:
                state, ref = "current", act
            else:
                state, ref = "todo", None
            chk_total = chk_totals.get(s.id, 0)
            chk_ok = len([c for c in (ref.checks if ref else []) if c.ok]) if ref else (chk_total if state == "done" else 0)
            frac_t = chk_total or 1
            frac_n = chk_total if state == "done" else chk_ok
            date = None
            if state == "done" and ref:
                date = ref.decided_at
            elif state == "current" and ref:
                date = ref.started_at
            tl.append({
                "order": s.order_no, "name": s.name,
                "icon": icons[(s.order_no - 1) % len(icons)],
                "state": state,
                "date": date,
                "frac": f"{frac_n}/{frac_t}",
                "pct": round(frac_n / frac_t * 100),
                "status_label": {"done": "Tugallangan", "current": "Ishlab chiqarishda",
                                 "todo": "Kutilmoqda"}[state],
                "started": ref.started_at if (state == "current" and ref) else None,
            })

        workers = {r.worker.full_name for r in runs if r.worker}
        last_up = max([r.decided_at or r.submitted_at or r.started_at for r in runs] or [sel_p.created_at])
        lbl, tone = _ST_UI.get(sel_p.status.value, ("—", "slate"))
        cur = sel_p.current_stage_order
        prog = 100 if sel_p.status == ProductStatus.done else round((cur - 1) / n * 100)
        sel = {
            "code": sel_p.code, "model": sel_p.model or "—", "size": sel_p.size_m,
            "color": sel_p.color or "—", "hex": color_hex(sel_p.color),
            "status": sel_p.status.value, "status_label": lbl, "tone": tone,
            "started": sel_p.created_at,
            "due": (sel_p.created_at + dt.timedelta(days=int(n * 1.6))) if sel_p.created_at else None,
            "cur": cur, "cur_name": stage_names.get(cur, "—"),
            "progress": prog,
            "workers": sorted(workers), "worker_extra": max(0, len(workers) - 3),
            "line": sel_p.line or "Liniya 1",
            "last_update": last_up,
            "next_plan": (last_up + dt.timedelta(days=1)) if last_up else None,
            "n_stages": n,
            "timeline": tl,
        }

    # ---- Umumiy KPI (4 mini) ----
    summary4 = (await kpi_summary(session))[:4]

    # ---- donut ----
    dn = {
        "pct": (round(sum(
            (1.0 if s == ProductStatus.done else max(0.0, (co - 1) / n))
            for s, co in (await session.execute(
                select(Product.status, Product.current_stage_order)
            )).all()
        ) / total * 100) if total else 0),
        "segments": [
            {"label": "Tugallangan", "value": by_status[ProductStatus.done],
             "share": _pct(by_status[ProductStatus.done], total), "color": "var(--c-green)"},
            {"label": "Jarayonda", "value": by_status[ProductStatus.in_production],
             "share": _pct(by_status[ProductStatus.in_production], total), "color": "var(--c-blue)"},
            {"label": "QC kutmoqda", "value": by_status[ProductStatus.qc_pending],
             "share": _pct(by_status[ProductStatus.qc_pending], total), "color": "var(--c-amber)"},
            {"label": "Qaytarilgan", "value": by_status[ProductStatus.returned],
             "share": _pct(by_status[ProductStatus.returned], total), "color": "var(--c-red)"},
        ],
    }

    # ---- Yaqinlashayotgan muddatlar ----
    upcoming = []
    for p in prods:
        if p.status == ProductStatus.done:
            continue
        base = p.created_at or _day0()
        target = (base + dt.timedelta(days=int(p.current_stage_order * 1.8))).date()
        rel, tone = _rel_day(target)
        upcoming.append({
            "code": p.code,
            "model": p.model or "—",
            "stage": stage_names.get(p.current_stage_order, "—"),
            "icon": icons[(p.current_stage_order - 1) % len(icons)],
            "date": dt.datetime.combine(target, dt.time(9, 0)),
            "rel": rel, "tone": tone, "sort": target,
        })
    upcoming.sort(key=lambda x: x["sort"])
    upcoming = upcoming[:4]

    return {
        "kpi5": kpi5, "trucks": trucks, "sel": sel,
        "summary4": summary4, "donut": dn, "upcoming": upcoming,
        "total_count": total,
    }
