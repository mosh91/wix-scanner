"""Alembic migration environment.

The database URL is read at runtime from get_settings().database_url so that
the same alembic.ini works across environments (local Docker, staging, prod)
without hard-coding credentials.

Autogenerate (--autogenerate) is intentionally disabled (target_metadata=None)
because SQLAlchemy models are distributed across many service files.  To enable
autogenerate, import each service's DeclarativeBase metadata and merge them:

    from app.services.credentials import Base as CredBase
    ...
    target_metadata = [CredBase.metadata, ...]
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure the project root is importable regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import get_settings  # noqa: E402

# Alembic Config object – provides access to values in alembic.ini.
config = context.config

# Attach Python logging configuration from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No unified metadata → autogenerate is not supported out of the box.
# New migrations should be written manually with op.* calls.
target_metadata = None


def get_url() -> str:
    """Return the database URL from application settings."""
    return get_settings().database_url


# ---------------------------------------------------------------------------
# Offline mode  – emit SQL to stdout without a live DB connection.
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode  – run against a live DB connection.
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
