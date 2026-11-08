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


@pytest.fixture(scope="session")
def db(client):
    """服务层单测直连测试库，不绕 HTTP。"""
    from app.database import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="session")
def planner_user(db):
    from app.models import User

    return db.query(User).filter(User.username == "planner").first()


@pytest.fixture(scope="session")
def run_agent(client, db):
    """POST /api/agents/run 现在只入队（202），编排落在后台任务里。

    测试要断言的是「跑完的 run」，所以这里把队列同步 drain 掉再取回结果，
    不依赖 worker 线程的时序。
    """
    from app.models import Job
    from app.services import jobs as job_queue

    def _run(headers, scenario, change_id=None, options=None) -> dict:
        body = {"scenario": scenario, "options": options or {}}
        if change_id:
            body["change_id"] = change_id
        response = client.post("/api/agents/run", json=body, headers=headers)
        assert response.status_code == 202, response.text
        job_id = response.json()["job"]["id"]
        assert job_queue.drain(db) >= 1, "队列为空：任务没入队"
        db.expire_all()
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job is not None and job.status == "succeeded", job.error if job else "任务丢失"
        detail = client.get(f"/api/agents/runs/{job.result['run_id']}", headers=headers)
        assert detail.status_code == 200, detail.text
        return detail.json()

    return _run
