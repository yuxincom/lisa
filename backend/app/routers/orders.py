from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import clearance_cfg, plant_cfg, require
from ..models import KitCheck, Operation, Order, PlanItem, Resource, User
from ..services import clearance as clr
from ..services import plants as pl
from ..services.audit import log_user_action
from ..services.kits import serialize_check
from ..services.metrics import latest_baseline
from ..services.serializers import order_to_dict

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _cfg(db: Session) -> dict:
    return clearance_cfg(db)


def _scope(db: Session) -> tuple[dict, dict]:
    """读取范围两件套：密级 + 厂区。两条必须同时成立，放宽一条等于没过滤。"""
    return clearance_cfg(db), plant_cfg(db)


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require("plans:read"))):
    cfg, pcfg = _scope(db)
    statuses = ["待排产", "已排产", "执行中", "逾期", "已完工", "冻结"]

    def scoped():
        return db.query(Order).filter(
            clr.visible_filter(user, Order.clearance, cfg),
            pl.visible_filter(user, Order.plant, pcfg),
        )

    by_status = [{"status": s, "count": scoped().filter(Order.status == s).count()} for s in statuses]
    by_priority = []
    for priority in ["P0", "P1", "P2"]:
        by_priority.append({"priority": priority, "count": scoped().filter(Order.priority == priority).count()})
    return {
        "total": scoped().count(),
        "by_status": by_status,
        "by_priority": by_priority,
        "military": scoped().filter(Order.is_military.is_(True)).count(),
        "kit_risk": scoped().filter(Order.kit_status != "齐套").count(),
        "hidden_by_clearance": clr.hidden_count(db, Order, user, cfg),
        "hidden_by_level": clr.hidden_breakdown(db, Order, user, cfg),
        "hidden_by_plant": pl.hidden_breakdown(db, Order, user, pcfg),
        "clearance_levels": cfg["levels"] if cfg["enabled"] else [],
        "clearance_enabled": cfg["enabled"],
        "plants": pcfg["names"],
        "plants_enabled": pcfg["enabled"],
        "your_plants": pl.allowed(user, pcfg),
    }


@router.get("")
def list_orders(
    status: str | None = None,
    priority: str | None = None,
    plant: str | None = None,
    search: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:read")),
):
    cfg, pcfg = _scope(db)
    query = db.query(Order).filter(
        clr.visible_filter(user, Order.clearance, cfg),
        pl.visible_filter(user, Order.plant, pcfg),
    )
    if plant:
        # 界面选厂区只能是「在我能看的范围里再收窄」，不能借这个参数越范围
        query = query.filter(pl.label_expr(Order.plant, pcfg) == plant)
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
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "hidden_by_clearance": clr.hidden_count(db, Order, user, cfg),
        "hidden_by_plant": pl.hidden_count(db, Order, user, pcfg),
    }


@router.get("/{order_id}")
def order_detail(order_id: int, db: Session = Depends(get_db), user: User = Depends(require("plans:read"))):
    cfg, pcfg = _scope(db)
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail={"code": "ORDER_NOT_FOUND", "message": "订单不存在"})
    if not clr.can_read(user, order, cfg) or not pl.can_read(user, order, pcfg):
        denied_by = "clearance" if not clr.can_read(user, order, cfg) else "plant"
        log_user_action(
            db, user, f"{denied_by}.denied", "order", order.order_no, result="denied",
            detail={"required": order.clearance if denied_by == "clearance" else order.plant,
                    "reason": "读取范围（密级 / 厂区）过滤命中"},
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CLEARANCE_DENIED" if denied_by == "clearance" else "PLANT_DENIED",
                "message": (
                    f"{user.username} 的密级不足以查看工单 {order.order_no}"
                    if denied_by == "clearance"
                    else f"{user.username} 的厂区范围不含工单 {order.order_no} 所在的 {order.plant}"
                ),
            },
        )
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
