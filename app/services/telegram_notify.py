"""Web'dan Telegram'ga xabar yuborish (botning tokeni orqali, qo'shimcha kutubxonasiz).

Yangi buyurtma haqida hammaga (ishchi, QC, admin) o'z tilida xabar ketadi; model rasmi bo'lsa
rasm bilan. Rasm Telegram'ga bir marta yuklanadi, keyin `file_id` bilan yuboriladi.
"""
from __future__ import annotations

import asyncio
import html
import json
import urllib.error
import urllib.request
import uuid

from app.config import settings
from app.services.media_store import _TG_API

PRIORITY = {
    "uz": {"low": "🟢 Past", "normal": "🔵 Oddiy", "high": "🟠 Yuqori", "urgent": "🔴 Shoshilinch"},
    "uz_cyrl": {"low": "🟢 Паст", "normal": "🔵 Одатий", "high": "🟠 Юқори", "urgent": "🔴 Шошилинч"},
    "ru": {"low": "🟢 Низкий", "normal": "🔵 Обычный", "high": "🟠 Высокий", "urgent": "🔴 Срочный"},
}

T = {
    "uz": {
        "title": "🆕 <b>Yangi buyurtma keldi!</b>", "model": "Model", "serial": "Seriya",
        "customer": "Buyurtmachi", "priority": "Prioritet", "deadline": "Muddat",
        "step1": "Karkas", "tasks": "📋 Vazifalarim", "queue": "🔔 Tekshirish navbati",
        "worker1": "👷 1-bosqich (<b>{step}</b>) sizning navbatingiz. «{btn}» ni bosib ishni boshlang!",
        "worker": "ℹ️ Ish 1-bosqichdan ({step}) boshlanadi. Navbat sizga kelganda alohida xabar olasiz.",
        "qc": "🔍 Ish yuborilganda «{btn}» bo‘limida ko‘rinadi.",
        "admin": "👑 Jarayonni web panelda kuzatib boring.",
    },
    "uz_cyrl": {
        "title": "🆕 <b>Янги буюртма келди!</b>", "model": "Модель", "serial": "Серия",
        "customer": "Буюртмачи", "priority": "Приоритет", "deadline": "Муддат",
        "step1": "Каркас", "tasks": "📋 Вазифаларим", "queue": "🔔 Текшириш навбати",
        "worker1": "👷 1-босқич (<b>{step}</b>) сизнинг навбатингиз. «{btn}» ни босиб ишни бошланг!",
        "worker": "ℹ️ Иш 1-босқичдан ({step}) бошланади. Навбат сизга келганда алоҳида хабар оласиз.",
        "qc": "🔍 Иш юборилганда «{btn}» бўлимида кўринади.",
        "admin": "👑 Жараённи веб панелда кузатиб боринг.",
    },
    "ru": {
        "title": "🆕 <b>Поступил новый заказ!</b>", "model": "Модель", "serial": "Серия",
        "customer": "Заказчик", "priority": "Приоритет", "deadline": "Срок",
        "step1": "Каркас", "tasks": "📋 Мои задачи", "queue": "🔔 Очередь проверки",
        "worker1": "👷 Этап 1 (<b>{step}</b>) — ваша очередь. Нажмите «{btn}» и начинайте работу!",
        "worker": "ℹ️ Работа начинается с этапа 1 ({step}). Когда дойдёт очередь, придёт отдельное сообщение.",
        "qc": "🔍 Когда работу отправят, она появится в «{btn}».",
        "admin": "👑 Следите за процессом в веб-панели.",
    },
}


def _api(method: str, fields: dict, file: tuple[str, str, bytes] | None = None, timeout: int = 20) -> dict:
    """Telegram Bot API chaqiruvi (sinxron; asyncio.to_thread ichida ishlatiladi)."""
    url = f"{_TG_API}/bot{settings.bot_token}/{method}"
    if file:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        fname, ctype, data = file
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{fname}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(fields).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except Exception:  # noqa: BLE001
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001 — tarmoq xatosi
        return {"ok": False, "description": str(e)[:120]}


QTY = {"uz": "Soni", "uz_cyrl": "Сони", "ru": "Количество"}
QTY_UNIT = {"uz": "ta", "uz_cyrl": "та", "ru": "шт."}


