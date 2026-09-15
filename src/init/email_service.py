"""Email tools using SMTP for sending and IMAP for reading/deleting."""
import imaplib
import json
import os
import re
import smtplib
import ssl
from email.header import decode_header, make_header
from email.message import EmailMessage
from email import message_from_bytes
from email.utils import parseaddr

from .config import load_config


PROVIDERS = {
    "gmail": {
        "smtp_host": "smtp.gmail.com", "smtp_port": 465,
        "smtp_ssl": True, "smtp_starttls": False,
        "imap_host": "imap.gmail.com", "imap_port": 993,
        "imap_ssl": True, "imap_starttls": False,
    },
    # Proton's desktop Bridge exposes a local SMTP/IMAP server.
    "proton": {
        "smtp_host": "127.0.0.1", "smtp_port": 1025,
        "smtp_ssl": False, "smtp_starttls": True,
        "imap_host": "127.0.0.1", "imap_port": 1143,
        "imap_ssl": False, "imap_starttls": True,
    },
}


def _result(status, **details):
    return json.dumps({"status": status, **details}, ensure_ascii=False)


def _settings():
    config = load_config()
    provider = config["email_provider"].strip().casefold()
    defaults = PROVIDERS.get(provider, {})
    password = os.environ.get("NORA_EMAIL_PASSWORD", "").strip() or config["email_password"]
    settings = {
        "address": config["email_address"].strip(),
        "password": password,
        "smtp_host": config["email_smtp_host"].strip() or defaults.get("smtp_host", ""),
        "smtp_port": config["email_smtp_port"] or defaults.get("smtp_port", 0),
        "smtp_ssl": config["email_smtp_use_ssl"] if config["email_smtp_host"].strip() else defaults.get("smtp_ssl", True),
        "smtp_starttls": config["email_smtp_starttls"] if config["email_smtp_host"].strip() else defaults.get("smtp_starttls", False),
        "imap_host": config["email_imap_host"].strip() or defaults.get("imap_host", ""),
        "imap_port": config["email_imap_port"] or defaults.get("imap_port", 0),
        "imap_ssl": config["email_imap_use_ssl"] if config["email_imap_host"].strip() else defaults.get("imap_ssl", True),
        "imap_starttls": config["email_imap_starttls"] if config["email_imap_host"].strip() else defaults.get("imap_starttls", False),
    }
    missing = [key for key in ("address", "password", "smtp_host", "smtp_port", "imap_host", "imap_port") if not settings[key]]
    if missing:
        raise ValueError("Configure email_address, email_password (or NORA_EMAIL_PASSWORD) and the email server settings")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", settings["address"]):
        raise ValueError("email_address must be a valid email address")
    return settings


def _decoded(value):
    try:
        return str(make_header(decode_header(value or "")))
    except (UnicodeError, ValueError):
        return value or ""


def _body(message):
    if message.is_multipart():
        parts = message.walk()
        for part in parts:
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")).lower():
                return part.get_content()
        return ""
    return message.get_content() if message.get_content_type() == "text/plain" else ""


def send_email(to: str = "", subject: str = "", body: str = "", cc: str = "", bcc: str = "") -> str:
    """Send an email through the configured SMTP server. Separate multiple recipients with commas."""
    if not to.strip() or not subject.strip() or not body.strip():
        return _result("needs_input", question="Indica destinatario, asunto y cuerpo del correo")
    try:
        settings = _settings()
        message = EmailMessage()
        message["From"] = settings["address"]
        message["To"] = to
        message["Subject"] = subject
        if cc.strip():
            message["Cc"] = cc
        message.set_content(body)
        recipients = [item.strip() for item in (to + "," + cc + "," + bcc).split(",") if item.strip()]
        context = ssl.create_default_context()
        if settings["smtp_ssl"]:
            with smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"], context=context, timeout=30) as server:
                server.login(settings["address"], settings["password"])
                server.send_message(message, to_addrs=recipients)
        else:
            with smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=30) as server:
                server.ehlo()
                if settings["smtp_starttls"]:
                    server.starttls(context=context)
                    server.ehlo()
                server.login(settings["address"], settings["password"])
                server.send_message(message, to_addrs=recipients)
        return _result("submitted", service="smtp", recipient=recipients, subject=subject)
    except (OSError, smtplib.SMTPException, ValueError) as error:
        return _result("error", error=str(error))


def _open_imap(settings):
    if settings["imap_ssl"]:
        client = imaplib.IMAP4_SSL(settings["imap_host"], settings["imap_port"], ssl_context=ssl.create_default_context())
    else:
        client = imaplib.IMAP4(settings["imap_host"], settings["imap_port"])
        if settings["imap_starttls"]:
            client.starttls(ssl_context=ssl.create_default_context())
    client.login(settings["address"], settings["password"])
    return client


def read_emails(folder: str = "INBOX", message_id: str = "", unread_only: bool = False, limit: int = 10) -> str:
    """Read recent emails or one IMAP UID from a folder; returns sender, subject, date and text."""
    if not 1 <= limit <= 50:
        return _result("error", error="limit must be between 1 and 50")
    if not re.fullmatch(r"[A-Za-z0-9_./ \-\[\]]{1,100}", folder):
        return _result("error", error="Invalid email folder")
    if message_id and not message_id.isdigit():
        return _result("error", error="message_id must be an IMAP numeric UID")
    client = None
    try:
        client = _open_imap(_settings())
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            return _result("error", error=f"Could not open email folder: {folder}")
        query = "UNSEEN" if unread_only else "ALL"
        ids = [message_id.encode()] if message_id else (client.uid("search", None, query)[1][0] or b"").split()
        ids = list(reversed(ids[-limit:]))
        results = []
        for uid in ids:
            status, data = client.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                continue
            parsed = message_from_bytes(data[0][1])
            results.append({"id": uid.decode(), "from": parseaddr(parsed.get("From", ""))[1],
                            "to": parsed.get("To", ""), "subject": _decoded(parsed.get("Subject")),
                            "date": parsed.get("Date", ""), "body": _body(parsed)[:20000]})
        return _result("ok", folder=folder, emails=results)
    except (OSError, imaplib.IMAP4.error, UnicodeError, ValueError) as error:
        return _result("error", error=str(error))
    finally:
        if client is not None:
            try:
                client.logout()
            except OSError:
                pass


def delete_email(message_id: str = "", folder: str = "INBOX") -> str:
    """Permanently delete one email by its IMAP UID after an explicit user request."""
    if not message_id.isdigit():
        return _result("needs_input", question="Indica el ID numérico del correo que quieres eliminar")
    if not re.fullmatch(r"[A-Za-z0-9_./ \-\[\]]{1,100}", folder):
        return _result("error", error="Invalid email folder")
    client = None
    try:
        client = _open_imap(_settings())
        status, _ = client.select(folder, readonly=False)
        if status != "OK":
            return _result("error", error=f"Could not open email folder: {folder}")
        status, _ = client.uid("store", message_id, "+FLAGS", "(\\Deleted)")
        if status != "OK":
            return _result("error", error="Could not mark the email for deletion")
        client.expunge()
        return _result("deleted", folder=folder, message_id=message_id)
    except (OSError, imaplib.IMAP4.error, ValueError) as error:
        return _result("error", error=str(error))
    finally:
        if client is not None:
            try:
                client.logout()
            except OSError:
                pass
