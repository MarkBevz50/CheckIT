"""The /api/users endpoints are gone: with open registration they allowed reading and
deleting any user by id (IDOR)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.authorization import create_access_token


@pytest.fixture
def client():
    return TestClient(app)


def test_no_users_paths_in_the_api_schema(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "/users" in p]


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/api/users/", {"name": "a", "email": "a@example.com", "password": "p"}),
        ("get", "/api/users/1", None),
        ("delete", "/api/users/1", None),
    ],
)
def test_users_endpoints_return_404_with_and_without_a_token(client, method, path, body):
    token = create_access_token({"sub": "a@example.com"})
    kwargs = {"json": body} if body else {}
    for headers in ({}, {"Authorization": f"Bearer {token}"}):
        response = getattr(client, method)(path, headers=headers, **kwargs)
        assert response.status_code == 404


def test_register_and_login_are_still_mounted(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/auth/register" in paths
    assert "/auth/login" in paths
