"""Konfiguration aus der Umgebung.

Alles, was openVerba über seine Umgebung weiß, kommt hier durch. Kein anderes Modul
liest direkt aus os.environ, und nichts Umgebungsspezifisches steht im Code.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Anwendung ---
    secret_key: str = Field(alias="OPENVERBA_SECRET_KEY", min_length=16)
    base_url: str = Field(default="http://localhost:8080", alias="OPENVERBA_BASE_URL")
    session_size: int = Field(default=20, alias="OPENVERBA_SESSION_SIZE", ge=1, le=200)
    typo_tolerance: bool = Field(default=True, alias="OPENVERBA_TYPO_TOLERANCE")

    # --- Bootstrap-Admin ---
    admin_user: str = Field(default="admin", alias="OPENVERBA_ADMIN_USER")
    admin_password: str = Field(default="", alias="OPENVERBA_ADMIN_PASSWORD")

    # --- Datenbank ---
    db_host: str = Field(default="db", alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_name: str = Field(default="openverba", alias="MARIADB_DATABASE")
    db_user: str = Field(default="openverba", alias="MARIADB_USER")
    db_password: str = Field(default="", alias="MARIADB_PASSWORD")

    # Vollständige URL. Überschreibt die Einzelwerte oben — die Tests fahren damit
    # gegen SQLite, ohne dass MariaDB laufen muss.
    database_url_override: str = Field(default="", alias="DATABASE_URL")

    # --- Mailversand (optional) ---
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")
    smtp_starttls: bool = Field(default=True, alias="SMTP_STARTTLS")

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def mail_enabled(self) -> bool:
        """Ohne SMTP_HOST bleibt der Reset-Link im Admin-Bereich — das ist der Normalfall."""
        return bool(self.smtp_host)


@lru_cache
def get_settings() -> Settings:
    return Settings()
