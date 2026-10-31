from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import Alert, User
from ..schemas import AcknowledgeRequest
from ..services.audit import log_user_action
from ..services.serializers import alert_to_dict

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require("alerts:read"))):
    rows = db.query(Alert).all()
    levels = {level: 0 for level in ("fatal", "critical", "warning", "info")}
    for row in rows:
        levels[row.level] = levels.get(row.level, 0) + 1
    open_rows = [r for r in rows if r.status == "open"]
    return {
        "total": len(rows),
        "open": len(open_rows),
        "acked": sum(1 for r in rows if r.status == "acked"),
        "levels": [{"level": k, "count": v} for k, v in levels.items()],
        "open_levels": [
            {"level": k, "count": sum(1 for r in open_rows if r.level == k)}
            for k in ("fatal", "critical", "warning", "info")
        ],
        "fatal_open": sum(1 for r in open_rows if r.level == "fatal"),
    }


@router.get("")
def list_alerts(
    status: str | None = None,
    level: str | None = None,
    type: str | None = None,
    search: str = "",
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("alerts:read")),
):
    query = db.query(Alert)
    if status:
        query = query.filter(Alert.status == status)
    if level:
        query = query.filter(Alert.level == level)
    if type:
        query = query.filter(Alert.type == type)
    if search:
        like = f"%{search}%"
        query = query.filter((Alert.title.like(like)) | (Alert.message.like(like)) | (Alert.code.like(like)))
    rows = query.order_by(Alert.created_at.desc()).limit(limit).all()
    return {"items": [alert_to_dict(a) for a in rows], "total": len(rows)}


@router.post("/ack")
def ack_batch(
    payload: AcknowledgeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("alerts:ack")),
):
    if not payload.alert_ids:
        raise HTTPException(status_code=400, detail={"code": "ALERT_IDS_REQUIRED", "message": "请选择要确认的告警"})
    rows = db.query(Alert).filter(Alert.id.in_(payload.alert_ids)).all()
    now = datetime.now().replace(microsecond=0)
    for alert in rows:
        alert.status = "acked"
        alert.acked_by = user.name
        alert.acked_at = now
    log_user_action(db, user, "alert.ack", "alert", ",".join(str(a.id) for a in rows), detail={"count": len(rows)})
    db.commit()
    return {"ok": True, "acked": len(rows)}


@router.post("/{alert_id}/ack")
def ack_one(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require("alerts:ack"))):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail={"code": "ALERT_NOT_FOUND", "message": "告警不存在"})
    alert.status = "acked"
    alert.acked_by = user.name
    alert.acked_at = datetime.now().replace(microsecond=0)
    log_user_action(db, user, "alert.ack", "alert", str(alert.id), detail={"level": alert.level, "title": alert.title})
    db.commit()
    return alert_to_dict(alert)
