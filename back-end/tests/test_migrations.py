"""Alembic migrations: one linear history, readable SQL with named constraints, and (when a
Postgres is available through TEST_DATABASE_URL) a real upgrade/check/downgrade round trip."""

import asyncio
import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import NAMING_CONVENTION, Base

BACKEND = Path(__file__).resolve().parents[1]
TABLES = ["users", "tenders", "tender_items", "price_history"]


def alembic_config(**attributes) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes.update(attributes)
    return cfg


def offline_sql(direction: str, revision: str) -> str:
    cfg = alembic_config()
    cfg.output_buffer = io.StringIO()
    getattr(command, direction)(cfg, revision, sql=True)
    return cfg.output_buffer.getvalue()


# ---- history ----------------------------------------------------------

def test_history_is_a_single_line_starting_with_the_baseline():
    script = ScriptDirectory.from_config(alembic_config())
    assert script.get_heads() == [script.get_current_head()]
    revisions = list(script.walk_revisions())
    assert revisions[-1].revision == "0001"
    assert revisions[-1].down_revision is None


def test_env_py_imports_cleanly_and_renders_sql_for_postgres():
    sql = offline_sql("upgrade", "head")
    for table in TABLES:
        assert f"CREATE TABLE {table} (" in sql


# ---- naming convention ------------------------------------------------

def test_base_metadata_uses_the_naming_convention():
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert set(NAMING_CONVENTION) == {"ix", "uq", "ck", "fk", "pk"}


def test_baseline_creates_constraints_and_indexes_with_conventional_names():
    sql = offline_sql("upgrade", "head")
    for expected in (
        "CONSTRAINT pk_users PRIMARY KEY (id)",
        "CONSTRAINT uq_users_email UNIQUE (email)",
        "CONSTRAINT fk_tenders_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)",
        "CONSTRAINT fk_tender_items_tender_id_tenders FOREIGN KEY(tender_id) REFERENCES tenders (id) ON DELETE CASCADE",
        "CONSTRAINT fk_price_history_item_id_tender_items FOREIGN KEY(item_id) REFERENCES tender_items (id) ON DELETE CASCADE",
        "CREATE UNIQUE INDEX ix_tenders_prozorro_id ON tenders (prozorro_id)",
        "CREATE INDEX ix_price_history_created_at ON price_history (created_at)",
    ):
        assert expected in sql, expected


def test_baseline_keeps_the_price_source_default_and_nullable_unit_price():
    sql = offline_sql("upgrade", "head")
    assert "price_source VARCHAR(20) DEFAULT 'tender' NOT NULL" in sql
    assert "unit_price FLOAT," in sql  # nullable


def test_downgrade_drops_everything_in_dependency_order():
    sql = offline_sql("downgrade", "0001:base")
    positions = [sql.index(f"DROP TABLE {t}") for t in ("price_history", "tender_items", "tenders", "users")]
    assert positions == sorted(positions)


def test_startup_no_longer_creates_the_schema():
    source = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "create_all" not in source
    assert "ALTER TABLE" not in source


# ---- real database (skipped unless TEST_DATABASE_URL is set) ----------

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


async def table_names(url: str) -> set:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            )
            return {r[0] for r in rows}
    finally:
        await engine.dispose()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL to an empty Postgres database")
def test_upgrade_check_downgrade_round_trip_on_an_empty_database():
    cfg = alembic_config(database_url=TEST_DATABASE_URL)

    command.upgrade(cfg, "head")
    assert set(TABLES) <= asyncio.run(table_names(TEST_DATABASE_URL))
    command.check(cfg)  # models and migrations agree: raises if autogenerate finds a diff

    command.downgrade(cfg, "base")
    assert not set(TABLES) & asyncio.run(table_names(TEST_DATABASE_URL))
