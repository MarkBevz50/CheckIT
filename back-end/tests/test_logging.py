"""E0.7: logging is configured in one place, and nothing else lowers the root logger to ERROR."""

import logging
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.logging_config import QUIET_LOGGERS, configure_logging

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    state = (root.level, list(root.handlers), {n: logging.getLogger(n).level for n in (*QUIET_LOGGERS, "sqlalchemy.engine", "sqlalchemy.pool")})
    yield
    root.setLevel(state[0])
    root.handlers[:] = state[1]
    for name, level in state[2].items():
        logging.getLogger(name).setLevel(level)


def test_application_info_is_visible_and_noisy_libraries_are_not():
    configure_logging()
    assert logging.getLogger().level == logging.INFO
    assert logging.getLogger("app.services.claude_validator").isEnabledFor(logging.INFO)
    for name in QUIET_LOGGERS:
        assert not logging.getLogger(name).isEnabledFor(logging.INFO), name


def test_sql_statements_are_logged_only_with_db_echo():
    configure_logging(db_echo=False)
    assert not logging.getLogger("sqlalchemy.engine").isEnabledFor(logging.INFO)
    configure_logging(db_echo=True)
    assert logging.getLogger("sqlalchemy.engine").isEnabledFor(logging.INFO)


def test_usage_lines_of_the_claude_client_reach_the_log(caplog):
    from types import SimpleNamespace

    from app.services import claude_validator

    configure_logging()  # force=True drops the handlers of the root logger, including caplog's
    logging.getLogger().addHandler(caplog.handler)
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    with caplog.at_level(logging.INFO, logger="app.services.claude_validator"):
        claude_validator._log_usage("test", SimpleNamespace(usage=usage, stop_reason="end_turn"), 100)
    assert "input=10 output=5" in caplog.text


def test_importing_the_scraper_package_does_not_change_the_root_logger():
    # -I ignores PYTHONPATH and the working directory, so the repository root goes on sys.path explicitly
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import logging; import scraper.parsers; print(logging.getLogger().level)"
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) == logging.WARNING  # the default of a process nobody configured


def test_basic_config_is_called_only_by_the_logging_module():
    offenders = []
    for base in (ROOT / "back-end" / "app", ROOT / "scraper" / "parsers"):
        for path in base.rglob("*.py"):
            if path.name == "logging_config.py":
                continue
            if re.search(r"^\s*logging\.basicConfig\(", path.read_text(encoding="utf-8"), re.MULTILINE):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
