"""add verified_by_actor and verification_evidence to wix_site_event_binding

Revision ID: 20260603_0000
Revises: 20260601_0000
Create Date: 2026-06-03
"""

from alembic import op

revision = "20260603_0000"
down_revision = "20260601_0000"
branch_labels = None
depend_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE wix_site_event_binding
            ADD COLUMN IF NOT EXISTS verified_by_actor TEXT,
            ADD COLUMN IF NOT EXISTS verification_evidence TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE wix_site_event_binding
            DROP COLUMN IF EXISTS verified_by_actor,
            DROP COLUMN IF EXISTS verification_evidence;
        """
    )
