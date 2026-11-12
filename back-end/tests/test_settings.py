"""Tests for app.core.config: required variables, .env loading, no secret fallbacks."""

import re
from pathlib import Path

import pytest

from app.core.config import Settings, load_settings

ALL_VARS = [name.upper() for name in Settings.model_fields]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate tests from the developer's real environment and .env files."""
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", ())


def test_fails_without_required_variables_and_names_them():
    with pytest.raises(RuntimeError) as exc:
        load_settings()
    message = str(exc.value)
    assert "DATABASE_URL" in message
    assert "SECRET_KEY" in message


def test_secret_key_has_no_fallback(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    with pytest.raises(RuntimeError) as exc:
        load_settings()
    assert "SECRET_KEY" in str(exc.value)
    assert "DATABASE_URL" not in str(exc.value)


def test_required_fields_have_no_defaults():
    # Guards against a silent default: nothing in the code may supply a key.
    assert Settings.model_fields["secret_key"].is_required()
    assert Settings.model_fields["database_url"].is_required()


def test_values_are_read_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://u:p@h:5432/d\n"
        "SECRET_KEY=from-file\n"
        "CACHE_TTL_SECONDS=60\n"
        "DB_ECHO=true\n",
        encoding="utf-8",
    )
    s = Settings(_env_file=env_file)
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert s.secret_key == "from-file"
    assert s.cache_ttl_seconds == 60
    assert s.db_echo is True


def test_process_environment_overrides_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://u:p@h:5432/d\nSECRET_KEY=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SECRET_KEY", "from-process")
    assert Settings(_env_file=env_file).secret_key == "from-process"


def test_defaults_and_derived_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("SECRET_KEY", "k")
    monkeypatch.setenv("GEMINI_MODELS", " a , b ,,c ")
    s = load_settings()
    assert s.db_echo is False
    assert s.algorithm == "HS256"
    assert s.cache_ttl_seconds == 7200
    assert s.anthropic_api_key == ""
    assert s.gemini_model_list == ["a", "b", "c"]


def test_no_direct_environment_access_outside_config():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"os\.(getenv|environ)|load_dotenv")
    offenders = [
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        if p.name != "config.py" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
