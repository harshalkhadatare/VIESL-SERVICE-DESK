from collections.abc import Iterator

import os

from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(url: str | None = None, echo: bool = False) -> Engine:
    settings = get_settings()
    url = url or settings.database_url
    kwargs: dict = {"pool_pre_ping": True, "echo": echo or settings.db_echo}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif os.environ.get("VERCEL"):
        # Serverless: don't hold idle connections between invocations (Neon suspends idle compute)
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_recycle"] = 1800
    if url.startswith("mssql"):
        kwargs["fast_executemany"] = True  # SQL Server: faster bulk inserts (seed / imports)
    if url.startswith("postgresql"):
        # Neon's pooled URL goes through PgBouncer (transaction mode): disable server-side prepared statements
        kwargs["connect_args"] = {"prepare_threshold": None}
    eng = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
