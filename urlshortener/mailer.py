# -*- coding: utf-8 -*-
# Copyright (c) 2026 Logikascium — AGPL-3.0-or-later
"""Delivery of short links by e-mail.

One class, one method, injected through the registry so the tests can
substitute a recorder: `request.mailer.send(...)` is the only door, and
nothing else in the code base imports `smtplib`.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)


class MailNotSent(Exception):
    """The relay refused or was unreachable. The caller decides what
    the visitor is told; the address is NOT put in the log."""


class SMTPMailer:
    def __init__(self, settings):
        self._settings = settings

    def send(self, recipient: str, subject: str, body: str) -> None:
        settings = self._settings
        message = EmailMessage()
        message["From"] = settings.mail_sender
        message["To"] = recipient
        message["Subject"] = subject
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls()
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            # The class of the failure is loggable; the recipient is a
            # personal datum and is not.
            log.error("mail delivery failed: %s", type(error).__name__)
            raise MailNotSent() from error
