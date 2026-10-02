import smtplib
from email.message import EmailMessage
from typing import Protocol

from config import INVITE_FROM_EMAIL, INVITE_SMTP_HOST, INVITE_SMTP_PORT


class Inviter(Protocol):
    def send_invitation(self, *, email: str, name: str, token: str, environment_name: str) -> None: ...


class NoOpInviter:
    def send_invitation(self, *, email: str, name: str, token: str, environment_name: str) -> None:
        return None


class SMTPInviter:
    def __init__(self, host: str, port: int, from_email: str):
        self.host = host
        self.port = port
        self.from_email = from_email

    def send_invitation(self, *, email: str, name: str, token: str, environment_name: str) -> None:
        message = EmailMessage()
        message["From"] = self.from_email
        message["To"] = email
        message["Subject"] = f"Undangan {environment_name}"
        message.set_content(f"Halo {name},\n\nToken aktivasi: {token}\n")
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.send_message(message)


def get_inviter() -> Inviter:
    if not INVITE_SMTP_HOST or not INVITE_FROM_EMAIL:
        return NoOpInviter()
    return SMTPInviter(INVITE_SMTP_HOST, INVITE_SMTP_PORT, INVITE_FROM_EMAIL)
