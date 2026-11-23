"""One configuration file (E0.12): Settings reads only the repo-root .env, like Docker.

A leftover back-end/.env is ignored and reported with a warning that lists variable NAMES only.
"""

import logging
import re
from pathlib import Path

from app.core import config
from app.core.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[2]
DB_URL = "postgresql+asyncpg://u:p@h:5432/d"
OK_KEY = "ok-key-" + "c" * 30


def test_the_root_env_is_the_only_file_settings_can_read():
    assert config.ENV_FILE == ROOT / ".env"
    assert config.LEGACY_ENV_FILE == ROOT / "back-end" / ".env"
    assert not hasattr(config, "ENV_FILES")  # the old two-file tuple is gone
    assert Settings.model_config["env_file"] == config.ENV_FILE  # a single path, not a tuple with back-end/.env


def test_a_legacy_env_file_gives_a_warning_with_names_but_never_values(tmp_path, caplog):
    legacy = tmp_path / ".env"
    legacy.write_text(
        "SECRET_KEY=never-print-this-value-0123456789\n"
        "export DATABASE_URL = postgresql://user:pw@host/db\n"
        "# COMMENTED=x\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger=config.logger.name):
        assert config.warn_if_legacy_env_file(legacy) is True
    message = caplog.text
    assert "IGNORED" in message and "root .env" in message
    assert "SECRET_KEY" in message and "DATABASE_URL" in message  # names only
    assert "COMMENTED" not in message  # a commented line defines nothing
    assert "never-print-this-value" not in message and "pw@host" not in message


def test_no_warning_without_a_legacy_env_file(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=config.logger.name):
        assert config.warn_if_legacy_env_file(tmp_path / "missing.env") is False
    assert caplog.text == ""


def test_load_settings_warns_at_start_when_the_legacy_file_exists(monkeypatch, tmp_path, caplog):
    legacy = tmp_path / ".env"
    legacy.write_text("GEMINI_API_KEY=value-that-must-not-leak\n", encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_ENV_FILE", legacy)
    monkeypatch.setitem(Settings.model_config, "env_file", ())
    for var in ("DATABASE_URL", "SECRET_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("SECRET_KEY", OK_KEY)
    with caplog.at_level(logging.WARNING, logger=config.logger.name):
        settings = load_settings()
    assert "GEMINI_API_KEY" in caplog.text and "value-that-must-not-leak" not in caplog.text
    assert settings.gemini_api_key == ""  # the ignored file did not leak into the settings


def test_compose_gives_the_container_the_db_host_whatever_the_root_env_says():
    """DATABASE_URL of the root .env (localhost:5433) is only for a local uvicorn; compose sets its own for backend."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    backend = compose.split("  backend:", 1)[1].split("\n  frontend:", 1)[0]
    match = re.search(r"^\s*DATABASE_URL:\s*(\S+)", backend, re.M)
    assert match, "the backend service must set DATABASE_URL itself"
    assert "@db:5432/" in match.group(1) and "localhost" not in match.group(1)
    assert "env_file" not in backend  # nothing from the root .env is passed through wholesale


def test_redis_has_a_named_volume_so_that_up_does_not_create_anonymous_ones():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    redis = compose.split("  redis:", 1)[1].split("\n  backend:", 1)[0]
    assert re.search(r"^\s*-\s*redis_data:/data\s*$", redis, re.M)
    assert re.search(r"^volumes:\n(?:\s+\w+:\n)*\s+redis_data:", compose, re.M)
