from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import clearance_cfg, require
from ..models import Disturbance, User
from ..schemas import ChangeCreateRequest
from ..services import clearance as clr
from ..services.audit import log_user_action
from ..services.impact import (
    TYPE_LABEL,
    assess_disturbance,
    create_change_plans,
    create_disturbance,
    relabel_disturbance_clearance,
)
from ..services.serializers import change_to_dict, plan_to_dict

router = APIRouter(prefix="/api/changes", tags=["changes"])

STATUS_ORDER = ["评估中", "评估完成", "待审批", "已关闭", "已挂起"]


def _guard(db: Session, user: User, change: Disturbance) -> dict:
    """事件密级 = 受影响工单里的最高密级；本人申报的事件可以读回来，但影响面明细仍按密级脱敏。"""
    cfg = clearance_cfg(db)
    if clr.can_read(user, change, cfg) or (change.reporter and change.reporter == user.name):
        return cfg
    log_user_action(db, user, "clearance.denied", "change", change.code, result="denied",
                    detail={"required": change.clearance, "surface": "changes"})
    db.commit()
    raise HTTPException(
        status_code=403,
        detail={"code": "CLEARANCE_DENIED", "message": f"{user.username} 的密级不足以查看变更事件 {change.code}"},
    )


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require("changes:read"))):
    cfg = clearance_cfg(db)
    all_changes = db.query(Disturbance).filter(clr.visible_filter(user, Disturbance.clearance, cfg)).all()
    counts = {status: 0 for status in STATUS_ORDER}
    for change in all_changes:
        counts[change.status] = counts.get(change.status, 0) + 1
    type_counts: dict[str, int] = {}
    for change in all_changes:
        label = TYPE_LABEL.get(change.type, change.type)
        type_counts[label] = type_counts.get(label, 0) + 1
    open_changes = [c for c in all_changes if c.status not in ("已关闭",)]
    critical = sum(1 for c in open_changes if c.severity == "critical")
    return {
        "total": len(all_changes),
        "open": len(open_changes),
        "critical": critical,
        "counts": [{"status": k, "count": v} for k, v in counts.items()],
        "types": [{"type": k, "count": v} for k, v in type_counts.items()],
        "sla_minutes": 15,
        "sla_target": "≤15min",
        "hidden_by_clearance": clr.hidden_count(db, Disturbance, user, cfg),
        "clearance_enabled": cfg["enabled"],
    }


@router.get("")
def list_changes(
    status: str | None = None,
    type: str | None = None,
    search: str = "",
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require("changes:read")),
):
    cfg = clearance_cfg(db)
    query = db.query(Disturbance).filter(clr.visible_filter(user, Disturbance.clearance, cfg))
    if status:
        query = query.filter(Disturbance.status == status)
    if type:
        query = query.filter(Disturbance.type == type)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Disturbance.title.like(like)) | (Disturbance.code.like(like)) | (Disturbance.detail.like(like))
        )
    rows = query.order_by(Disturbance.occurred_at.desc()).limit(limit).all()
    return {
        "items": [change_to_dict(c, user, cfg) for c in rows],
        "total": len(rows),
        "hidden_by_clearance": clr.hidden_count(db, Disturbance, user, cfg),
    }


@router.post("")
def create(
    payload: ChangeCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("changes:create")),
):
    if payload.type not in TYPE_LABEL:
        raise HTTPException(status_code=400, detail={"code": "CHANGE_TYPE_INVALID", "message": "不支持的扰动类型"})
    cfg = clearance_cfg(db)
    change = create_disturbance(
        db, payload.type, payload.title, payload.detail, payload.severity, payload.payload, reporter=user.name
    )
    code = change.code
    body = change_to_dict(change, user, cfg)
    log_user_action(
        db, user, "change.create", "change", code,
        detail={"type": payload.type, "severity": payload.severity, "clearance": change.clearance,
                "redacted_affected": body["redacted_affected"]},
    )
    db.commit()
    db.refresh(change)
    return change_to_dict(change, user, cfg)


def _get(db: Session, user: User, change_id: int) -> tuple[Disturbance, dict]:
    change = db.get(Disturbance, change_id)
    if not change:
        raise HTTPException(status_code=404, detail={"code": "CHANGE_NOT_FOUND", "message": "扰动事件不存在"})
    return change, _guard(db, user, change)


@router.post("/relabel")
def relabel(db: Session = Depends(get_db), user: User = Depends(require("changes:approve"))):
    """存量事件的密级按当前等级表重算（幂等）。改完等级表或批量重新打标工单后调一次，不必重启。"""
    try:
        result = relabel_disturbance_clearance(db)
    except clr.ClearanceError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    log_user_action(db, user, "change.relabel", "disturbance", "batch", detail=result)
    db.commit()
    return result


@router.get("/{change_id}")
def detail(change_id: int, db: Session = Depends(get_db), user: User = Depends(require("changes:read"))):
    change, cfg = _get(db, user, change_id)
    return change_to_dict(change, user, cfg)


@router.post("/{change_id}/assess")
def assess(change_id: int, db: Session = Depends(get_db), user: User = Depends(require("changes:create"))):
    change, cfg = _get(db, user, change_id)
    impact = assess_disturbance(db, change)
    change.status = "评估完成" if change.status == "评估中" else change.status
    change.occurred_at = change.occurred_at or datetime.now()
    log_user_action(db, user, "change.assess", "change", change.code, detail={"affected_orders": impact["summary"]["affected_orders"]})
    db.commit()
    db.refresh(change)
    return change_to_dict(change, user, cfg)


@router.post("/{change_id}/plans")
def generate_plans(change_id: int, db: Session = Depends(get_db), user: User = Depends(require("changes:create"))):
    change, cfg = _get(db, user, change_id)
    if change.status in ("已关闭",):
        raise HTTPException(status_code=409, detail={"code": "CHANGE_CLOSED", "message": "事件已关闭，不可生成方案"})
    plans = create_change_plans(db, user, change, scenarios=("A", "B"))
    log_user_action(db, user, "change.plans.generate", "change", change.code, detail={"plans": [p.code for p in plans]})
    db.commit()
    return {
        "change": change_to_dict(change, user, cfg),
        "plans": [plan_to_dict(p, db) for p in plans],
    }


@router.post("/{change_id}/resolve")
def resolve(change_id: int, db: Session = Depends(get_db), user: User = Depends(require("changes:approve"))):
    change, cfg = _get(db, user, change_id)
    change.status = "已关闭"
    change.resolved_at = datetime.now().replace(microsecond=0)
    log_user_action(db, user, "change.resolve", "change", change.code, detail={"note": "人工关闭事件"})
    db.commit()
    db.refresh(change)
    return change_to_dict(change, user, cfg)
