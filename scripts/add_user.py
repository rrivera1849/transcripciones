#!/usr/bin/env python3
"""Create an account.  usage: uv run python scripts/add_user.py <username> [password]

Prints a generated password when none is given. Run on the app host, where
DATA_DIR points at the app's data directory.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth, db


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    username = argv[1].strip().lower()
    password = argv[2] if len(argv) > 2 else auth.generate_password()
    db.init_db()
    with db.connect() as conn:
        if db.get_user(conn, username):
            print(f"user {username!r} already exists")
            return 1
        db.create_user(conn, username, auth.hash_password(password))
    print(f"created {username}\npassword: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
