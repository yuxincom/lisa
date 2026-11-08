from __future__ import annotations

"""异步任务队列：库行即队列，worker 轮询 claim。

为什么不用进程内线程池 / Redis / Celery：
- 进程内队列在 `--workers 1` 的容器里一重启就丢任务，而且丢得无声无息；
- 内网不允许多引入一个 Redis 依赖（也没有），而任务本身要能被审计、被查询、被重启后继续。
所以队列落在 `jobs` 表里：queued 的行就是「还没做完的事」，进程崩了、发布重启了，
下一个 worker 起来照样 claim 得到。

claim 用比较并交换（UPDATE ... WHERE id=? AND status='queued'）而不是 FOR UPDATE SKIP LOCKED：
后者 PostgreSQL 支持、SQLite 不支持，而这里必须两种库都能跑（测试用 SQLite）。
CAS 的语义对多副本同样成立：只有一个会话能把 queued 改成 running。
"""

import os
import socket
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..models import Job, User, now
from .audit import log_user_action

TERMINAL = ("succeeded", "failed", "cancelled")
DEFAULT_STALE_SECONDS = 180


class JobError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_handlers: dict[str, Callable[[Session, Job], dict]] = {}
_stop = threading.Event()


def handler(kind: str):
    """注册任务处理器。kind 必须是 snake_case 的已登记场景，未登记的 kind 入队即拒绝——
    宁可不入队，也不要入一个没人会执行的队。"""

    def deco(func: Callable[[Session, Job], dict]):
        _handlers[kind] = func
        return func

    return deco


def registered_kinds() -> list[str]:
    return sorted(_handlers)