def build_text(rec: dict, *, model: str, serial: str, customer: str | None, priority: str,
               deadline: str | None, description: str | None, count: int = 1) -> str:
    lang = rec.get("language") if rec.get("language") in T else "uz"
    t = T[lang]
    e = html.escape
    lines = [t["title"], "", f"🚛 {t['model']}: <b>{e(model)}</b>"]
    if count > 1:
        lines.append(f"🔢 {QTY[lang]}: <b>{count} {QTY_UNIT[lang]}</b>")
    lines.append(f"🔖 {t['serial']}: <b>{e(serial)}</b>")
    if customer:
        lines.append(f"👤 {t['customer']}: {e(customer)}")
    lines.append(f"🎯 {t['priority']}: {PRIORITY[lang].get(priority, priority)}")
    if deadline:
        lines.append(f"📅 {t['deadline']}: {e(deadline)}")
    if description:
        lines += ["", f"📝 <i>{e(description[:300])}</i>"]
    lines.append("")
    role, step = rec.get("role"), rec.get("step_number")
    if role == "worker" and step == 1:
        lines.append(t["worker1"].format(step=t["step1"], btn=t["tasks"]))
    elif role == "worker":
        lines.append(t["worker"].format(step=t["step1"]))
    elif role == "qc":
        lines.append(t["qc"].format(btn=t["queue"]))
    else:
        lines.append(t["admin"])
    return "\n".join(lines)


async def notify_new_order(
    recips: list[dict], *, model: str, serial: str, customer: str | None, priority: str,
    deadline: str | None, description: str | None, count: int = 1,
    image: bytes | None = None, image_name: str = "model.jpg", tg_file_id: str | None = None,
) -> dict:
    """Hammaga yangi buyurtma xabarini yuboradi. {sent, failed, total, file_id, error} qaytaradi."""
    out = {"sent": 0, "failed": 0, "total": len(recips), "file_id": tg_file_id, "error": None}
    if not settings.bot_token:
        out.update(failed=len(recips), error="BOT_TOKEN sozlanmagan")
        return out

    ctype = {"png": "image/png", "webp": "image/webp"}.get(image_name.rsplit(".", 1)[-1], "image/jpeg")

    async def call(method: str, fields: dict, file: tuple | None = None) -> dict:
        """Telegram so'rovi; «Too Many Requests» (429) bo'lsa kutib, ikki martagacha qayta uriniladi."""
        r: dict = {}
        for _ in range(3):
            r = await (asyncio.to_thread(_api, method, fields, file) if file else asyncio.to_thread(_api, method, fields))
            if r.get("ok") or r.get("error_code") != 429:
                break
            await asyncio.sleep(min(float((r.get("parameters") or {}).get("retry_after", 1)), 5) + 0.2)
        return r

    async def send(rec: dict) -> bool:
        text = build_text(rec, model=model, serial=serial, customer=customer, priority=priority,
                          deadline=deadline, description=description, count=count)
        chat = rec["telegram_id"]
        if out["file_id"] or image:
            fields = {"chat_id": chat, "caption": text, "parse_mode": "HTML"}
            if out["file_id"]:
                r = await call("sendPhoto", {**fields, "photo": out["file_id"]})
                if r.get("ok"):
                    return True
            if image:
                r = await call("sendPhoto", fields, (image_name, ctype, image))
                if r.get("ok"):
                    try:
                        out["file_id"] = r["result"]["photo"][-1]["file_id"]
                    except (KeyError, IndexError, TypeError):
                        pass
                    return True
            # rasm yuborilmadi — hech bo'lmasa matnni yuboramiz
        r = await call("sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML"})
        if not r.get("ok"):
            out["error"] = r.get("description")
        return bool(r.get("ok"))

    if not recips:
        return out
    # Birinchisi ketma-ket (file_id olish uchun), qolganlari parallel.
    results = [await send(recips[0])]
    sem = asyncio.Semaphore(8)

    async def guarded(rec):
        async with sem:
            return await send(rec)

    results += await asyncio.gather(*(guarded(r) for r in recips[1:]))
    out["sent"] = sum(results)
    out["failed"] = len(results) - out["sent"]
    return out


_BOT_NAME: dict = {"v": None, "t": 0.0}


async def bot_username() -> str | None:
    """Botning @username'i (Telegram getMe, 1 soat keshlanadi). Token yo'q yoki xato bo'lsa None."""
    import time

    if not settings.bot_token:
        return None
    if _BOT_NAME["v"] and time.monotonic() - _BOT_NAME["t"] < 3600:
        return _BOT_NAME["v"]
    r = await asyncio.to_thread(_api, "getMe", {}, None, 6)
    name = (r.get("result") or {}).get("username") if r.get("ok") else None
    if name:
        _BOT_NAME.update(v=name, t=time.monotonic())
    return name
