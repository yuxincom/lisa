from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Disturbance, Operation, Order, Resource, User
from . import clearance
from .serializers import iso

TYPE_PREFIX = {
    "fault": "GZ",
    "material": "WL",
    "insert": "CJ",
    "rework": "FG",
    "order_change": "DD",
    "inspection": "TS",
    "ecn": "ECN",
}
TYPE_LABEL = {
    "fault": "设备故障",
    "material": "物料缺料",
    "insert": "紧急插单",
    "rework": "返工返修",
    "order_change": "订单变更",
    "inspection": "检测军检",
    "ecn": "工艺变更",
}


def relabel_disturbance_clearance(db: Session) -> dict:
    """扰动事件的密级是派生值：始终等于受影响工单里的最高密级，可重复执行。

    老库升级、seed 直接插入、工单密级改动后都靠它把标签纠正过来——不写「内部」占位，
    因为那等于把一条本来涉密的事件降级成谁都能看。
    """
    cfg = clearance.config(db)
    rows = db.query(Disturbance).all()
    relabelled = 0
    for change in rows:
        label = clearance.highest([order.clearance for order in _affected_orders(db, change)], cfg)
        if (change.clearance or "") != label:
            change.clearance = label
            relabelled += 1
    return {"total": len(rows), "relabelled": relabelled, "levels": cfg["levels"]}


def create_disturbance(
    db: Session,
    change_type: str,
    title: str,
    detail: str = "",
    severity: str = "warning",
    payload: dict | None = None,
    reporter: str = "系统事件总线",
) -> Disturbance:
    prefix = TYPE_PREFIX.get(change_type, "EVT")
    now = datetime.now().replace(microsecond=0)
    code = f"{prefix}-{now:%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"
    change = Disturbance(
        code=code,
        type=change_type,
        title=title,
        detail=detail,
        severity=severity,
        status="评估中",
        occurred_at=now,
        payload=payload or {},
        reporter=reporter,
    )
    db.add(change)
    db.flush()
    change.clearance = clearance.highest([order.clearance for order in _affected_orders(db, change)], clearance.config(db))
    assess_disturbance(db, change)
    return change


def _affected_orders(db: Session, change: Disturbance) -> list[Order]:
    payload = change.payload or {}
    order_ids = payload.get("order_ids") or []
    if order_ids:
        return db.query(Order).filter(Order.id.in_(order_ids)).all()
    resource_id = payload.get("resource_id")
    if resource_id:
        ops = (
            db.query(Operation)
            .filter(Operation.resource_id == resource_id, Operation.planned_end >= change.occurred_at)
            .order_by(Operation.planned_start.asc())
            .limit(120)
            .all()
        )
        ids = list(dict.fromkeys(op.order_id for op in ops))
        if ids:
            return db.query(Order).filter(Order.id.in_(ids)).all()
    return (
        db.query(Order)
        .filter(~Order.status.in_(["已完工", "已取消"]))
        .order_by(Order.due_date.asc())
        .limit(6)
        .all()
    )


