#!/usr/bin/env python3
"""Reset an account's password (admin path, e.g. when it is forgotten).

usage: uv run python scripts/set_password.py <username> [new-password]

Prints a generated password when none is given. Run on the app host.
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
        if not db.set_password(conn, username, auth.hash_password(password)):
            print(f"no such user: {username!r}")
            return 1
    print(f"password for {username} set to: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