def worker_id() -> str:
    return os.getenv("LISA_WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"


def enqueue(
    db: Session,
    kind: str,
    payload: dict | None = None,
    user: User | None = None,
    max_attempts: int = 1,
) -> Job:
    if kind not in _handlers:
        raise JobError("JOB_KIND_UNKNOWN", f"未登记的任务类型：{kind}（已登记：{', '.join(registered_kinds()) or '无'}）")
    job = Job(
        kind=kind,
        status="queued",
        payload=payload or {},
        actor_id=getattr(user, "id", None),
        created_by=getattr(user, "username", "") or "system",
        clearance=getattr(user, "clearance", "") or "内部",
        max_attempts=max_attempts,
        heartbeat_at=now(),
    )
    db.add(job)
    db.flush()
    if user is not None:
        log_user_action(db, user, "job.enqueue", "job", str(job.id),
                        detail={"kind": kind, "payload_keys": sorted((payload or {}).keys())})
    db.commit()
    db.refresh(job)
    return job


def claim(db: Session, worker: str | None = None) -> Job | None:
    """取一个 queued 任务并占为 running；并发下只有一个会话能成功。"""
    candidate = db.query(Job).filter(Job.status == "queued").order_by(Job.id.asc()).first()
    if candidate is None:
        return None
    stamp = now()
    updated = db.query(Job).filter(Job.id == candidate.id, Job.status == "queued").update(
        {Job.status: "running", Job.worker: worker or worker_id(), Job.started_at: stamp,
         Job.heartbeat_at: stamp, Job.attempt: candidate.attempt + 1},
        synchronize_session=False,
    )
    db.commit()
    if not updated:
        return None
    db.refresh(candidate)
    return candidate


def heartbeat(db: Session, job: Job, progress: int | None = None) -> None:
    values: dict[str, Any] = {"heartbeat_at": now()}
    if progress is not None:
        values["progress"] = max(0, min(100, int(progress)))
    db.query(Job).filter(Job.id == job.id).update(values, synchronize_session=False)
    db.commit()
    db.refresh(job)


def _finish(db: Session, job: Job, status: str, result: dict | None = None, error: dict | None = None) -> Job:
    values = {"status": status, "finished_at": now(), "heartbeat_at": now(), "worker": ""}
    if result is not None:
        values["result"] = result
    if error is not None:
        values["error"] = error
    if status == "succeeded":
        values["progress"] = 100
    db.query(Job).filter(Job.id == job.id).update(values, synchronize_session=False)
    db.commit()
    db.refresh(job)
    return job


def execute(db: Session, job: Job) -> Job:
    """就地跑一个已 claim 的任务。异常不外抛：失败写进 error，界面上看得见失败原因。"""
    func = _handlers.get(job.kind)
    if func is None:
        return _finish(db, job, "failed", error={"code": "JOB_KIND_UNKNOWN", "message": f"未登记的任务类型：{job.kind}"})
    try:
        result = func(db, job)
        heartbeat(db, job, 100)
        return _finish(db, job, "succeeded", result=result if isinstance(result, dict) else {"value": result})
    except Exception as exc:  # noqa: BLE001 - 后台任务必须把任何异常落成失败记录
        db.rollback()
        code = getattr(exc, "code", None) or exc.__class__.__name__
        message = str(exc) or exc.__class__.__name__
        retriable = job.attempt < max(1, job.max_attempts)
        if retriable:
            db.query(Job).filter(Job.id == job.id).update(
                {"status": "queued", "worker": "", "error": {"code": code, "message": message, "attempt": job.attempt}},
                synchronize_session=False,
            )
            db.commit()
            db.refresh(job)
            return job
        return _finish(db, job, "failed", error={"code": code, "message": message})


def run_once(db: Session, worker: str | None = None) -> Job | None:
    job = claim(db, worker)
    if job is None:
        return None
    return execute(db, job)


def recover_stale(db: Session, older_than_seconds: int = DEFAULT_STALE_SECONDS) -> list[int]:
    """running 但心跳停了 = worker 半路死了。放回 queued 或按 max_attempts 判死，不能永远卡在 running。"""
    cutoff = now() - timedelta(seconds=max(30, older_than_seconds))
    stale = db.query(Job).filter(Job.status == "running", Job.heartbeat_at < cutoff).all()
    ids = []
    for job in stale:
        if job.attempt < max(1, job.max_attempts):
            db.query(Job).filter(Job.id == job.id).update(
                {"status": "queued", "worker": "", "error": {"code": "JOB_WORKER_LOST",
                 "message": "执行该任务的进程没有再回来（发布重启或崩溃），已重新排队"}},
                synchronize_session=False,
            )
        else:
            _finish(db, job, "failed", error={"code": "JOB_WORKER_LOST",
                   "message": "执行进程失联且已达最大重试次数，任务未完成，请重新发起"})
        ids.append(job.id)
    if ids:
        db.commit()
    return ids


def queue_health(db: Session) -> dict:
    counts: dict[str, int] = {}
    for (status,) in db.query(Job.status).all():
        counts[status] = counts.get(status, 0) + 1
    oldest = db.query(Job).filter(Job.status == "queued").order_by(Job.id.asc()).first()
    running = db.query(Job).filter(Job.status == "running").all()
    return {
        "counts": counts,
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "worker_enabled": worker_enabled(),
        "worker_alive": _thread is not None and _thread.is_alive(),
        "worker_id": worker_id(),
        "kinds": registered_kinds(),
        "oldest_queued_seconds": int((now() - oldest.queued_at).total_seconds()) if oldest and oldest.queued_at else None,
        "silent_workers": sum(
            1 for job in running
            if job.heartbeat_at and job.heartbeat_at < now() - timedelta(seconds=DEFAULT_STALE_SECONDS)
        ),
    }


def worker_enabled() -> bool:
    return os.getenv("LISA_JOB_WORKER", "1").strip().lower() not in ("0", "false", "no")


def poll_once(db: Session) -> bool:
    """跑一轮：清理失联 → 取一个任务执行。返回是否真的执行了任务。"""
    recovered = recover_stale(db)
    if recovered:
        return True
    job = run_once(db)
    return job is not None


def _worker_loop(poll_seconds: float) -> None:
    from ..database import SessionLocal

    while not _stop.is_set():
        db = SessionLocal()
        try:
            worked = poll_once(db)
        except Exception:  # noqa: BLE001 - worker 线程不能因一次异常就退出
            worked = False
            db.rollback()
        finally:
            db.close()
        if not worked:
            _stop.wait(poll_seconds)


_thread: threading.Thread | None = None


def start_worker(poll_seconds: float = 1.5) -> bool:
    """在 API 进程里起一个 worker 线程。已经起了就返回 False，不重复起。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return False
    _stop.clear()
    _thread = threading.Thread(target=_worker_loop, args=(poll_seconds,), name="lisa-job-worker", daemon=True)
    _thread.start()
    return True


def stop_worker(timeout_seconds: float = 5.0) -> None:
    global _thread
    _stop.set()
    thread = _thread
    _thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout_seconds)


def drain(db: Session, max_jobs: int = 50) -> int:
    """同步把当前排队的任务跑完（测试与 CLI 用，绕开线程时序）。"""
    done = 0
    while done < max_jobs and run_once(db) is not None:
        done += 1
    return done


def job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress or 0,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "worker": job.worker,
        "created_by": job.created_by,
        "payload": job.payload or {},
        "result": job.result or {},
        "error": job.error or {},
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_seconds": (
            (job.finished_at - job.started_at).total_seconds()
            if job.started_at and job.finished_at
            else (now() - job.started_at).total_seconds() if job.started_at and job.status == "running"
            else None
        ),
    }


def enqueue_wait(db: Session, job: Job, timeout_seconds: float = 30.0, poll_seconds: float = 0.2) -> Job:
    """给 CLI / 测试用：等一个任务跑到终态，超时就把当前状态原样返回（不假装成功）。"""
    deadline = time.monotonic() + timeout_seconds
    while job.status not in TERMINAL and time.monotonic() < deadline:
        time.sleep(poll_seconds)
        db.expire_all()
        db.refresh(job)
    return job
