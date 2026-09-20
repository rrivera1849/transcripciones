from app import config, notify


def test_send_email_disabled_without_smtp(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "")
    assert notify.send_email("a@b.co", "s", "b") is False
