"""Tell the person who uploaded a hearing that it is ready (or failed).

Only email for now; it is sent from the worker, never from a request.
Disabled unless SMTP_HOST is configured and the user has an email address.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import config, db

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    if not config.SMTP_HOST or not to:
        return False
    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if config.SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20,
                                  context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
        server.starttls(context=ssl.create_default_context())
    with server:
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(msg)
    return True


def job_finished(conn, job: dict, error: str | None = None) -> bool:
    """Email the uploader. Returns True when a message went out."""
    user = db.get_user(conn, job.get("created_by") or "")
    email = user["email"] if user else None
    if not email:
        return False
    title = job["title"]
    link = f"{config.APP_URL}/t/{job['id']}" if config.APP_URL else ""
    if error:
        subject = f"No se pudo transcribir «{title}»"
        body = f"La transcripción de «{title}» falló:\n\n{error}\n\nPuedes pulsar Reintentar en la lista."
    else:
        subject = f"«{title}» está lista"
        body = f"La transcripción de «{title}» ya está lista."
    if link:
        body += f"\n\nÁbrela aquí: {link}\n"
    try:
        return send_email(email, subject, body)
    except Exception as e:  # noqa: BLE001 - a mail failure must never fail the job
        log.warning("no se pudo enviar el aviso a %s: %s", email, e)
        return False
