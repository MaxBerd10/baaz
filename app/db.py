from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import GenericFunction
from sqlalchemy.types import Date

from app.config import settings
from app.models import Base


class day(GenericFunction):
    """Timestamp'ni sanaga keltiradi. SQLite'da date(), Postgres'da CAST(... AS DATE)."""

    type = Date()
    inherit_cache = True


@compiles(day)
def _day_default(element, compiler, **kw):  # pragma: no cover
    return "date(%s)" % compiler.process(element.clauses, **kw)


@compiles(day, "postgresql")
def _day_pg(element, compiler, **kw):  # pragma: no cover
    return "CAST(%s AS DATE)" % compiler.process(element.clauses, **kw)


def _normalize(url: str) -> tuple[str, dict]:
    """Postgres URL'ni async driver uchun tayyorlaydi va asyncpg tushunmaydigan
    query paramlarni (sslmode, channel_binding) olib tashlaydi."""
    if url.startswith("sqlite"):
        return url, {}

    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    q = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("sslmode", "channel_binding")]
    new = urlunsplit((scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))

    connect_args: dict = {}
    host = (parts.hostname or "").lower()
    if "asyncpg" in scheme and host not in ("localhost", "127.0.0.1", "db"):
        connect_args["ssl"] = True
    return new, connect_args


_url, _connect_args = _normalize(settings.database_url)
_is_sqlite = _url.startswith("sqlite")

_kw: dict = {"echo": False, "pool_pre_ping": True}
if not _is_sqlite:
    _kw.update(pool_size=2, max_overflow=3, pool_recycle=280)
    if _connect_args:
        _kw["connect_args"] = _connect_args

engine = create_async_engine(_url, **_kw)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
