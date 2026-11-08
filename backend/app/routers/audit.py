from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import AuditLog, User
from ..services.anchor import AnchorError, append_anchor, path as anchor_path, verify_anchors
from ..services.audit import audit_stats, verify_chain
from ..services.serializers import audit_to_dict

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(require("audit:read"))):
    return audit_stats(db)


@router.get("/verify")
def verify(db: Session = Depends(get_db), user: User = Depends(require("audit:read"))):
    result = verify_chain(db)
    result["anchor"] = verify_anchors(db)
    result["tamper_evident"] = bool(result["ok"] and result["anchor"]["chain_ok"])
    return result


@router.post("/anchor")
def anchor(db: Session = Depends(get_db), user: User = Depends(require("audit:anchor"))):
    """把当前链尾锚定到库外文件；密钥缺失或无新记录时明确报错，不写「看似成功」的锚点。"""
    try:
        return append_anchor(db, user)
    except AnchorError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})


@router.get("/anchors")
def anchors(db: Session = Depends(get_db), user: User = Depends(require("audit:read"))):
    result = verify_anchors(db)
    file = anchor_path()
    history = []
    if file.exists():
        for line in file.read_text(encoding="utf-8").splitlines()[-20:]:
            if line.strip():
                record = json.loads(line)
                history.append(
                    {
                        "seq_from": record["seq_from"], "seq_to": record["seq_to"],
                        "records": record["records"], "ts": record["ts"], "actor": record.get("actor"),
                        "chain_hash": record["chain_hash"], "anchor_hash": record["anchor_hash"],
                    }
                )
    result["history"] = history
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
