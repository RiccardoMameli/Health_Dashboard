"""Declarative base and portable column types.

The production database is Postgres (Supabase). Tests run on SQLite, so any
Postgres-specific type is declared with a SQLite fallback rather than used
directly — otherwise the test suite silently diverges from production.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, MetaData, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# Explicit naming so Alembic autogenerate produces stable, reversible migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB on Postgres, plain JSON on SQLite.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class TZDateTime(TypeDecorator):
    """A timestamp that is always timezone-aware UTC on the way in and out.

    Postgres preserves the offset; SQLite silently discards it and hands back
    a naive datetime, which then raises on any comparison with an aware one.
    Normalising in the type rather than at every call site means the same code
    behaves identically against the test database and production.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "Naive datetime reached the database. Normalise with "
                "app.services.timeutil.to_utc() first."
            )
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


# Always store UTC (plan 5.1). Rendering to Europe/London happens at the edge.
UTCDateTime = TZDateTime()


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        datetime: UTCDateTime,
        dict: JSONType,
        list: JSONType,
    }
