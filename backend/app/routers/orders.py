from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import KitCheck, Operation, Order, PlanItem, Resource, User
from ..services.kits import serialize_check
from ..services.metrics import latest_baseline
from ..services.serializers import order_to_dict

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require("plans:read"))):
    statuses = ["待排产", "已排产", "执行中", "逾期", "已完工", "冻结"]
    by_status = [{"status": s, "count": db.query(Order).filter(Order.status == s).count()} for s in statuses]
    by_priority = []
    for priority in ["P0", "P1", "P2"]:
        by_priority.append({"priority": priority, "count": db.query(Order).filter(Order.priority == priority).count()})
    return {
        "total": db.query(Order).count(),
        "by_status": by_status,
        "by_priority": by_priority,
        "military": db.query(Order).filter(Order.is_military.is_(True)).count(),
        "kit_risk": db.query(Order).filter(Order.kit_status != "齐套").count(),
    }


@router.get("")
def list_orders(
    status: str | None = None,
    priority: str | None = None,
    search: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:read")),
):
    query = db.query(Order)
    if status:
        query = query.filter(Order.status == status)
    if priority:
        query = query.filter(Order.priority == priority)
    if search:
        like = f"%{search}%"
        query = query.filter((Order.order_no.like(like)) | (Order.product_name.like(like)) | (Order.customer.like(like)))
    total = query.count()
    orders = query.order_by(Order.due_date.asc()).offset(offset).limit(limit).all()
    baseline = latest_baseline(db)
    item_map: dict[int, dict] = {}
    if baseline:
        rows = (
            db.query(
                PlanItem.order_id,
                func.min(PlanItem.start),
                func.max(PlanItem.end),
                func.count(PlanItem.id),
                func.sum(case((PlanItem.risk == "late", 1), else_=0)),
            )
            .filter(PlanItem.plan_id == baseline.id)
            .group_by(PlanItem.order_id)
            .all()
        )
        for order_id, start, end, count, late in rows:
            item_map[order_id] = {"start": start, "finish": end, "operations": count, "late": late or 0}
    items = []
    for order in orders:
        plan_info = item_map.get(order.id, {})
        late = 0
        if plan_info.get("finish") and plan_info["finish"] > order.due_date:
            late = max(1, int((plan_info["finish"] - order.due_date).total_seconds() / 3600))
        items.append(
            order_to_dict(
                order,
                {
                    "scheduled_start": plan_info.get("start").isoformat() if plan_info.get("start") else None,
                    "scheduled_finish": plan_info.get("finish").isoformat() if plan_info.get("finish") else None,
                    "scheduled_operations": plan_info.get("operations", 0),
                    "late_hours": late,
                    "risk": "late" if late > 0 else "normal",
                },
            )
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{order_id}")
def order_detail(order_id: int, db: Session = Depends(get_db), user: User = Depends(require("plans:read"))):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail={"code": "ORDER_NOT_FOUND", "message": "订单不存在"})
    operations = db.query(Operation).filter(Operation.order_id == order.id).order_by(Operation.seq).all()
    resources = {r.id: r for r in db.query(Resource).all()}
    checks = (
        db.query(KitCheck)
        .filter(KitCheck.order_id == order.id)
        .order_by(KitCheck.checked_at.desc())
        .all()
    )
    latest: dict[str, KitCheck] = {}
    for check in checks:
        if check.checkpoint not in latest:
            latest[check.checkpoint] = check
    return {
        "order": order_to_dict(order),
        "operations": [
            {
                "id": op.id,
                "seq": op.seq,
                "name": op.name,
                "domain": op.domain,
                "special": op.special,
                "status": op.status,
                "std_minutes": op.std_minutes,
                "setup_minutes": op.setup_minutes,
                "planned_start": op.planned_start.isoformat() if op.planned_start else None,
                "planned_end": op.planned_end.isoformat() if op.planned_end else None,
                "resource": resources[op.resource_id].name if op.resource_id in resources else None,
                "locked": op.locked,
                "risk": op.risk,
            }
            for op in operations
        ],
        "kits": [serialize_check(c) for c in latest.values()],
    }
