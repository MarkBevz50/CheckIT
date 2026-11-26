"""One place that configures logging for the whole application (E0.7).

Before this module the scraper package called ``logging.basicConfig(level=ERROR)`` when it was imported, which
set the root logger to ERROR: in Docker every INFO and WARNING of the application was dropped, including the
token-usage lines and the "output truncated at max_tokens" warnings of the Claude client.
"""

import logging

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Libraries that are chatty at INFO or print request URLs; they are shown from WARNING up.
QUIET_LOGGERS = ("httpx", "httpx2", "httpcore", "urllib3", "PIL", "pikepdf", "asyncio", "google", "grpc")


def configure_logging(db_echo: bool = False) -> None:
    """INFO for the application, WARNING for noisy libraries, SQL statements only when DB_ECHO is on."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, force=True)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # with the root logger at INFO SQLAlchemy would log every statement with its parameters
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if db_echo else logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
