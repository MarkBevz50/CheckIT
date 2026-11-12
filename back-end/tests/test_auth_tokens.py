"""get_current_user: JWT validation (valid, expired, forged, malformed)."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.config import settings
from app.routers.authorization import ALGORITHM, create_access_token, get_current_user


async def test_valid_token_returns_email():
    token = create_access_token({"sub": "a@example.com"})
    assert await get_current_user(token) == "a@example.com"


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
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token_factory())
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


def test_token_is_signed_with_the_configured_key():
    token = create_access_token({"sub": "a@example.com"})
    assert jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])["sub"] == "a@example.com"


def test_protected_endpoint_requires_a_token():
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/tenders/")
    assert response.status_code == 401
