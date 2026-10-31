from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="lisa-test-"))
os.environ["LISA_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["DATABASE_URL"] = os.getenv("LISA_TEST_DATABASE_URL") or f"sqlite:///{(TEST_DATA_DIR / 'lisa-test.db').as_posix()}"
os.environ["LISA_SEED"] = "1"
os.environ["LISA_ENV"] = "test"
os.environ["JWT_SECRET"] = "lisa-test-only-secret"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _login(client, username: str, password: str) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def planner(client):
    return _login(client, "planner", "planner123")


@pytest.fixture(scope="session")
def commander(client):
    return _login(client, "commander", "commander123")


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, "admin", "admin123")


@pytest.fixture(scope="session")
def engineer(client):
    return _login(client, "engineer", "engineer123")
