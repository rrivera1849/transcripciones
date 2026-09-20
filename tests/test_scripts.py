"""Admin scripts: password comes from the argument, a prompt, or is generated."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import _password


def test_argument_wins(monkeypatch):
    assert _password.choose_password(["x", "mama", "clave-larga"]) == ("clave-larga", False)


def test_generates_when_not_a_terminal(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    pw, generated = _password.choose_password(["x", "mama"])
    assert generated and len(pw) >= 12


def test_prompts_twice_and_rejects_short_or_mismatched(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    answers = iter(["corta", "clave-larga", "otra-cosa", "clave-larga", "clave-larga"])
    monkeypatch.setattr(_password.getpass, "getpass", lambda prompt: next(answers))
    assert _password.choose_password(["x", "mama"]) == ("clave-larga", False)


def test_empty_prompt_generates(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_password.getpass, "getpass", lambda prompt: "")
    pw, generated = _password.choose_password(["x", "mama"])
    assert generated and pw
