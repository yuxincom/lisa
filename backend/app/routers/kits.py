from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import KitCheck, Order, User
from ..schemas import KitCheckRequest
from ..services.audit import log_user_action
from ..services.kits import CHECKPOINT_LABELS, kit_overview, persist_check, serialize_check

router = APIRouter(prefix="/api/kits", tags=["kits"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(require("kits:read"))):
    return kit_overview(db)


@router.get("")
def list_checks(
    checkpoint: str = "post_schedule",
    status: str | None = None,
    search: str = "",
    limit: int = Query(60, ge=1, le=300),
    db: Session = Depends(get_db),
    user: User = Depends(require("kits:read")),
):
    query = db.query(KitCheck).filter(KitCheck.checkpoint == checkpoint)
    if status:
        query = query.filter(KitCheck.status == status)
    if search:
        like = f"%{search}%"
        query = query.filter((KitCheck.order_no.like(like)) | (KitCheck.product_name.like(like)))
    rows = query.order_by(KitCheck.checked_at.desc()).limit(limit * 3).all()
    latest: dict[int, KitCheck] = {}
    for row in rows:
        if row.order_id not in latest:
            latest[row.order_id] = row
    items = [serialize_check(c) for c in list(latest.values())[:limit]]
    counts = {
        "齐套": sum(1 for c in items if c["status"] == "齐套"),
        "缺项": sum(1 for c in items if c["status"] == "缺项"),
        "阻断": sum(1 for c in items if c["status"] == "阻断"),
    }
    return {
        "items": items,
        "checkpoint": checkpoint,
        "checkpoint_label": CHECKPOINT_LABELS.get(checkpoint, checkpoint),
        "counts": counts,
        "total": len(items),
    }


@router.post("/check")
def run_check(
    payload: KitCheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("kits:read")),
):
    order = db.get(Order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail={"code": "ORDER_NOT_FOUND", "message": "订单不存在"})
    if payload.checkpoint not in CHECKPOINT_LABELS:
        raise HTTPException(status_code=400, detail={"code": "CHECKPOINT_INVALID", "message": "检查时点非法"})
    check = persist_check(db, order, payload.checkpoint)
    log_user_action(
        db, user, "kit.check", "order", order.order_no,
        detail={"checkpoint": payload.checkpoint, "status": check.status, "score": check.score, "gaps": len(check.gaps or [])},
    )
    db.commit()
    db.refresh(check)
    return serialize_check(check)


@router.get("/{order_id}")
def order_kits(order_id: int, db: Session = Depends(get_db), user: User = Depends(require("kits:read"))):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail={"code": "ORDER_NOT_FOUND", "message": "订单不存在"})
    checks = (
        db.query(KitCheck)
        .filter(KitCheck.order_id == order_id)
        .order_by(KitCheck.checked_at.desc())
        .all()
    )
    latest: dict[str, KitCheck] = {}
    for check in checks:
        if check.checkpoint not in latest:
            latest[check.checkpoint] = check
    return {
        "order": {
            "id": order.id,
            "order_no": order.order_no,
            "product_name": order.product_name,
            "priority": order.priority,
            "kit_status": order.kit_status,
            "due_date": order.due_date.isoformat(),
        },
        "checkpoints": [serialize_check(latest[cp]) for cp in CHECKPOINT_LABELS if cp in latest],
    }
