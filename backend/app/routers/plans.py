from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require
from ..models import Alert, Approval, Disturbance, Order, Plan, PlanItem, Resource, User
from ..schemas import ApproveRequest, FeedbackRequest
from ..security import signature_digest, verify_password
from ..services.audit import log_user_action
from ..services.metrics import latest_baseline
from ..services.rules import validate_schedule
from ..services.scheduler import apply_plan
from ..services.serializers import (
    agent_run_to_dict,
    change_to_dict,
    iso,
    item_to_dict,
    plan_to_dict,
    resource_to_dict,
)
from ..services.settings import get_setting

router = APIRouter(prefix="/api/plans", tags=["plans"])

STATUS_LABELS = {
    "draft": "草稿", "pending": "待审批", "approved": "已审批", "applied": "已签发",
    "rejected": "已驳回", "superseded": "已择优", "blocked": "硬约束阻断", "expired": "已过期",
}


def _plan_or_404(db: Session, plan_id: int) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail={"code": "PLAN_NOT_FOUND", "message": "排产方案不存在"})
    return plan


@router.get("")
def list_plans(
    status: str | None = None,
    type: str | None = None,
    include_history: bool = False,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:read")),
):
    query = db.query(Plan)
    if not include_history:
        query = query.filter(~Plan.code.like("HIST%"))
    if status:
        query = query.filter(Plan.status == status)
    if type:
        query = query.filter(Plan.type == type)
    total = query.count()
    plans = query.order_by(Plan.created_at.desc(), Plan.id.desc()).offset(offset).limit(limit).all()
    counts = {}
    for key in STATUS_LABELS:
        counts[key] = db.query(Plan).filter(Plan.status == key, ~Plan.code.like("HIST%")).count()
    return {
        "items": [plan_to_dict(p, db) for p in plans],
        "total": total,
        "limit": limit,
        "offset": offset,
        "counts": counts,
    }


@router.get("/batches/pending")
def pending_batches(db: Session = Depends(get_db), user: User = Depends(require("plans:read"))):
    plans = db.query(Plan).filter(Plan.status == "pending").order_by(Plan.created_at.desc()).all()
    batches: dict[str, list[Plan]] = {}
    for plan in plans:
        batches.setdefault(plan.batch_id or f"single-{plan.id}", []).append(plan)
    result = []
    for batch_id, group in batches.items():
        group.sort(key=lambda p: p.scenario)
        result.append(
            {
                "batch_id": batch_id,
                "change_id": group[0].change_id,
                "type": group[0].type,
                "created_at": iso(group[0].created_at),
                "plans": [plan_to_dict(p, db) for p in group],
                "recommended": next((p.scenario for p in group if p.scenario == "A"), group[0].scenario),
            }
        )
    return {"items": result, "total": len(result)}


@router.get("/baseline")
def baseline(db: Session = Depends(get_db), user: User = Depends(require("plans:read"))):
    plan = latest_baseline(db)
    if not plan:
        raise HTTPException(status_code=404, detail={"code": "NO_BASELINE", "message": "尚无生效基线"})
    return plan_to_dict(plan, db)


@router.get("/{plan_id}")
def get_plan(
    plan_id: int,
    include_items: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:read")),
):
    plan = _plan_or_404(db, plan_id)
    data = plan_to_dict(plan, db)
    data["items_count"] = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).count()
    if include_items:
        items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).order_by(PlanItem.start).limit(4000).all()
        data["items"] = [item_to_dict(i) for i in items]
    if plan.change_id:
        change = db.get(Disturbance, plan.change_id)
        data["change"] = change_to_dict(change) if change else None
    siblings = []
    if plan.batch_id:
        siblings = db.query(Plan).filter(Plan.batch_id == plan.batch_id, Plan.id != plan.id).all()
    data["siblings"] = [
        {"id": s.id, "code": s.code, "scenario": s.scenario, "objective": s.objective, "status": s.status,
         "score": (s.kpi or {}).get("total_score"), "on_time_rate": (s.kpi or {}).get("on_time_rate")}
        for s in sorted(siblings, key=lambda x: x.scenario)
    ]
    return data


