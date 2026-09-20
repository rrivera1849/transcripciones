#!/usr/bin/env python3
"""Reset an account's password (admin path, e.g. when it is forgotten).

usage: uv run python scripts/set_password.py <username> [new-password]

Without a password argument it prompts (twice) when run in a terminal, or
generates and prints one when it is not. Run on the app host.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _password import choose_password

from app import auth, db


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    username = argv[1].strip().lower()
    password, generated = choose_password(argv)
    db.init_db()
    with db.connect() as conn:
        if not db.set_password(conn, username, auth.hash_password(password)):
            print(f"no such user: {username!r}")
            return 1
    shown = password if generated else "(la que escribiste)"
    print(f"password for {username} set to: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
