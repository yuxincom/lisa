from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import clearance_cfg, require
from ..models import Job, User, now
from ..services import jobs as job_queue
from ..services import clearance as clr
from ..services.audit import log_user_action

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    return job


@router.get("")
def list_jobs(
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("jobs:read")),
):
    cfg = clearance_cfg(db)
    query = db.query(Job).filter(clr.visible_filter(user, Job.clearance, cfg))
    if status:
        query = query.filter(Job.status == status)
    if kind:
        query = query.filter(Job.kind == kind)
    rows = query.order_by(Job.id.desc()).limit(limit).all()
    for job in rows:
        clr.guard(user, job, cfg)
    return {
        "items": [job_queue.job_to_dict(job) for job in rows],
        "hidden_by_clearance": clr.hidden_count(db, Job, user, cfg),
        "clearance_enabled": cfg["enabled"],
    }


@router.get("/health")
def health(db: Session = Depends(get_db), user: User = Depends(require("jobs:read"))):
    """队列体检：worker 活着没、排队最久等了多久、有没有失联的执行进程。

    「任务在排队」和「没人处理任务」是两件完全不同的事，界面上必须分得开。
    """
    return job_queue.queue_health(db)


@router.get("/{job_id}")
def detail(job_id: int, db: Session = Depends(get_db), user: User = Depends(require("jobs:read"))):
    cfg = clearance_cfg(db)
    job = _get(db, job_id)
    try:
        clr.guard(user, job, cfg)
    except clr.ClearanceError as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": exc.message}) from exc
    return job_queue.job_to_dict(job)


@router.post("/{job_id}/cancel")
def cancel(job_id: int, db: Session = Depends(get_db), user: User = Depends(require("jobs:cancel"))):
    """只取消还没被 claim 的任务。已经在跑的重排不硬砍——砍在半路会留下半成品方案，
    比等它跑完更危险；要中止请连进程一起停，失联任务由 recover_stale 收尾。"""
    cfg = clearance_cfg(db)
    job = _get(db, job_id)
    try:
        clr.guard(user, job, cfg)
    except clr.ClearanceError as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": exc.message}) from exc
    updated = db.query(Job).filter(Job.id == job.id, Job.status == "queued").update(
        {"status": "cancelled", "finished_at": now(), "worker": ""}, synchronize_session=False
    )
    if not updated:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_NOT_CANCELLABLE", "message": f"任务当前 {job.status}，只有排队中的任务可取消"},
        )
    db.commit()
    db.refresh(job)
    log_user_action(db, user, "job.cancel", "job", str(job.id), detail={"kind": job.kind})
    db.commit()
    return job_queue.job_to_dict(job)
