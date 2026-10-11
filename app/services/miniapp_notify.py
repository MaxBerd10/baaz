"""Mini App'dagi harakatlar (yuborish, tasdiqlash, rad etish) uchun Telegram xabarlari.

Botning o'z xabarlari bilan bir xil vaziyatlar, lekin 3 tilda va xabar tagida «ilovada ochish» tugmasi bilan
(tugma shu ishning o'ziga olib boradi). Tunda (QUIET_FROM..QUIET_TO) xabarlar ovozsiz ketadi.
"""
from __future__ import annotations

import asyncio
import html
import os

from app.services.media_store import MEDIA_ROOT
from app.services.telegram_notify import PRIORITY, _api, quiet_now

MINIAPP_URL = os.getenv("MINIAPP_URL", "").rstrip("/")   # masalan: https://factory.baaztrucks.uz/app

STEPS = {
    "uz": ["Karkas", "Kuzov o'rnatish", "Ichki qoplama", "Bo'yash", "Eshik-deraza", "Yig'ish"],
    "uz_cyrl": ["Каркас", "Кузов ўрнатиш", "Ички қоплама", "Бўяш", "Эшик-дераза", "Йиғиш"],
    "ru": ["Каркас", "Установка кузова", "Внутренняя отделка", "Покраска", "Двери и окна", "Сборка"],
}

TX = {
    "uz": {
        "qc_new": "🔔 <b>Yangi ish keldi!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Bosqich: <b>{step}</b>\n👷 Ishchi: {worker}\n📎 Fayllar: {files} ta{note}\n\nTekshirish uchun ilovani oching 👇",
        "qc_btn": "📱 Tekshirish",
        "sent": "✅ <b>Ish yuborildi</b>\n\n🚛 {serial}\n🔧 {step}\n📎 Fayllar: {files} ta\n\nSifat nazoratchisi tekshiradi, natijani shu yerda yozamiz.",
        "approved": "✅ <b>Ishingiz tasdiqlandi!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Bosqich: <b>{step}</b>{next}",
        "next_line": "\n\n📍 Keyingi bosqich: <b>{step}</b>",
        "rejected": "❌ <b>Ishingiz rad etildi</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Bosqich: <b>{step}</b>\n\n📝 <b>Sabab:</b>\n<i>{reason}</i>\n\nTuzatib, qayta yuboring 👇",
        "resend_btn": "📱 Qayta yuborish",
        "task": "🔔 <b>Yangi vazifa!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Bosqich: <b>{step}</b>\n🎯 {priority}{deadline}\n\nIshni boshlash uchun ilovani oching 👇",
        "task_btn": "📱 Boshlash",
        "deadline": "\n📅 Muddat: {d}",
        "done": "🎉 <b>Truck tayyor!</b>\n\n🚛 {serial}\nBarcha 6 bosqich tasdiqlandi.",
        "note": "\n📝 Izoh: <i>{c}</i>",
    },
    "uz_cyrl": {
        "qc_new": "🔔 <b>Янги иш келди!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Босқич: <b>{step}</b>\n👷 Ишчи: {worker}\n📎 Файллар: {files} та{note}\n\nТекшириш учун иловани очинг 👇",
        "qc_btn": "📱 Текшириш",
        "sent": "✅ <b>Иш юборилди</b>\n\n🚛 {serial}\n🔧 {step}\n📎 Файллар: {files} та\n\nСифат назоратчиси текширади, натижани шу ерда ёзамиз.",
        "approved": "✅ <b>Ишингиз тасдиқланди!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Босқич: <b>{step}</b>{next}",
        "next_line": "\n\n📍 Кейинги босқич: <b>{step}</b>",
        "rejected": "❌ <b>Ишингиз рад этилди</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Босқич: <b>{step}</b>\n\n📝 <b>Сабаб:</b>\n<i>{reason}</i>\n\nТузатиб, қайта юборинг 👇",
        "resend_btn": "📱 Қайта юбориш",
        "task": "🔔 <b>Янги вазифа!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Босқич: <b>{step}</b>\n🎯 {priority}{deadline}\n\nИшни бошлаш учун иловани очинг 👇",
        "task_btn": "📱 Бошлаш",
        "deadline": "\n📅 Муддат: {d}",
        "done": "🎉 <b>Truck тайёр!</b>\n\n🚛 {serial}\nБарча 6 босқич тасдиқланди.",
        "note": "\n📝 Изоҳ: <i>{c}</i>",
    },
    "ru": {
        "qc_new": "🔔 <b>Пришла новая работа!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Этап: <b>{step}</b>\n👷 Рабочий: {worker}\n📎 Файлов: {files}{note}\n\nОткройте приложение для проверки 👇",
        "qc_btn": "📱 Проверить",
        "sent": "✅ <b>Работа отправлена</b>\n\n🚛 {serial}\n🔧 {step}\n📎 Файлов: {files}\n\nКонтролёр качества проверит, результат придёт сюда.",
        "approved": "✅ <b>Ваша работа принята!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Этап: <b>{step}</b>{next}",
        "next_line": "\n\n📍 Следующий этап: <b>{step}</b>",
        "rejected": "❌ <b>Работа отклонена</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Этап: <b>{step}</b>\n\n📝 <b>Причина:</b>\n<i>{reason}</i>\n\nИсправьте и отправьте снова 👇",
        "resend_btn": "📱 Отправить снова",
        "task": "🔔 <b>Новая задача!</b>\n\n🚛 Truck: <b>{serial}</b>\n🔧 Этап: <b>{step}</b>\n🎯 {priority}{deadline}\n\nОткройте приложение, чтобы начать 👇",
        "task_btn": "📱 Начать",
        "deadline": "\n📅 Срок: {d}",
        "done": "🎉 <b>Truck готов!</b>\n\n🚛 {serial}\nВсе 6 этапов приняты.",
        "note": "\n📝 Комментарий: <i>{c}</i>",
    },
}


