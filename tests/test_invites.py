import os
import subprocess
import sys


def test_smtp_inviter_uses_configured_activation_url_and_encodes_token(monkeypatch):
    import app.invites as invites

    sent = []

    class SMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send_message(self, message):
            sent.append(message.get_content())

    monkeypatch.setattr(invites, "INVITE_ACTIVATION_URL", "https://frontend.example/activate?from=invite")
    monkeypatch.setattr(invites.smtplib, "SMTP", SMTP)

    invites.SMTPInviter("smtp.example", 25, "no-reply@example.com").send_invitation(
        email="user@example.com",
        name="User",
        token="token+/=?",
        environment_name="Toko",
    )

    body = sent[0]
    assert "https://frontend.example/activate?from=invite&token=token%2B%2F%3D%3F" in body
    assert "https://example.com/activate" not in body


def test_production_config_rejects_missing_invite_activation_url():
    environment = os.environ | {
        "APP_ENV": "production",
        "SECRET_KEY": "x" * 32,
        "POS_INTEGRATION_KEY": "y" * 32,
        "CORS_ORIGINS": "https://frontend.example",
    }
    for name in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "INVITE_ACTIVATION_URL"):
        environment.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "INVITE_ACTIVATION_URL" in result.stderr
