from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

COOKIE_NAME = "baaz_session"
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="baaz-web")
SESSION_MAX_AGE = 60 * 60 * 12   # token 12 soatdan keyin o'zi yaroqsiz bo'ladi (cookie muddati bilan bir xil)


def make_token() -> str:
    return _serializer.dumps({"ok": True})


def valid(token) -> bool:
    if not token:
        return False
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return bool(data.get("ok"))
    except (BadSignature, SignatureExpired):
        return False


class _RedirectException(Exception):
    def __init__(self, location: str) -> None:
        self.location = location


def install_redirect_handler(app) -> None:
    @app.exception_handler(_RedirectException)
    async def _handle(_: Request, exc: _RedirectException):  # pragma: no cover
        return RedirectResponse(exc.location, status_code=302)


def require_login(request: Request) -> bool:
    if not valid(request.cookies.get(COOKIE_NAME)):
        raise _RedirectException("/login")
    return True
