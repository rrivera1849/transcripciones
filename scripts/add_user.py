#!/usr/bin/env python3
"""Create an account.  usage: uv run python scripts/add_user.py <username> [password]

Without a password argument it prompts (twice) when run in a terminal, or
generates and prints one when it is not. Run on the app host, where DATA_DIR
points at the app's data directory.
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
        if db.get_user(conn, username):
            print(f"user {username!r} already exists")
            return 1
        db.create_user(conn, username, auth.hash_password(password))
    shown = password if generated else "(la que escribiste)"
    print(f"created {username}\npassword: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
