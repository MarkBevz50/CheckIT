"""E0.13: every user works only with their own tenders. Real PostgreSQL, real JWTs, no mocks of the user lookup.

Why not SQLite: it does not enforce foreign keys by default, and the bug this step fixes (every handler
wrote `user_id = 1`) showed up exactly as a foreign-key violation. A security test that could not notice
that would be weak. The tests need `TEST_DATABASE_URL` (an empty Postgres database). Locally they are
skipped without it; in CI (`CI` is set) a missing variable is a failure, so they always run there.

Endpoint inventory (ownership check needed / present after E0.13):
  POST   /tenders/                        creates a tender for the caller                    -> user_id = caller
  GET    /tenders/                        list                                               -> filtered by owner
  GET    /tenders/{id}  PUT  DELETE       one tender                                         -> owner, else 404
  POST   /tenders/import/{prozorro_id}    creates a tender for the caller                    -> user_id = caller
  POST   /tenders/{id}/analyze            analysis of one tender                             -> owner, else 404
  GET    /tenders/{id}/price-history      history of the tender's items                      -> owner, else 404
  POST   /assistant/analyze-risks         risk analysis of one tender (tender_id in query)   -> login + owner, else 404
  POST   /excel-page                      works on the uploaded file only, nothing stored    -> login only
  GET    /search-tender/{contract_id}     public Prozorro data, nothing stored               -> login only
  POST   /analyze-documents/{ua_id}       public Prozorro documents, result not stored       -> login only
  GET    /stores/available, GET /         static, no user data                               -> public
  POST   /auth/register, /auth/login      authentication itself                              -> public
  POST   /assistant/perform-task          no tender data (chat, time, user_count)            -> login only (removed in E6.6)
"""

import asyncio
import os

import httpx  # noqa: F401  (TestClient dependency, imported to fail early if missing)
import pytest
import requests
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.database import get_db
from app.main import app
from app.models.model import User
from app.models.tender import PriceHistory, Tender, TenderItem
from app.routers.authorization import create_access_token
from tests.helpers import FakeResponse
from tests.test_import_tender import synthetic_tender
from tests.test_migrations import alembic_config

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
MISSING = 999_999  # an id that exists for nobody


@pytest.fixture(scope="module")
def database():
    if not TEST_DATABASE_URL:
        if os.environ.get("CI"):
            pytest.fail("TEST_DATABASE_URL must be set in CI: the user isolation tests need a real PostgreSQL")
        pytest.skip("set TEST_DATABASE_URL to an empty Postgres database")
    cfg = alembic_config(database_url=TEST_DATABASE_URL)
    command.upgrade(cfg, "head")
    yield TEST_DATABASE_URL
    command.downgrade(cfg, "base")


def session_factory():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)  # a new loop per call: no pooled connections
    return engine, sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def run_sql(work):
    """Run `async def work(session)` against the test database in its own event loop."""

    async def main():
        engine, factory = session_factory()
        try:
            async with factory() as session:
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


_counter = iter(range(1, 10_000))


def seed_tender(session, owner_id, title):
    """A tender with one item and one price-history row (flushed, not committed)."""

    async def build():
        tender = Tender(tender_type="product", prozorro_id=f"UA-SEED-{next(_counter):05d}", title=title, user_id=owner_id,
                        items=[TenderItem(name="Item of A", quantity=1.0, unit_name="шт", unit_price=10.0)])
        session.add(tender)
        await session.flush()
        session.add(PriceHistory(item_id=tender.items[0].id, source_store="rozetka", price=12.0,
                                 product_url="https://example.com/p"))
        await session.commit()
        return tender.id

    return build()


@pytest.fixture(scope="module")
def world(database):
    """Two users; user A owns one tender (id in world["tender"])."""

    async def seed(session):
        a = User(name="A", email="a@example.com", hashed_password="x")
        b = User(name="B", email="b@example.com", hashed_password="x")
        session.add_all([a, b])
        await session.flush()
        tender_id = await seed_tender(session, a.id, "Tender of A")
        return {"a": a.id, "b": b.id, "tender": tender_id}

    ids = run_sql(seed)
    ids["token_a"] = create_access_token({"sub": "a@example.com"})
    ids["token_b"] = create_access_token({"sub": "b@example.com"})
    return ids


@pytest.fixture
def fresh_tender(world):
    """A new tender of A for each test case, so that one destructive case cannot hide the next."""
    return run_sql(lambda session: seed_tender(session, world["a"], "Tender of A"))


@pytest.fixture
def client(database):
    async def override_db():
        engine, factory = session_factory()
        try:
            async with factory() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_db] = override_db  # only the database is replaced: get_current_user is the real one
    yield TestClient(app)
    app.dependency_overrides.clear()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- who is calling -----------------------------------------------------

def test_a_token_of_a_user_who_does_not_exist_is_rejected(client, world):
    ghost = create_access_token({"sub": "deleted@example.com"})
    response = client.get("/tenders/", headers=auth(ghost))
    assert response.status_code == 401


