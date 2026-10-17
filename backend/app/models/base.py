"""Declarative base, shared column types and mixins.

All timestamps are stored as UTC (DATETIME2 on SQL Server, naive-UTC storage)
and returned as timezone-aware UTC datetimes.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, MetaData, TypeDecorator
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, returns aware UTC. DATETIME2(3) on SQL Server."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mssql":
            return dialect.type_descriptor(mssql.DATETIME2(precision=3))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use timezone-aware UTC values")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class CreatedByMixin:
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)


# Long text: NVARCHAR(MAX) on SQL Server (NTEXT is deprecated), TEXT elsewhere.
from sqlalchemy import UnicodeText as _UnicodeText  # noqa: E402

LongText = _UnicodeText().with_variant(mssql.NVARCHAR(), "mssql")
