"""SQLAlchemy-Modelle.

Die Typen sind bewusst portabel gehalten (String mit Länge, keine MariaDB-Spezialitäten),
damit die Tests dieselben Modelle gegen SQLite fahren können.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Seiten einer Vokabel
SIDE_FOREIGN = "foreign"
SIDE_DE = "de"

# Abfragerichtungen: fw = Fremdsprache -> Deutsch, bw = Deutsch -> Fremdsprache
DIRECTION_FW = "fw"
DIRECTION_BW = "bw"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Language(Base):
    __tablename__ = "languages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    sets: Mapped[list["VocabSet"]] = relationship(back_populates="language")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Kinder haben oft kein Postfach — deshalb optional.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    sets: Mapped[list["VocabSet"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    progress: Mapped[list["LearnProgress"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Nur der Hash liegt in der Datenbank, nie das Token selbst.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="reset_tokens")

    __table_args__ = (Index("ix_reset_tokens_user", "user_id"),)


class VocabSet(Base):
    __tablename__ = "vocab_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    owner: Mapped["User"] = relationship(back_populates="sets")
    language: Mapped["Language"] = relationship(back_populates="sets")
    entries: Mapped[list["VocabEntry"]] = relationship(
        back_populates="vocab_set", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_vocab_sets_owner_lang", "owner_id", "language_id"),)


class VocabEntry(Base):
    __tablename__ = "vocab_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(
        ForeignKey("vocab_sets.id", ondelete="CASCADE"), nullable=False
    )
    # Zusatzinfo, die nie mitgeprüft wird — bei Latein typischerweise die Stammformen.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    vocab_set: Mapped["VocabSet"] = relationship(back_populates="entries")
    variants: Mapped[list["VocabVariant"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", lazy="selectin"
    )
    progress: Mapped[list["LearnProgress"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_vocab_entries_set", "set_id"),)

    def side(self, side: str) -> list["VocabVariant"]:
        """Alle Varianten einer Seite, primäre zuerst."""
        return sorted(
            (v for v in self.variants if v.side == side),
            key=lambda v: (not v.is_primary, v.id or 0),
        )

    def prompt(self, side: str) -> str:
        variants = self.side(side)
        return variants[0].text if variants else ""


class VocabVariant(Base):
    __tablename__ = "vocab_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("vocab_entries.id", ondelete="CASCADE"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    text: Mapped[str] = mapped_column(String(255), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    entry: Mapped["VocabEntry"] = relationship(back_populates="variants")

    __table_args__ = (Index("ix_vocab_variants_entry_side", "entry_id", "side"),)


class LearnProgress(Base):
    """Fortschritt hängt am lernenden Nutzer, nicht am Besitzer der Vokabel.

    Nur so kann jemand fremde Vokabeln aus dem globalen Pool lernen und trotzdem eigene
    Boxen führen. Beide Richtungen werden getrennt gezählt, weil Deutsch → Fremdsprache
    deutlich schwerer ist als umgekehrt.
    """

    __tablename__ = "learn_progress"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("vocab_entries.id", ondelete="CASCADE"), primary_key=True
    )
    direction: Mapped[str] = mapped_column(String(2), primary_key=True)

    box: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="progress")
    entry: Mapped["VocabEntry"] = relationship(back_populates="progress")

    # (user_id, entry_id, direction) ist bereits der Primärschlüssel — kein zusätzlicher
    # Unique-Index nötig.
    __table_args__ = (Index("ix_progress_user_due", "user_id", "due_at"),)
