"""Dev launcher: web server + worker in one process.  uv run python -m app"""

import logging
import threading

import uvicorn

from . import config, db
from .worker import Worker, make_backend


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.init_db()
    worker = Worker(make_backend())
    threading.Thread(target=worker.run_forever, name="worker", daemon=True).start()
    logging.getLogger("app").info(
        "data dir %s, transcriber=%s", config.DATA_DIR, config.TRANSCRIBER
    )
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