def assess_disturbance(db: Session, change: Disturbance) -> dict:
    payload = change.payload or {}
    orders = _affected_orders(db, change)
    started = datetime.now()
    now = datetime.now().replace(microsecond=0)
    delay_hours = float(payload.get("delay_hours", 8 if change.severity != "critical" else 18))
    resource = db.get(Resource, int(payload["resource_id"])) if payload.get("resource_id") else None

    affected = []
    domain_set: dict[str, int] = {}
    total_ops = 0
    critical = 0
    max_late_days = 0.0
    projected_delays = []
    for order in orders[:8]:
        remaining = (
            db.query(Operation)
            .filter(Operation.order_id == order.id, Operation.seq >= 1)
            .all()
        )
        future = [o for o in remaining if not o.planned_end or o.planned_end >= now]
        finish = max([o.planned_end for o in remaining if o.planned_end] or [now])
        projected = finish + timedelta(hours=delay_hours)
        late_days = max(0.0, (projected - order.due_date).total_seconds() / 86400)
        domains = sorted({o.domain for o in future})
        for d in domains:
            domain_set[d] = domain_set.get(d, 0) + 1
        total_ops += len(future)
        if order.priority == "P0":
            critical += 1
        max_late_days = max(max_late_days, late_days)
        projected_delays.append(late_days)
        affected.append(
            {
                "order_id": order.id,
                "order_no": order.order_no,
                "product_name": order.product_name,
                "priority": order.priority,
                "clearance": order.clearance or "内部",
                "due_date": iso(order.due_date),
                "current_finish": iso(finish),
                "projected_finish": iso(projected),
                "late_days": round(late_days, 1),
                "domains": domains,
                "operations": len(future),
                "status": order.status,
                "kit_status": order.kit_status,
            }
        )

    avg_delay = sum(projected_delays) / len(projected_delays) if projected_delays else 0
    affected_count = len(affected)
    moved_ops = max(1, int(total_ops * 0.35))
    elapsed_seconds = max(0.001, (datetime.now() - started).total_seconds())
    grounded = sum(1 for item in affected if item["operations"] > 0)
    confidence = round(0.55 + 0.45 * (grounded / affected_count), 2) if affected_count else 0.0
    assumptions = []
    if not payload.get("delay_hours"):
        assumptions.append(
            f"事件未上报延误工时，按严重度默认 {delay_hours:g}h 推演（需人工确认）"
        )
    if not payload.get("resource_id") and not payload.get("order_ids"):
        assumptions.append("事件未绑定资源或工单，按最近到期的未完成工单样本估算影响面")
    option_a = {
        "id": "A",
        "name": "协同重排",
        "tag": "推荐",
        "description": "M-01~M-05 联动重排受影响链，优先保留军品交期，吸收大部分延误",
        "delay_days": round(avg_delay * 0.28, 1),
        "affected_orders": affected_count,
        "moved_operations": moved_ops,
        "extra_changeovers": max(1, affected_count // 2),
        "cost_hours": round(moved_ops * 0.6, 1),
        "risk": "低",
        "score": max(42.0, round(88.0 - avg_delay * 0.28 * 6, 1)),
        "requires_approval": True,
    }
    option_b = {
        "id": "B",
        "name": "原地顺延",
        "tag": "保稳定",
        "description": "保持基线不动，受影响工单按原资源顺延，避免扰动扩散但交期风险高",
        "delay_days": round(avg_delay, 1),
        "affected_orders": affected_count,
        "moved_operations": 0,
        "extra_changeovers": 0,
        "cost_hours": 0,
        "risk": "高" if avg_delay > 1 else "中",
        "score": max(42.0, round(88.0 - avg_delay * 6, 1)),
        "requires_approval": True,
    }

    nodes = [
        {
            "id": "event",
            "label": change.title,
            "type": "event",
            "level": 0,
            "meta": {"severity": change.severity, "type": TYPE_LABEL.get(change.type, change.type)},
        }
    ]
    edges = []
    domain_added = set()
    for idx, item in enumerate(affected[:6]):
        node_id = f"order-{item['order_id']}"
        nodes.append(
            {
                "id": node_id,
                "label": item["order_no"],
                "type": "order",
                "level": 1,
                "meta": {"priority": item["priority"], "late_days": item["late_days"]},
            }
        )
        edges.append({"source": "event", "target": node_id, "kind": "trigger"})
        for domain in item["domains"][:3]:
            domain_id = f"domain-{domain}"
            if domain_id not in domain_added:
                domain_added.add(domain_id)
                nodes.append(
                    {
                        "id": domain_id,
                        "label": domain,
                        "type": "domain",
                        "level": 2,
                        "meta": {"orders": domain_set.get(domain, 0)},
                    }
                )
            edges.append({"source": node_id, "target": domain_id, "kind": "ripple"})

    impact = {
        "summary": {
            "affected_orders": affected_count,
            "affected_operations": total_ops,
            "critical_orders": critical,
            "avg_delay_days": round(avg_delay, 1),
            "max_late_days": round(max_late_days, 1),
            "projected_delay_hours": delay_hours,
            "domains": [{"name": k, "orders": v} for k, v in sorted(domain_set.items(), key=lambda x: -x[1])],
            "resource": resource.name if resource else payload.get("resource_name", "跨工序链路"),
            "sla_minutes": 15,
            "elapsed_minutes": round(elapsed_seconds / 60, 3),
            "confidence": confidence,
            "assumptions": assumptions,
            "delay_hours": delay_hours,
            "grounded_orders": grounded,
            "assessed_at": now.isoformat(),
            "engine": "内存依赖图涟漪推演（订单→工序→工序域）+ 时态延误实算 + A/B 方案估算",
        },
        "affected_orders": affected,
        "graph": {"nodes": nodes, "edges": edges},
        "timeline": [
            {"time": change.occurred_at.strftime("%H:%M"), "text": f"{TYPE_LABEL.get(change.type, change.type)}事件进入事件总线（R001）"},
            {"time": (change.occurred_at + timedelta(minutes=1)).strftime("%H:%M"), "text": "按事件绑定的资源/工单锁定受影响工序集合"},
            {"time": (change.occurred_at + timedelta(minutes=4)).strftime("%H:%M"), "text": "依赖图涟漪推演：以未完工序实算完成时间推算延误与波及工序域"},
            {"time": now.strftime("%H:%M"), "text": "给出协同重排 / 原地顺延 A/B 估算建议，实际方案需触发重排后由排产引擎实算评分"},
        ],
        "recommendation": "建议采用 A 方案协同重排，并在 15 分钟内完成终审电子签名，未审将自动升级生产指挥部。",
    }
    options = {"A": option_a, "B": option_b, "recommended": "A"}
    change.impact = impact
    change.options = options
    if change.status in ("评估中", "新建"):
        change.status = "评估完成"
    db.flush()
    return impact


def create_change_plans(db: Session, user: User, change: Disturbance, scenarios=("A", "B")) -> list:
    from .scheduler import create_plan_batch

    impact = change.impact or assess_disturbance(db, change)
    affected_ids = [item["order_id"] for item in impact.get("affected_orders", [])]
    orders = db.query(Order).filter(Order.id.in_(affected_ids)).all() if affected_ids else None
    if not orders:
        orders = None
    plans = create_plan_batch(
        db,
        user,
        plan_type="change",
        change_id=change.id,
        scenarios=tuple(scenarios),
        orders=orders,
    )
    change.status = "待审批"
    option_map = dict(change.options or {})
    option_map["plans"] = [
        {
            "plan_id": p.id,
            "code": p.code,
            "scenario": p.scenario,
            "objective": p.objective,
            "score": p.kpi.get("total_score", 0),
            "on_time_rate": p.kpi.get("on_time_rate", 0),
            "late_orders": p.kpi.get("late_orders", 0),
        }
        for p in plans
    ]
    change.options = option_map
    db.flush()
    return plans


def refresh_escalations(db: Session) -> int:
    from ..models import Alert, Approval

    now = datetime.now()
    pending = db.query(Approval).filter(Approval.status == "pending", Approval.deadline < now).all()
    escalated = 0
    for approval in pending:
        if not approval.escalated:
            approval.escalated = True
            approval.status = "escalated"
            escalated += 1
            db.add(
                Alert(
                    code=f"AL-ESC-{approval.id}-{uuid.uuid4().hex[:4].upper()}",
                    level="fatal",
                    type="approval",
                    title="审批超时自动升级",
                    message=f"方案审批已超时，按 R009 自动升级至生产指挥部（审批单 #{approval.id}）",
                    source="审批长事务",
                    related_type="approval",
                    related_id=str(approval.id),
                )
            )
    if escalated:
        db.flush()
    return escalated
