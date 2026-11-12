"""Login/register error handling: proper 4xx instead of 500 (no real database)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.main import app
from app.routers.authorization import (
    EMAIL_TAKEN_MESSAGE,
    INVALID_CREDENTIALS_MESSAGE,
    get_password_hash,
)

PASSWORD = "Passw0rd!x"


class FakeResult:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user


class FakeSession:
    """Just enough of AsyncSession for the auth endpoints."""

    def __init__(self, user=None, execute_error=None, commit_error=None):
        self.user = user
        self.execute_error = execute_error
        self.commit_error = commit_error
        self.rolled_back = False

    async def execute(self, *args, **kwargs):
        if self.execute_error:
            raise self.execute_error
        return FakeResult(self.user)

    def add(self, obj):
        pass

    async def commit(self):
        if self.commit_error:
            raise self.commit_error

    async def refresh(self, obj):
        pass

    async def rollback(self):
        self.rolled_back = True


@pytest.fixture
def client_for():
    def make(session):
        async def override():
            yield session

        app.dependency_overrides[get_db] = override
        return TestClient(app)

    yield make
    app.dependency_overrides.pop(get_db, None)


def existing_user():
    return SimpleNamespace(
        name="t", email="a@example.com", hashed_password=get_password_hash(PASSWORD)
    )


def login(client, email="a@example.com", password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def register(client, email="a@example.com"):
    return client.post("/auth/register", json={"name": "t", "email": email, "password": PASSWORD})


# ---- login ------------------------------------------------------------

def test_login_unknown_email_returns_401_with_message(client_for):
    response = login(client_for(FakeSession(user=None)))
    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE


def test_login_wrong_password_returns_401_with_same_message(client_for):
    response = login(client_for(FakeSession(user=existing_user())), password="wrong-password")
    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE


def test_login_success_returns_token(client_for):
    response = login(client_for(FakeSession(user=existing_user())))
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_database_failure_is_still_500(client_for):
    response = login(client_for(FakeSession(execute_error=RuntimeError("db down"))))
    assert response.status_code == 500
    assert response.json()["detail"] == "Login failed"


# ---- register ---------------------------------------------------------

def test_register_existing_email_returns_400_with_message(client_for):
    session = FakeSession(user=existing_user())
    response = register(client_for(session))
    assert response.status_code == 400
    assert response.json()["detail"] == EMAIL_TAKEN_MESSAGE
    assert session.rolled_back


def test_register_concurrent_duplicate_returns_400(client_for):
    session = FakeSession(user=None, commit_error=IntegrityError("INSERT", {}, Exception("dup")))
    response = register(client_for(session))
    assert response.status_code == 400
    assert response.json()["detail"] == EMAIL_TAKEN_MESSAGE
    assert session.rolled_back


def test_register_success_returns_201_and_token(client_for):
    response = register(client_for(FakeSession(user=None)))
    assert response.status_code == 201
    assert response.json()["access_token"]


def test_register_database_failure_is_still_500(client_for):
    response = register(client_for(FakeSession(execute_error=RuntimeError("db down"))))
    assert response.status_code == 500
