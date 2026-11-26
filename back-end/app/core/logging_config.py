"""One place that configures logging for the whole application (E0.7).

Before this module the scraper package called ``logging.basicConfig(level=ERROR)`` when it was imported, which
set the root logger to ERROR: in Docker every INFO and WARNING of the application was dropped, including the
token-usage lines and the "output truncated at max_tokens" warnings of the Claude client.
"""

import logging

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Libraries that are chatty at INFO or print request URLs; they are shown from WARNING up.
QUIET_LOGGERS = ("httpx", "httpx2", "httpcore", "urllib3", "PIL", "pikepdf", "asyncio", "google", "grpc")


class _OcrOrientationNoise(logging.Filter):
    """ocrmypdf logs ERROR when page orientation (OSD) cannot be detected on a page with almost no text, for
    example a page that is one stamp or signature image. The page is then simply OCR-ed without rotation and
    a genuine OCR failure still raises (the application logs it), so these two lines are only noise."""

    MARKERS = ("LSTM requested, but not present", "Error during processing")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(marker in message for marker in self.MARKERS)


def configure_logging(db_echo: bool = False) -> None:
    """INFO for the application, WARNING for noisy libraries, SQL statements only when DB_ECHO is on."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, force=True)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # with the root logger at INFO SQLAlchemy would log every statement with its parameters
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if db_echo else logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    ocr_logger = logging.getLogger("ocrmypdf._exec.tesseract")
    if not any(isinstance(f, _OcrOrientationNoise) for f in ocr_logger.filters):
        ocr_logger.addFilter(_OcrOrientationNoise())