PROTECTED = [
    ("post", "/tenders/", {"json": {"tender_type": "product", "prozorro_id": "X", "title": "T"}}),
    ("get", "/tenders/", {}),
    ("get", f"/tenders/{MISSING}", {}),
    ("put", f"/tenders/{MISSING}", {"json": {"title": "T"}}),
    ("delete", f"/tenders/{MISSING}", {}),
    ("post", "/tenders/import/abc", {}),
    ("post", f"/tenders/{MISSING}/analyze", {}),
    ("get", f"/tenders/{MISSING}/price-history", {}),
    ("post", f"/assistant/analyze-risks?tender_id={MISSING}", {}),
    ("post", "/excel-page", {"files": {"file": ("a.xlsx", b"x")}}),
    ("post", "/assistant/perform-task", {"json": {"task": "time"}}),
    ("get", "/search-tender/abc", {}),
    ("post", "/analyze-documents/UA-2026-01-01-000001-a", {}),
]


@pytest.mark.parametrize("method,path,kwargs", PROTECTED, ids=[f"{m} {p}" for m, p, _ in PROTECTED])
def test_every_endpoint_that_touches_user_data_requires_a_login(client, world, method, path, kwargs):
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401, f"{method.upper()} {path} answered {response.status_code} without a token"


# ---- another user's tender ------------------------------------------------

FOREIGN = [
    ("get", "/tenders/{id}", {}),
    ("put", "/tenders/{id}", {"json": {"title": "Hijacked"}}),
    ("delete", "/tenders/{id}", {}),
    ("post", "/tenders/{id}/analyze", {}),
    ("get", "/tenders/{id}/price-history", {}),
    ("post", "/assistant/analyze-risks?tender_id={id}", {}),
]


@pytest.mark.parametrize("method,path,kwargs", FOREIGN, ids=[f"{m} {p}" for m, p, _ in FOREIGN])
def test_a_user_cannot_reach_a_tender_of_another_user(client, world, fresh_tender, method, path, kwargs):
    send = getattr(client, method)
    foreign = send(path.format(id=fresh_tender), headers=auth(world["token_b"]), **kwargs)
    absent = send(path.format(id=MISSING), headers=auth(world["token_b"]), **kwargs)

    assert foreign.status_code == 404
    # indistinguishable from a tender that does not exist, so it does not even confirm that it exists
    assert (foreign.status_code, foreign.json()) == (absent.status_code, absent.json())


def test_the_attempts_above_changed_nothing(client, world, fresh_tender):
    for method, path, kwargs in FOREIGN:
        getattr(client, method)(path.format(id=fresh_tender), headers=auth(world["token_b"]), **kwargs)

    response = client.get(f"/tenders/{fresh_tender}", headers=auth(world["token_a"]))
    assert response.status_code == 200
    assert response.json()["title"] == "Tender of A"
    assert len(response.json()["items"]) == 1


def test_the_owner_still_has_access(client, world):
    headers = auth(world["token_a"])
    assert client.get(f"/tenders/{world['tender']}", headers=headers).status_code == 200
    history = client.get(f"/tenders/{world['tender']}/price-history", headers=headers)
    assert history.status_code == 200
    assert history.json()["items"][0]["item_name"] == "Item of A"


def test_the_list_shows_only_own_tenders(client, world):
    listed = client.get("/tenders/", headers=auth(world["token_a"])).json()
    assert world["tender"] in [t["id"] for t in listed]
    assert client.get("/tenders/", headers=auth(world["token_b"])).json() == []


# ---- who owns what a user creates -----------------------------------------------

def test_a_created_tender_belongs_to_its_creator(client, world):
    payload = {"tender_type": "product", "prozorro_id": "UA-B-0001", "title": "Tender of B", "total_amount": 20.0,
               "items": [{"name": "Item of B", "quantity": 2, "unit_name": "шт", "unit_price": 10.0}]}
    response = client.post("/tenders/", json=payload, headers=auth(world["token_b"]))
    assert response.status_code == 201, response.text

    async def owner(session):
        return (await session.execute(select(Tender.user_id).where(Tender.prozorro_id == "UA-B-0001"))).scalar_one()

    assert run_sql(owner) == world["b"]


def test_an_imported_tender_belongs_to_the_importer(client, world, monkeypatch):
    body = synthetic_tender("aaaa0000bbbb1111cccc2222dddd3333", "Імпортований товар")
    monkeypatch.setattr(
        requests, "get",
        lambda url, *a, **k: FakeResponse(200, body) if url.endswith("/tenders/aaaa0000bbbb1111cccc2222dddd3333")
        else FakeResponse(404, {"errors": []}),
    )
    response = client.post("/tenders/import/aaaa0000bbbb1111cccc2222dddd3333", headers=auth(world["token_b"]))
    assert response.status_code == 201, response.text

    async def owner(session):
        query = select(Tender.user_id).where(Tender.prozorro_id == "aaaa0000bbbb1111cccc2222dddd3333")
        return (await session.execute(query)).scalar_one()

    assert run_sql(owner) == world["b"]
    # and A, who did not import it, does not see it
    assert "aaaa0000bbbb1111cccc2222dddd3333" not in [
        t["prozorro_id"] for t in client.get("/tenders/", headers=auth(world["token_a"])).json()
    ]
