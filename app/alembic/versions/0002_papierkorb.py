"""Papierkorb für Vokabelsets: Löschen flaggt nur noch, der Admin räumt auf.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vocab_sets", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("vocab_sets", "deleted_at")
