"""get_current_user: JWT validation (valid, expired, forged, malformed) and the user lookup (E0.13)."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.config import settings
from app.models.model import User
from app.routers.authorization import ALGORITHM, create_access_token, get_current_user


class FakeDb:
    """AsyncSession stand-in whose users table holds `user` (or nothing)."""

    def __init__(self, user=None):
        self.user = user
        self.queries = 0

    async def execute(self, *args, **kwargs):
        self.queries += 1
        user = self.user

        class Result:
            def scalar_one_or_none(self):
                return user

        return Result()


async def test_valid_token_returns_the_user_object():
    user = User(id=5, name="A", email="a@example.com")
    token = create_access_token({"sub": "a@example.com"})
    assert await get_current_user(token, FakeDb(user)) is user


async def test_valid_token_of_a_user_that_does_not_exist_is_rejected_with_401():
    token = create_access_token({"sub": "gone@example.com"})
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token, FakeDb(None))
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "token_factory",
    [
        lambda: create_access_token({"sub": "a@example.com"}, expires_delta=timedelta(minutes=-1)),
        lambda: jwt.encode({"sub": "a@example.com"}, "another-secret", algorithm=ALGORITHM),
        lambda: create_access_token({"no_sub": True}),
        lambda: "not-a-jwt",
        lambda: "",
    ],
    ids=["expired", "forged-signature", "missing-sub", "garbage", "empty"],
)
async def test_invalid_token_is_rejected_with_401(token_factory):
    db = FakeDb(User(id=5, name="A", email="a@example.com"))
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token_factory(), db)
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}
    assert db.queries == 0  # an invalid token never reaches the database


def test_token_is_signed_with_the_configured_key():
    token = create_access_token({"sub": "a@example.com"})
    assert jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])["sub"] == "a@example.com"


def test_protected_endpoint_requires_a_token():
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/tenders/")
    assert response.status_code == 401


def test_assistant_endpoints_require_a_token():
    """/assistant/perform-task spends the Hugging Face key and reveals the user count: login only."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for task in ("chat", "user_count", "time", "help"):
        response = client.post("/assistant/perform-task", json={"task": task, "message": "hi"})
        assert response.status_code == 401, task
