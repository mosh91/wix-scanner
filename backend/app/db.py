"""Central SQLAlchemy engine factory for backend services.

All backend services that need database persistence should obtain their
SQLAlchemy engine via :func:`make_engine` rather than calling
``create_engine`` directly. This ensures consistent engine configuration
(WAL mode for SQLite in tests, connection pool settings for PostgreSQL).

Architecture decision: PostgreSQL is the canonical backend store.
SQLite is used only in automated tests (via a ``sqlite:///`` URL passed
directly to the service constructor) and in the relay service which runs
on edge hardware without access to a Postgres instance.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker


def make_engine(url: str, **kwargs: object) -> Engine:
    """Create a SQLAlchemy engine for *url*.

    Extra keyword arguments are forwarded to :func:`~sqlalchemy.create_engine`.
    For SQLite URLs the ``journal_mode=WAL`` PRAGMA is applied automatically to
    improve concurrency during tests.
    """
    engine = create_engine(url, **kwargs)  # type: ignore[arg-type]
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # type: ignore[misc]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine


def make_session_factory(engine: Engine):  # type: ignore[return]
    """Return a :class:`~sqlalchemy.orm.sessionmaker` bound to *engine*."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
