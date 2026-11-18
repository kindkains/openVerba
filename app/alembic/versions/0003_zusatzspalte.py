"""Optionale dritte Spalte: Überschrift am Set, Werte als Variantenseite "extra".

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vocab_sets", sa.Column("extra_label", sa.String(60), nullable=True))


def downgrade() -> None:
    op.execute("DELETE FROM vocab_variants WHERE side = 'extra'")
    op.drop_column("vocab_sets", "extra_label")
