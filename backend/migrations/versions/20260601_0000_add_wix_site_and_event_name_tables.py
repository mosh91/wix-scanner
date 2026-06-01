"""add wix site and event name lookup tables

Revision ID: 20260601_0000
Revises: 0001
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260601_0000"
down_revision = "0001"
branch_labels = None
depend_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS wix_site (
            id TEXT PRIMARY KEY,
            wix_site_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS wix_event_name (
            id TEXT PRIMARY KEY,
            wix_event_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_wix_site_wix_site_id ON wix_site (wix_site_id);
        CREATE INDEX IF NOT EXISTS idx_wix_event_name_wix_event_id ON wix_event_name (wix_event_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS wix_event_name;
        DROP TABLE IF EXISTS wix_site;
        """
    )
