"""Tashqi kutubxonasiz, ichki SVG grafiklar. Ranglar CSS o'zgaruvchilaridan olinadi."""
from __future__ import annotations

import math

STATUS_COLOR = {
    "done": "var(--c-green)",
    "in_production": "var(--c-blue)",
    "qc_pending": "var(--c-amber)",
    "returned": "var(--c-red)",
    "cancelled": "var(--c-slate)",
}


def donut(segments: list[tuple[str, float]], center_top: str, center_bottom: str,
          size: int = 190, stroke: int = 24) -> str:
    """segments: [(color, value), ...]"""
    r = (size - stroke) / 2
    cx = cy = size / 2
    circ = 2 * math.pi * r
    total = sum(v for _, v in segments) or 1
    offset = 0.0
    arcs = []
    for color, value in segments:
        if value <= 0:
            continue
        seg = value / total * circ
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r:.2f}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="butt" '
            f'stroke-dasharray="{seg:.2f} {circ - seg:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})">'
            f'</circle>'
        )
        offset += seg
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" class="c-donut">'
        f'<circle cx="{cx}" cy="{cy}" r="{r:.2f}" fill="none" stroke="var(--c-track)" stroke-width="{stroke}"></circle>'
        f'{"".join(arcs)}'
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" class="c-donut-a">{center_top}</text>'
        f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" class="c-donut-b">{center_bottom}</text>'
        f'</svg>'
    )


def stacked_bars(cats: list[str], series: list[dict], height: int = 210) -> str:
    """cats: ['1','2',...]; series: [{'name','color','values':[..]}]"""
    n = len(cats)
    step = 46
    width = max(n * step, 60)
    pad_b, pad_t = 22, 8
    plot_h = height - pad_b - pad_t
    totals = [sum(s["values"][i] for s in series) for i in range(n)]
    maxv = max(totals + [1])
    bars = []
    bw = 22
    for i, cat in enumerate(cats):
        x = i * step + (step - bw) / 2
        y = pad_t + plot_h
        for s in series:
            v = s["values"][i]
            if v <= 0:
                continue
            h = v / maxv * plot_h
            y -= h
            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw}" height="{h:.1f}" '
                f'rx="3" fill="{s["color"]}"><title>{cat}: {v}</title></rect>'
            )
        bars.append(
            f'<text x="{i * step + step / 2:.1f}" y="{height - 6}" text-anchor="middle" '
            f'class="c-axis">{cat}</text>'
        )
        if totals[i]:
            bars.append(
                f'<text x="{i * step + step / 2:.1f}" y="{pad_t + plot_h - totals[i] / maxv * plot_h - 4:.1f}" '
                f'text-anchor="middle" class="c-axis c-axis-strong">{totals[i]}</text>'
            )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" '
        f'class="c-bars" height="{height}">{"".join(bars)}</svg>'
    )


def area_trend(labels: list[str], created: list[int], finished: list[int],
               width: int = 680, height: int = 200) -> str:
    n = len(labels)
    if n == 0:
        return ""
    pad_l, pad_r, pad_b, pad_t = 6, 6, 20, 10
    pw = width - pad_l - pad_r
    ph = height - pad_b - pad_t
    maxv = max(created + finished + [1])
    step = pw / max(n - 1, 1)

    def pts(data):
        return " ".join(
            f"{pad_l + i * step:.1f},{pad_t + ph - v / maxv * ph:.1f}"
            for i, v in enumerate(data)
        )

    c_pts, f_pts = pts(created), pts(finished)
    area = (
        f"{pad_l:.1f},{pad_t + ph:.1f} " + c_pts + f" {pad_l + (n - 1) * step:.1f},{pad_t + ph:.1f}"
    )
    grid = "".join(
        f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{pad_t + ph * k / 3:.1f}" '
        f'y2="{pad_t + ph * k / 3:.1f}" class="c-grid"/>'
        for k in range(4)
    )
    xlabels = ""
    for i, lb in enumerate(labels):
        if n <= 8 or i % max(n // 7, 1) == 0 or i == n - 1:
            xlabels += (
                f'<text x="{pad_l + i * step:.1f}" y="{height - 5}" text-anchor="middle" '
                f'class="c-axis">{lb}</text>'
            )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="c-area" height="{height}">'
        f'{grid}'
        f'<polygon points="{area}" fill="var(--c-blue)" opacity="0.12"/>'
        f'<polyline points="{c_pts}" fill="none" stroke="var(--c-blue)" stroke-width="2.5"/>'
        f'<polyline points="{f_pts}" fill="none" stroke="var(--c-green)" stroke-width="2.5"/>'
        f'{xlabels}'
        f'</svg>'
    )


