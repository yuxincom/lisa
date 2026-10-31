from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..config import ROLE_LABELS
from ..models import (
    AgentRun,
    Alert,
    Approval,
    AuditLog,
    Disturbance,
    KitCheck,
    Order,
    Plan,
    PlanItem,
    Resource,
    Rule,
    User,
)

PLAN_STATUS = {
    "draft": "草稿",
    "pending": "待审批",
    "approved": "已审批",
    "applied": "已签发",
    "rejected": "已驳回",
    "superseded": "已择优",
    "blocked": "硬约束阻断",
    "expired": "已过期",
}

RISK_LABEL = {"normal": "正常", "tight": "紧张", "late": "逾期", "blocked": "阻断"}
LEVEL_LABEL = {"fatal": "致命", "critical": "严重", "warning": "警告", "info": "提示"}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role),
        "clearance": user.clearance,
        "department": user.department,
        "avatar_color": user.avatar_color,
    }


def plan_to_dict(plan: Plan, db: Session, include_approval: bool = True) -> dict:
    approval = None
    minutes_left = None
    escalated = False
    if include_approval:
        approval = (
            db.query(Approval)
            .filter(Approval.plan_id == plan.id)
            .order_by(Approval.id.desc())
            .first()
        )
        if approval and approval.deadline and approval.status == "pending":
            minutes_left = max(0, round((approval.deadline - datetime.now()).total_seconds() / 60, 1))
            escalated = approval.escalated or minutes_left <= 0
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "type": plan.type,
        "status": plan.status,
        "status_label": PLAN_STATUS.get(plan.status, plan.status),
        "scenario": plan.scenario,
        "objective": plan.objective,
        "weights": plan.weights or {},
        "summary": plan.summary or {},
        "kpi": plan.kpi or {},
        "diff": plan.diff or {},
        "created_by": plan.created_by,
        "created_at": iso(plan.created_at),
        "submitted_at": iso(plan.submitted_at),
        "approved_at": iso(plan.approved_at),
        "applied_at": iso(plan.applied_at),
        "baseline": plan.baseline,
        "batch_id": plan.batch_id,
        "change_id": plan.change_id,
        "approval": {
            "id": approval.id,
            "status": approval.status,
            "approver_name": approval.approver_name,
            "deadline": iso(approval.deadline),
            "minutes_left": minutes_left,
            "escalated": escalated,
            "comment": approval.comment,
            "signature": approval.signature,
            "decided_at": iso(approval.decided_at),
        } if approval else None,
    }


def item_to_dict(item: PlanItem) -> dict:
    return {
        "id": item.id,
        "order_id": item.order_id,
        "operation_id": item.operation_id,
        "order_no": item.order_no,
        "product_name": item.product_name,
        "priority": item.priority,
        "seq": item.seq,
        "name": item.name,
        "domain": item.domain,
        "resource_id": item.resource_id,
        "resource_code": item.resource_code,
        "resource_name": item.resource_name,
        "start": iso(item.start),
        "end": iso(item.end),
        "duration_minutes": item.duration_minutes,
        "setup_minutes": item.setup_minutes,
        "risk": item.risk,
        "risk_label": RISK_LABEL.get(item.risk, item.risk),
        "locked": item.locked,
        "reason": item.reason,
    }


def order_to_dict(order: Order, extra: dict | None = None) -> dict:
    data = {
        "id": order.id,
        "order_no": order.order_no,
        "product_id": order.product_id,
        "product_name": order.product_name,
        "qty": order.qty,
        "priority": order.priority,
        "plant": order.plant,
        "customer": order.customer,
        "due_date": iso(order.due_date),
        "status": order.status,
        "progress": order.progress,
        "is_military": order.is_military,
        "kit_status": order.kit_status,
        "created_at": iso(order.created_at),
        "released_at": iso(order.released_at),
    }
    if extra:
        data.update(extra)
    return data


def resource_to_dict(resource: Resource, extra: dict | None = None) -> dict:
    data = {
        "id": resource.id,
        "code": resource.code,
        "name": resource.name,
        "domain": resource.domain,
        "plant": resource.plant,
        "capacity_hours": resource.capacity_hours,
        "efficiency": resource.efficiency,
        "bottleneck": resource.bottleneck,
        "status": resource.status,
        "maintenance_until": iso(resource.maintenance_until),
    }
    if extra:
        data.update(extra)
    return data


def alert_to_dict(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "code": alert.code,
        "level": alert.level,
        "level_label": LEVEL_LABEL.get(alert.level, alert.level),
        "type": alert.type,
        "title": alert.title,
        "message": alert.message,
        "source": alert.source,
        "related_type": alert.related_type,
        "related_id": alert.related_id,
        "status": alert.status,
        "created_at": iso(alert.created_at),
        "acked_by": alert.acked_by,
        "acked_at": iso(alert.acked_at),
    }


def change_to_dict(change: Disturbance) -> dict:
    return {
        "id": change.id,
        "code": change.code,
        "type": change.type,
        "title": change.title,
        "detail": change.detail,
        "severity": change.severity,
        "status": change.status,
        "occurred_at": iso(change.occurred_at),
        "payload": change.payload or {},
        "impact": change.impact or {},
        "options": change.options or {},
        "resolved_at": iso(change.resolved_at),
        "reporter": change.reporter,
    }


def kit_to_dict(check: KitCheck) -> dict:
    return {
        "id": check.id,
        "order_id": check.order_id,
        "order_no": check.order_no,
        "product_name": check.product_name,
        "checkpoint": check.checkpoint,
        "status": check.status,
        "score": check.score,
        "elements": check.elements or [],
        "gaps": check.gaps or [],
        "checked_at": iso(check.checked_at),
    }


def agent_run_to_dict(run: AgentRun, include_steps: bool = False) -> dict:
    data = {
        "id": run.id,
        "code": run.code,
        "agent_code": run.agent_code,
        "agent_name": run.agent_name,
        "level": run.level,
        "scenario": run.scenario,
        "status": run.status,
        "summary": run.summary,
        "operator": run.operator,
        "started_at": iso(run.started_at),
        "ended_at": iso(run.ended_at),
        "duration_ms": run.duration_ms,
        "plan_id": run.plan_id,
        "output": run.output or {},
    }
    if include_steps:
        data["inputs"] = run.inputs or {}
        data["steps"] = run.steps or []
    return data


def audit_to_dict(log: AuditLog, include_detail: bool = True) -> dict:
    data = {
        "id": log.id,
        "seq": log.seq,
        "ts": iso(log.ts),
        "actor": log.actor,
        "role": log.role,
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "result": log.result,
        "prev_hash": log.prev_hash,
        "hash": log.hash,
        "clearance": log.clearance,
    }
    if include_detail:
        data["detail"] = log.detail or {}
    return data


def rule_to_dict(rule: Rule) -> dict:
    return {
        "id": rule.id,
        "code": rule.code,
        "kind": rule.kind,
        "category": rule.category,
        "title": rule.title,
        "description": rule.description,
        "priority": rule.priority,
        "trigger": rule.trigger,
        "action": rule.action,
        "weight": rule.weight,
        "domain": rule.domain,
        "enabled": rule.enabled,
        "hits": rule.hits,
    }