@router.get("/{plan_id}/gantt")
def plan_gantt(
    plan_id: int,
    domain: str = "机加",
    search: str = "",
    priority: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:read")),
):
    plan = _plan_or_404(db, plan_id)
    query = db.query(PlanItem).filter(PlanItem.plan_id == plan.id, PlanItem.domain == domain)
    if priority:
        query = query.filter(PlanItem.priority == priority)
    if search:
        like = f"%{search}%"
        query = query.filter((PlanItem.order_no.like(like)) | (PlanItem.product_name.like(like)) | (PlanItem.name.like(like)))
    items = query.order_by(PlanItem.start).limit(1200).all()
    current_baseline = latest_baseline(db)
    baseline_items = []
    if current_baseline and current_baseline.id != plan.id:
        baseline_items = (
            db.query(PlanItem)
            .filter(
                PlanItem.plan_id == current_baseline.id,
                PlanItem.domain == domain,
                PlanItem.operation_id.in_([i.operation_id for i in items if i.operation_id]) if items else False,
            )
            .all()
        )
    resources = db.query(Resource).filter(Resource.domain == domain).order_by(Resource.bottleneck.desc(), Resource.code).all()
    freeze_days = int(get_setting(db, "freeze_days", 3))
    now = datetime.now().replace(second=0, microsecond=0)
    late = sum(1 for i in items if i.risk == "late")
    tight = sum(1 for i in items if i.risk == "tight")
    return {
        "plan": plan_to_dict(plan, db, include_approval=True),
        "domain": domain,
        "items": [item_to_dict(i) for i in items],
        "baseline_items": [item_to_dict(i) for i in baseline_items],
        "resources": [resource_to_dict(r) for r in resources],
        "freeze_until": (now + timedelta(days=freeze_days)).isoformat(),
        "now": now.isoformat(),
        "stats": {
            "operations": len(items),
            "orders": len({i.order_id for i in items}),
            "late": late,
            "tight": tight,
            "locked": sum(1 for i in items if i.locked),
            "resources": len(resources),
            "bottleneck": sum(1 for r in resources if r.bottleneck),
        },
        "domains": ["锻造", "机加", "热表", "钣焊", "装配", "试车", "大修"],
    }


@router.get("/{plan_id}/items")
def plan_items(
    plan_id: int,
    domain: str | None = None,
    search: str = "",
    risk: str | None = None,
    limit: int = Query(500, ge=1, le=3000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:read")),
):
    _plan_or_404(db, plan_id)
    query = db.query(PlanItem).filter(PlanItem.plan_id == plan_id)
    if domain:
        query = query.filter(PlanItem.domain == domain)
    if risk:
        query = query.filter(PlanItem.risk == risk)
    if search:
        like = f"%{search}%"
        query = query.filter((PlanItem.order_no.like(like)) | (PlanItem.product_name.like(like)))
    total = query.count()
    rows = query.order_by(PlanItem.start).offset(offset).limit(limit).all()
    return {"items": [item_to_dict(r) for r in rows], "total": total}


@router.post("/{plan_id}/approve")
def approve_plan(
    plan_id: int,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:approve")),
):
    if payload.plan_id != plan_id:
        raise HTTPException(status_code=400, detail={"code": "PLAN_MISMATCH", "message": "方案 ID 不一致"})
    if not verify_password(payload.password, user.password_hash):
        log_user_action(db, user, "plan.signature.failed", "plan", str(plan_id), result="denied", detail={"reason": "bad signature password"})
        db.commit()
        raise HTTPException(status_code=403, detail={"code": "SIGNATURE_FAILED", "message": "电子签名校验失败：密码错误"})
    plan = _plan_or_404(db, plan_id)
    if plan.status != "pending":
        raise HTTPException(status_code=409, detail={"code": "PLAN_STATE_INVALID", "message": f"方案当前状态为 {STATUS_LABELS.get(plan.status, plan.status)}，不可审批"})
    approval = db.query(Approval).filter(Approval.plan_id == plan.id).order_by(Approval.id.desc()).first()
    if not approval or approval.status in ("cancelled",):
        raise HTTPException(status_code=409, detail={"code": "APPROVAL_INVALID", "message": "审批单已失效"})
    now = datetime.now().replace(microsecond=0)
    if payload.action == "reject":
        approval.status = "rejected"
        approval.approver_id = user.id
        approval.approver_name = user.name
        approval.role = user.role
        approval.comment = payload.comment
        approval.decided_at = now
        plan.status = "rejected"
        if plan.change_id:
            change = db.get(Disturbance, plan.change_id)
            if change:
                change.status = "已挂起"
        log_user_action(
            db, user, "plan.reject", "plan", plan.code,
            detail={"comment": payload.comment, "batch": plan.batch_id, "scenario": plan.scenario},
        )
        db.commit()
        return {"ok": True, "action": "reject", "plan": plan_to_dict(plan, db), "message": "方案已驳回，进入重排回路"}

    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    verification = validate_schedule(db, items)
    if not verification["passed"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "HARD_CONSTRAINT_VIOLATION", "message": f"硬约束违规 {verification['hard_count']} 项，写保护网关拒绝签发", "violations": verification},
        )
    signature = signature_digest(plan.code, user.username, now.isoformat())
    approval.status = "approved"
    approval.approver_id = user.id
    approval.approver_name = user.name
    approval.role = user.role
    approval.comment = payload.comment or "同意签发，按方案执行"
    approval.signature = signature
    approval.decided_at = now
    plan.status = "approved"
    plan.approved_at = now
    db.flush()
    result = apply_plan(db, plan, user, approval.comment)
    db.add(
        Alert(
            code=f"AL-PS-{uuid.uuid4().hex[:8].upper()}",
            level="info",
            type="plan",
            title="新排产基线已签发",
            message=f"{user.name} 完成 {plan.code} 终审签名，基线已通过写保护网关写入 APS。",
            source="写保护网关",
            related_type="plan",
            related_id=str(plan.id),
        )
    )
    log_user_action(
        db, user, "plan.approve", "plan", plan.code,
        detail={
            "signature_digest": signature,
            "batch": plan.batch_id,
            "scenario": plan.scenario,
            "comment": approval.comment,
            "operations_updated": result["operations_updated"],
        },
    )
    db.commit()
    db.refresh(plan)
    return {"ok": True, "action": "approve", "plan": plan_to_dict(plan, db), "apply": result}


