"""Telegram Mini App (WebApp) kirish ma'lumoti (`initData`) ni tekshirish.

Telegram ilovani ochganda foydalanuvchi haqidagi ma'lumotni `initData` qatori bilan beradi va uni bot tokeni
asosidagi kalit bilan imzolaydi. Imzo to'g'ri bo'lsa, foydalanuvchi aynan o'sha Telegram akkaunt ekani
ishonchli (parol kerak emas). Hujjat: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

INIT_DATA_MAX_AGE = 24 * 3600      # initData shu muddatdan eski bo'lsa qabul qilinmaydi
SESSION_MAX_AGE = 12 * 3600        # ilova sessiya tokeni muddati


class InitDataError(ValueError):
    """initData noto'g'ri, imzosi xato yoki eskirgan."""


def validate_init_data(init_data: str, bot_token: str, *, max_age: int = INIT_DATA_MAX_AGE,
                       now: float | None = None) -> dict:
    """initData ni tekshiradi va foydalanuvchi ma'lumotini ({id, first_name, ...}) qaytaradi."""
    if not init_data or not bot_token:
        raise InitDataError("initData yo'q")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received = pairs.pop("hash", "")
    if not received:
        raise InitDataError("hash yo'q")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("imzo noto'g'ri")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as e:
        raise InitDataError("auth_date noto'g'ri") from e
    if (now if now is not None else time.time()) - auth_date > max_age:
        raise InitDataError("initData eskirgan")
    try:
        user = json.loads(pairs.get("user", ""))
    except (ValueError, TypeError) as e:
        raise InitDataError("user yo'q") from e
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("user noto'g'ri")
    return user


def make_init_data(user: dict, bot_token: str, *, auth_date: int | None = None) -> str:
    """Sinov uchun: Telegram'ning o'zi kabi imzolangan initData yasaydi."""
    from urllib.parse import urlencode

    pairs = {"auth_date": str(auth_date if auth_date is not None else int(time.time())),
             "query_id": "AAH-test", "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False)}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="miniapp-session")


def make_session_token(telegram_id: int, secret_key: str) -> str:
    return _serializer(secret_key).dumps({"tg": telegram_id})


def read_session_token(token: str, secret_key: str, max_age: int = SESSION_MAX_AGE) -> int | None:
    """Token to'g'ri va muddati o'tmagan bo'lsa Telegram ID, aks holda None."""
    try:
        data = _serializer(secret_key).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    tg = data.get("tg") if isinstance(data, dict) else None
    return tg if isinstance(tg, int) else None
