"""Grundschema

Revision ID: 0001
Revises:
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "languages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_reset_tokens_user", "password_reset_tokens", ["user_id"])

    op.create_table(
        "vocab_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("language_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["language_id"], ["languages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vocab_sets_owner_lang", "vocab_sets", ["owner_id", "language_id"])

    op.create_table(
        "vocab_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["set_id"], ["vocab_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vocab_entries_set", "vocab_entries", ["set_id"])

    op.create_table(
        "vocab_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("text", sa.String(length=255), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["entry_id"], ["vocab_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vocab_variants_entry_side", "vocab_variants", ["entry_id", "side"])

    op.create_table(
        "learn_progress",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=2), nullable=False),
        sa.Column("box", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["vocab_entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "entry_id", "direction"),
    )
    op.create_index("ix_progress_user_due", "learn_progress", ["user_id", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_progress_user_due", table_name="learn_progress")
    op.drop_table("learn_progress")
    op.drop_index("ix_vocab_variants_entry_side", table_name="vocab_variants")
    op.drop_table("vocab_variants")
    op.drop_index("ix_vocab_entries_set", table_name="vocab_entries")
    op.drop_table("vocab_entries")
    op.drop_index("ix_vocab_sets_owner_lang", table_name="vocab_sets")
    op.drop_table("vocab_sets")
    op.drop_index("ix_reset_tokens_user", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_table("users")
    op.drop_table("languages")
