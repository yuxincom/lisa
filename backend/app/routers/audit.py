from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import AuditLog, User
from ..services.audit import audit_stats, verify_chain
from ..services.serializers import audit_to_dict

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(require("audit:read"))):
    return audit_stats(db)


@router.get("/verify")
def verify(db: Session = Depends(get_db), user: User = Depends(require("audit:read"))):
    result = verify_chain(db)
    return result


@router.get("")
def list_logs(
    action: str | None = None,
    actor: str | None = None,
    result: str | None = None,
    search: str = "",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require("audit:read")),
):
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor.like(f"%{actor}%"))
    if result:
        query = query.filter(AuditLog.result == result)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (AuditLog.action.like(like)) | (AuditLog.target_id.like(like)) | (AuditLog.actor.like(like))
        )
    total = query.count()
    rows = query.order_by(AuditLog.seq.desc()).offset(offset).limit(limit).all()
    return {"items": [audit_to_dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{log_id}")
def detail(log_id: int, db: Session = Depends(get_db), user: User = Depends(require("audit:read"))):
    log = db.get(AuditLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail={"code": "AUDIT_NOT_FOUND", "message": "审计日志不存在"})
    data = audit_to_dict(log)
    prev = db.query(AuditLog).filter(AuditLog.seq == log.seq - 1).first()
    data["prev_log"] = {"seq": prev.seq, "hash": prev.hash, "ts": prev.ts.isoformat()} if prev else None
    return data