def dynamics(labels: list[str], plan: list[int], fact: list[int], ready: list[int],
             width: int = 640, height: int = 230) -> str:
    n = len(labels)
    if n == 0:
        return ""
    # Chap o'q va ko'rsatkichlar grafikni raqamsiz "taxmin" qilishdan saqlaydi.
    pad_l, pad_r, pad_b, pad_t = 34, 16, 28, 18
    pw = width - pad_l - pad_r
    ph = height - pad_b - pad_t
    maxv = max(plan + fact + ready + [1])
    step = pw / max(n - 1, 1)

    def coords(data):
        return [(pad_l + i * step, pad_t + ph - v / maxv * ph) for i, v in enumerate(data)]

    def pts(data):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in coords(data))

    f_pts = pts(fact)
    area = f"{pad_l:.1f},{pad_t + ph:.1f} {f_pts} {pad_l + (n - 1) * step:.1f},{pad_t + ph:.1f}"
    grid = "".join(
        f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{pad_t + ph * k / 4:.1f}" '
        f'y2="{pad_t + ph * k / 4:.1f}" class="c-grid"/>'
        f'<text x="{pad_l - 8}" y="{pad_t + ph * k / 4 + 3:.1f}" text-anchor="end" class="c-axis">{round(maxv * (4-k) / 4)}</text>'
        for k in range(5)
    )
    xl = ""
    for i, lb in enumerate(labels):
        if n <= 8 or i % max(n // 7, 1) == 0 or i == n - 1:
            xl += (
                f'<text x="{pad_l + i * step:.1f}" y="{height - 5}" text-anchor="middle" '
                f'class="c-axis">{lb}</text>'
            )
    fact_dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.7" fill="#fff" stroke="var(--c-blue)" stroke-width="2"><title>{labels[i]}: {fact[i]} ta</title></circle>'
        for i, (x, y) in enumerate(coords(fact))
    )
    ready_dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="#fff" stroke="var(--c-green)" stroke-width="2"><title>{labels[i]}: {ready[i]} ta</title></circle>'
        for i, (x, y) in enumerate(coords(ready))
    )
    fx, fy = coords(fact)[-1]
    rx, ry = coords(ready)[-1]
    fact_label = f'<text x="{fx:.1f}" y="{max(pad_t + 10, fy - 10):.1f}" text-anchor="middle" class="c-value-label">{fact[-1]} ta</text>'
    ready_label = f'<text x="{rx:.1f}" y="{min(height - pad_b - 7, ry + 17):.1f}" text-anchor="middle" class="c-value-label c-value-green">{ready[-1]} ta</text>'
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="c-area" height="{height}">'
        f'<defs><linearGradient id="dyn-fact" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3b82f6" stop-opacity=".18"/><stop offset="1" stop-color="#3b82f6" stop-opacity="0"/></linearGradient></defs>'
        f'{grid}'
        f'<polygon points="{area}" fill="url(#dyn-fact)"/>'
        f'<polyline points="{pts(plan)}" fill="none" stroke="var(--c-slate)" stroke-width="2" stroke-dasharray="6 5"/>'
        f'<polyline points="{f_pts}" fill="none" stroke="var(--c-blue)" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<polyline points="{pts(ready)}" fill="none" stroke="var(--c-green)" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'{fact_dots}{ready_dots}{fact_label}{ready_label}'
        f'{xl}'
        f'</svg>'
    )


_SPARK_SEQ = 0


def sparkline(data: list[float], width: int = 150, height: int = 36,
              color: str = "var(--brand)", fill: bool = False) -> str:
    global _SPARK_SEQ
    if not data:
        return ""
    lo, hi = min(data), max(data)
    rng = (hi - lo) or 1
    step = width / max(len(data) - 1, 1)
    coords = [
        (i * step, height - 3 - (v - lo) / rng * (height - 8))
        for i, v in enumerate(data)
    ]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    grad = ""
    area = ""
    if fill:
        _SPARK_SEQ += 1
        gid = f"spg{_SPARK_SEQ}"
        grad = (
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{color}" stop-opacity="0.22"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/>'
            f'</linearGradient></defs>'
        )
        area = (
            f'<polygon points="0,{height} {pts} {width:.1f},{height}" fill="url(#{gid})"/>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'preserveAspectRatio="none" class="c-spark">'
        f'{grad}{area}'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )
