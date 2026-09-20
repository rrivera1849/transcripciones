"""Shared password entry for the admin scripts: argument, prompt, or generated."""

import getpass
import sys

from app import auth

MIN_LEN = 8


def choose_password(argv: list[str]) -> tuple[str, bool]:
    """(password, generated). From argv[2] if given; else prompt on a terminal; else generate."""
    if len(argv) > 2:
        return argv[2], False
    if not sys.stdin.isatty():
        return auth.generate_password(), True
    while True:
        first = getpass.getpass("Nueva contraseña (Enter para generar una): ")
        if not first:
            return auth.generate_password(), True
        if len(first) < MIN_LEN:
            print(f"Mínimo {MIN_LEN} caracteres.")
            continue
        if first == getpass.getpass("Repítela: "):
            return first, False
        print("No coinciden, intenta de nuevo.")
