"""Zustellung des Reset-Links.

Ohne SMTP_HOST verschickt openVerba nichts — der Link steht dann im Admin-Bereich zum
Weitergeben bereit. Das ist der Normalbetrieb und bewusst so gewählt, damit die
Anwendung ohne Mailserver vollständig benutzbar bleibt.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger(__name__)


def send_reset_link(to_address: str, link: str) -> bool:
    """Verschickt den Link. Gibt zurück, ob das geklappt hat.

    Ein Fehlschlag wird protokolliert, aber nie hochgereicht: Der Reset-Vorgang darf
    daran nicht scheitern, der Link bleibt im Admin-Bereich abrufbar.
    """
    settings = get_settings()
    if not settings.mail_enabled:
        return False
    if not to_address:
        return False

    message = EmailMessage()
    message["Subject"] = "openVerba — Passwort zurücksetzen"
    message["From"] = settings.smtp_from or f"openverba@{settings.smtp_host}"
    message["To"] = to_address
    message.set_content(
        "Hallo,\n\n"
        "für deinen openVerba-Zugang wurde ein neues Passwort angefordert.\n"
        "Über diesen Link kannst du eines setzen:\n\n"
        f"{link}\n\n"
        "Der Link gilt 24 Stunden und lässt sich nur einmal verwenden.\n"
        "Warst du das nicht, kannst du diese Nachricht ignorieren.\n"
    )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except Exception:  # noqa: BLE001 - jeder Fehler bleibt hier und wird protokolliert
        log.exception("Reset-Mail an %s konnte nicht zugestellt werden", to_address)
        return False

    log.info("Reset-Mail an %s zugestellt", to_address)
    return True