@router.post("/{plan_id}/write-attempt")
def write_attempt(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = _plan_or_404(db, plan_id)
    log_user_action(
        db, user, "write.blocked", "plan", plan.code, result="blocked",
        detail={"reason": "未审批写入 APS/MES 被写保护网关拦截", "plan_status": plan.status},
    )
    db.commit()
    raise HTTPException(
        status_code=403,
        detail={
            "code": "WRITE_SHIELD_BLOCKED",
            "message": "写保护网关已拦截：LLM/求解器禁止直写 APS/MES，必须经审批与电子签名",
            "audit": "blocked event logged",
        },
    )


@router.get("/{plan_id}/lineage")
def plan_lineage(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:read")),
):
    plan = _plan_or_404(db, plan_id)
    baseline = latest_baseline(db)
    summary = plan.summary or {}
    hard_checks = summary.get("hard_checks", [])
    soft = summary.get("soft_violations", [])
    nodes = [
        {"id": "plan", "label": plan.code, "type": "plan", "meta": {"objective": plan.objective, "status": plan.status}},
        {"id": "data", "label": "专识 68,884 条 / 通识 54,400 条", "type": "dataset", "meta": {"trace_version": "v1.0"}},
        {"id": "rules", "label": "68 条排产规则", "type": "rule", "meta": {"version": "ZD-01-2026"}},
        {"id": "constraints", "label": "HC-01~14 / SC-01~13", "type": "constraint", "meta": {"hard": 14, "soft": 13}},
        {"id": "solver", "label": "LISA Heuristic Engine", "type": "solver", "meta": {"scenario": plan.scenario, "weights": plan.weights}},
        {"id": "approval", "label": "生产指挥部终审", "type": "approval", "meta": {"signature": (plan_to_dict(plan, db).get("approval") or {}).get("signature", "待签发")}},
    ]
    if baseline:
        nodes.append({"id": "baseline", "label": f"基线 {baseline.code}", "type": "baseline", "meta": {"applied_at": iso(baseline.applied_at)}})
    if plan.change_id:
        change = db.get(Disturbance, plan.change_id)
        if change:
            nodes.append({"id": "change", "label": change.code, "type": "disturbance", "meta": {"title": change.title}})
    edges = [
        {"source": "data", "target": "plan", "label": "wasDerivedFrom"},
        {"source": "rules", "target": "plan", "label": "wasGeneratedBy"},
        {"source": "constraints", "target": "plan", "label": "wasValidatedBy"},
        {"source": "solver", "target": "plan", "label": "wasGeneratedBy"},
        {"source": "plan", "target": "approval", "label": "wasApprovedBy"},
    ]
    if baseline:
        edges.append({"source": "baseline", "target": "plan", "label": "wasRevisionOf"})
    if plan.change_id:
        edges.append({"source": "change", "target": "plan", "label": "wasInfluencedBy"})
    return {
        "nodes": nodes,
        "edges": edges,
        "prov": {
            "bundle": f"PROV-O/{plan.code}",
            "hard_checks": len(hard_checks),
            "hard_failed": sum(1 for c in hard_checks if not c.get("passed")),
            "soft_violations": len(soft),
            "trace_version": "v1.0",
        },
    }


@router.post("/{plan_id}/feedback")
def submit_feedback(
    plan_id: int,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("plans:read")),
):
    plan = _plan_or_404(db, plan_id)
    log_user_action(
        db, user, "plan.feedback", "plan", plan.code,
        detail={"accepted": payload.accepted, "note": payload.note, "human_ai_divergence": not payload.accepted},
    )
    db.commit()
    return {"ok": True, "message": "人机分歧已采集，将回流影子数据集（R010）"}