def _lang(rec: dict | None) -> str:
    lg = (rec or {}).get("language")
    return lg if lg in TX else "uz"


def _step(lang: str, n: int) -> str:
    names = STEPS[lang]
    return names[n - 1] if 1 <= n <= len(names) else f"#{n}"


def _markup(label: str, query: str = "") -> dict | None:
    if not MINIAPP_URL:
        return None
    return {"inline_keyboard": [[{"text": label, "web_app": {"url": f"{MINIAPP_URL}{query}"}}]]}


async def _send(chat_id: int, text: str, markup: dict | None = None) -> bool:
    fields: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        fields["reply_markup"] = markup
    if quiet_now():
        fields["disable_notification"] = True
    r = await asyncio.to_thread(_api, "sendMessage", fields)
    return bool(r.get("ok"))


async def _send_file(chat_id: int, rel_path: str, kind: str, caption: str) -> str | None:
    """Faylni (rasm ≤10 MB, video ≤50 MB) ishchining chatiga yuboradi; Telegram file_id ni qaytaradi.
    Bu bot orqali tekshiruvchi QC ham rasmni ko'rishi uchun kerak (bot faqat file_id bilan ko'rsatadi)."""
    p = MEDIA_ROOT / rel_path
    try:
        size = p.stat().st_size
        ext = p.suffix.lower().lstrip(".")
        if kind == "photo" and ext in ("jpg", "png", "webp") and size <= 10 * 1024 * 1024:
            method, field, ctype = "sendPhoto", "photo", "image/jpeg" if ext == "jpg" else f"image/{ext}"
        elif kind == "video" and ext in ("mp4", "mov") and size <= 50 * 1024 * 1024:
            method, field, ctype = "sendVideo", "video", "video/mp4"
        else:
            return None
        data = await asyncio.to_thread(p.read_bytes)
    except OSError:
        return None
    fields = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    if quiet_now():
        fields["disable_notification"] = "true"
    r = await asyncio.to_thread(_api, method, fields, (p.name, ctype, data), 120, field)
    if not r.get("ok"):
        return None
    res = r.get("result") or {}
    if method == "sendPhoto":
        photos = res.get("photo") or []
        return photos[-1].get("file_id") if photos else None
    return (res.get("video") or {}).get("file_id")


def _e(s) -> str:
    return html.escape(str(s or ""))


async def on_submitted(info: dict, qcs: list[dict], worker: dict) -> str | None:
    """Ish yuborildi: QC larga xabar + ishchiga tasdiq (rasm bilan). Rasmning Telegram file_id ni qaytaradi."""
    for qc in qcs:
        lg = _lang(qc)
        t = TX[lg]
        note = t["note"].format(c=_e(info["comment"])) if info.get("comment") else ""
        await _send(qc["telegram_id"], t["qc_new"].format(
            serial=_e(info["serial"]), step=_e(_step(lg, info["step_number"])), worker=_e(info["worker"]),
            files=info["files"], note=note), _markup(t["qc_btn"], f"?go=step&id={info['step_id']}"))
    lg = _lang(worker)
    caption = TX[lg]["sent"].format(serial=_e(info["serial"]), step=_e(_step(lg, info["step_number"])), files=info["files"])
    file_id = await _send_file(worker["telegram_id"], info["primary_path"], info["primary_kind"], caption)
    if not file_id:
        await _send(worker["telegram_id"], caption)
    return file_id


async def on_approved(info: dict, worker: dict | None, next_workers: list[dict], admins: list[dict]) -> None:
    if worker:
        lg = _lang(worker)
        t = TX[lg]
        nxt = t["next_line"].format(step=_e(_step(lg, info["next_step"]))) if info.get("next_step") else ""
        await _send(worker["telegram_id"], t["approved"].format(
            serial=_e(info["serial"]), step=_e(_step(lg, info["step_number"])), next=nxt))
    if info["completed"]:
        for a in admins:
            lg = _lang(a)
            await _send(a["telegram_id"], TX[lg]["done"].format(serial=_e(info["serial"])))
        return
    for w in next_workers:
        lg = _lang(w)
        t = TX[lg]
        dl = t["deadline"].format(d=_e(str(info["deadline"])[:10])) if info.get("deadline") else ""
        await _send(w["telegram_id"], t["task"].format(
            serial=_e(info["serial"]), step=_e(_step(lg, info["next_step"])),
            priority=PRIORITY[lg].get(info.get("priority"), ""), deadline=dl),
            _markup(t["task_btn"], f"?go=step&id={info['next_step_id']}" if info.get("next_step_id") else ""))


async def on_rejected(info: dict, worker: dict | None) -> None:
    if not worker:
        return
    lg = _lang(worker)
    t = TX[lg]
    await _send(worker["telegram_id"], t["rejected"].format(
        serial=_e(info["serial"]), step=_e(_step(lg, info["step_number"])), reason=_e(info["reason"])),
        _markup(t["resend_btn"], f"?go=step&id={info['step_id']}"))


async def set_menu_button() -> bool:
    """Bot chatining pastki menyu tugmasini «📱 Ilova» ga o'rnatadi (hamma foydalanuvchi uchun)."""
    if not MINIAPP_URL:
        return False
    r = await asyncio.to_thread(_api, "setChatMenuButton", {
        "menu_button": {"type": "web_app", "text": "📱 Ilova", "web_app": {"url": MINIAPP_URL}}})
    return bool(r.get("ok"))


__all__ = ["on_submitted", "on_approved", "on_rejected", "set_menu_button", "MINIAPP_URL"]
