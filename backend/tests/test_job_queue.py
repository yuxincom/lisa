from __future__ import annotations

"""P2-9 后台任务队列：入队、领取、失败重试、失联回收、密级过滤。

这里的断言刻意不看「worker 线程跑没跑」——线程时序在 CI 上不靠得住。
被测的是队列本身的语义：行在库里、claim 互斥、失败有原因、失联能回收。
"""

import pytest

from app.models import Job
from app.services import jobs as jq


@jq.handler("test.ok")
def _handler_ok(db, job):
    return {"echo": job.payload.get("x", 0) + 1}


@jq.handler("test.fail")
def _handler_fail(db, job):
    db.rollback()
    raise RuntimeError("故意失败")


def test_unknown_kind_is_refused_at_enqueue(db, planner_user):
    with pytest.raises(jq.JobError) as exc:
        jq.enqueue(db, "test.nobody_will_run_this", {}, user=planner_user)
    assert exc.value.code == "JOB_KIND_UNKNOWN"
    db.rollback()
    assert db.query(Job).filter(Job.kind == "test.nobody_will_run_this").count() == 0


def test_agent_run_is_queued_then_drained(client, db, planner, run_agent):
    response = client.post("/api/agents/run", json={"scenario": "full"}, headers=planner)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["run"] is None, "入队即返回，不能假装已经跑完"
    job_id = body["job"]["id"]

    listed = client.get("/api/jobs", headers=planner).json()
    assert any(item["id"] == job_id for item in listed["items"])

    assert jq.drain(db) >= 1
    db.expire_all()
    job = db.get(Job, job_id)
    assert job.status == "succeeded", job.error
    assert job.result["run_id"]
    detail = client.get(f"/api/agents/runs/{job.result['run_id']}", headers=planner)
    assert detail.status_code == 200
    assert detail.json()["status"] == "succeeded"

    audit = client.get("/api/audit", params={"action": "job.enqueue"}, headers=planner).json()
    assert any(item["action"] == "job.enqueue" for item in audit["items"])


def test_failure_keeps_reason_and_honours_max_attempts(db, planner_user):
    job = jq.enqueue(db, "test.fail", {}, user=planner_user, max_attempts=2)
    jq.drain(db)
    db.expire_all()
    db.refresh(job)
    assert job.status == "failed"
    assert job.attempt == 2, "重试次数必须真的用满，否则 max_attempts 是假的"
    assert job.error["code"] == "RuntimeError"
    assert "故意失败" in job.error["message"]


def test_successful_handler_stores_result(db, planner_user):
    job = jq.enqueue(db, "test.ok", {"x": 41}, user=planner_user)
    assert jq.drain(db) >= 1
    db.expire_all()
    db.refresh(job)
    assert (job.status, job.progress) == ("succeeded", 100)
    assert job.result["echo"] == 42


def test_claim_is_exclusive_across_sessions(db, planner_user):
    from app.database import SessionLocal

    jq.enqueue(db, "test.ok", {"x": 1}, user=planner_user)
    first, second = SessionLocal(), SessionLocal()
    try:
        claimed = jq.claim(first)
        assert claimed is not None and claimed.status == "running"
        assert jq.claim(second) is None, "同一个任务被两个 worker 抢到就是重复排产"
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_stale_running_job_is_requeued_then_killed(db, planner_user):
    from datetime import timedelta

    job = jq.enqueue(db, "test.ok", {}, user=planner_user, max_attempts=2)
    jq.claim(db)
    db.expire_all()
    db.refresh(job)
    job.heartbeat_at = job.heartbeat_at - timedelta(seconds=600)
    db.commit()

    assert jq.recover_stale(db) == [job.id]
    db.expire_all()
    db.refresh(job)
    assert job.status == "queued"
    assert job.error["code"] == "JOB_WORKER_LOST"

    # 第二次失联时重试已用满，必须判死，不能永远在 running/queued 之间来回
    jq.claim(db)
    db.expire_all()
    db.refresh(job)
    job.heartbeat_at = job.heartbeat_at - timedelta(seconds=600)
    db.commit()
    jq.recover_stale(db)
    db.expire_all()
    db.refresh(job)
    assert job.status == "failed"


def test_only_queued_jobs_can_be_cancelled(client, db, admin, planner_user):
    job = jq.enqueue(db, "test.ok", {}, user=planner_user)
    cancelled = client.post(f"/api/jobs/{job.id}/cancel", headers=admin)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.post(f"/api/jobs/{job.id}/cancel", headers=admin).status_code == 409
    jq.drain(db)
    db.expire_all()
    db.refresh(job)
    assert job.status == "cancelled", "已取消的任务不能被 worker 再领走"


def test_queue_health_reports_worker_and_kinds(client, admin):
    health = client.get("/api/jobs/health", headers=admin).json()
    assert "test.ok" in health["kinds"]
    assert health["worker_id"]
    assert set(health["counts"]) <= {"queued", "running", "succeeded", "failed", "cancelled"}
    assert health["queued"] >= 0


def test_jobs_are_clearance_scoped(client, db, admin, engineer, planner_user):
    """任务行记的是「谁发起的排产」+ 产出引用，密级按发起人打标；
    高于阅读者等级的任务行谁都读不到，但数量必须如实报出来。"""
    job = jq.enqueue(db, "test.ok", {}, user=planner_user)
    job.clearance = "机密"
    db.commit()

    listed = client.get("/api/jobs", headers=engineer).json()
    assert all(item["id"] != job.id for item in listed["items"])
    assert listed["hidden_by_clearance"] >= 1
    denied = client.get(f"/api/jobs/{job.id}", headers=engineer)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "CLEARANCE_DENIED"
    assert client.get(f"/api/jobs/{job.id}", headers=admin).status_code == 200
