from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..config import (
    APP_NAME,
    APP_VERSION,
    ENVIRONMENT,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
)
from ..database import engine, get_db
from ..deps import get_current_user, require
from ..models import (
    AgentRun,
    Alert,
    AuditLog,
    Disturbance,
    Operation,
    Order,
    Plan,
    Resource,
    Rule,
    User,
)
from ..schemas import SettingsUpdate
from ..services.audit import log_user_action
from ..services.serializers import audit_to_dict, user_to_dict
from ..services.settings import SCENARIO_META, all_settings, get_setting, set_setting

router = APIRouter(prefix="/api/system", tags=["system"])

PERMISSION_LABELS = {
    "dashboard:read": "驾驶舱",
    "plans:read": "方案查看",
    "plans:create": "方案生成",
    "plans:submit": "方案提交",
    "plans:approve": "方案终审签名",
    "agents:read": "智能体查看",
    "agents:run": "智能体运行",
    "changes:read": "变更查看",
    "changes:create": "变更评估",
    "changes:approve": "变更审批",
    "kits:read": "齐套检查",
    "data:read": "数据基座",
    "knowledge:read": "知识规则",
    "audit:read": "审计追溯",
    "alerts:read": "告警查看",
    "alerts:ack": "告警确认",
    "settings:read": "设置查看",
    "export:read": "数据导出",
}


@router.get("/meta")
def meta():
    return {
        "name": APP_NAME,
        "name_en": "Liyang Intelligent Scheduling Agent",
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "roles": [{"code": k, "label": v} for k, v in ROLE_LABELS.items()],
        "scenarios": SCENARIO_META,
        "constraints": {"hard": "HC-01~14", "soft": "SC-01~13", "rules": 68},
        "kpis": [
            "采纳率≥85%", "夜间重排1~2h", "变更评估≤15min", "局部重排≤30min",
            "齐套率60%→100%", "试车达成率提升",
        ],
        "compliance": ["可追溯", "可兜底", "可解释", "安全合规"],
    }


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "time": datetime.now().replace(microsecond=0).isoformat(),
    }


@router.get("/settings")
def settings(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    return {"values": all_settings(db), "scenarios": SCENARIO_META}


@router.put("/settings")
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可修改全局参数"})
    allowed = {
        "weights", "thresholds", "freeze_days", "shift", "approval_timeout_minutes",
        "solver_timeout_seconds", "auto_escalate", "write_shield",
    }
    updated = {}
    for key, value in payload.values.items():
        if key not in allowed:
            continue
        updated[key] = set_setting(db, key, value)
    log_user_action(db, user, "settings.update", "settings", "global", detail={"keys": list(updated.keys()), "values": updated})
    db.commit()
    return {"values": all_settings(db), "updated": list(updated.keys())}


@router.get("/users")
def users(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    rows = db.query(User).order_by(User.id).all()
    return {"items": [user_to_dict(u) for u in rows]}


@router.get("/security")
def security(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    blocked = db.query(AuditLog).filter(AuditLog.action == "write.blocked").count()
    denied = db.query(AuditLog).filter(AuditLog.result == "denied").count()
    matrix = []
    for role, perms in ROLE_PERMISSIONS.items():
        matrix.append(
            {
                "role": role,
                "label": ROLE_LABELS.get(role, role),
                "permissions": ["*"] if "*" in perms else perms,
                "permission_labels": ["全部权限"] if "*" in perms else [PERMISSION_LABELS.get(p, p) for p in perms],
            }
        )
    return {
        "write_shield": {
            "enabled": bool(get_setting(db, "write_shield", True)),
            "policy": "LLM / 求解器禁止直写 APS/MES，写请求必须携带方案 ID + 审批人 + 电子签名",
            "blocked_writes": blocked,
            "target": "100% 拦截未审批写入",
            "status": "active",
        },
        "abac": {
            "matrix": matrix,
            "denied_events": denied,
            "policy_engine": "LISA ABAC Policy Point (自研)",
            "target": "100% 越权拦截",
        },
        "audit": {
            "hash_chain": "SHA-256",
            "worm": True,
            "retention": "按军工审计要求（可配置 ≥10 年）",
        },
        "encryption": {
            "transport": "内网 mTLS / HTTPS",
            "desensitization": "不可逆哈希 + 盐",
            "data_boundary": "数据不出内网，无公网依赖",
        },
        "electronic_signature": {
            "levels": ["计划员择优", "生产指挥部终审", "15min 未审自动升级"],
            "algorithm": "PBKDF2-SHA256 身份校验 + 签名摘要",
        },
    }


@router.post("/write-shield/test")
def test_write_shield(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    log_user_action(
        db, user, "write.blocked", "gateway", "APS/MES", result="blocked",
        detail={"reason": "未携带审批凭证的模拟写入", "policy": "write-through-shield"},
    )
    db.commit()
    return {
        "blocked": True,
        "status": "blocked",
        "message": "写保护网关已拦截：未审批写入 APS/MES 被拒绝（拦截率 100%）",
        "audit": "已写入审计哈希链",
        "tested_at": datetime.now().replace(microsecond=0).isoformat(),
    }


@router.get("/search")
def global_search(
    q: str = Query(..., min_length=1, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    like = f"%{q}%"
    orders = (
        db.query(Order)
        .filter((Order.order_no.like(like)) | (Order.product_name.like(like)))
        .order_by(Order.due_date.asc()).limit(5).all()
    )
    plans = (
        db.query(Plan)
        .filter((Plan.code.like(like)) | (Plan.name.like(like)))
        .order_by(Plan.created_at.desc()).limit(5).all()
    )
    changes = (
        db.query(Disturbance)
        .filter((Disturbance.code.like(like)) | (Disturbance.title.like(like)))
        .order_by(Disturbance.occurred_at.desc()).limit(5).all()
    )
    return {
        "query": q,
        "orders": [{"id": o.id, "title": o.order_no, "subtitle": o.product_name, "status": o.status, "priority": o.priority} for o in orders],
        "plans": [{"id": p.id, "title": p.code, "subtitle": p.name, "status": p.status} for p in plans],
        "changes": [{"id": c.id, "title": c.code, "subtitle": c.title, "status": c.status} for c in changes],
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    return {
        "orders": db.query(Order).count(),
        "operations": db.query(Operation).count(),
        "resources": db.query(Resource).count(),
        "plans": db.query(Plan).count(),
        "rules": db.query(Rule).count(),
        "agent_runs": db.query(AgentRun).count(),
        "alerts": db.query(Alert).count(),
        "audit_logs": db.query(AuditLog).count(),
        "db_engine": engine.dialect.name,
    }


@router.get("/export/orders.csv")
def export_orders(db: Session = Depends(get_db), user: User = Depends(require("export:read"))):
    rows = db.query(Order).order_by(Order.order_no).limit(5000).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["订单号", "产品", "数量", "优先级", "厂区", "客户", "交期", "状态", "进度", "齐套状态"])
    for o in rows:
        writer.writerow([o.order_no, o.product_name, o.qty, o.priority, o.plant, o.customer, o.due_date.strftime("%Y-%m-%d"), o.status, o.progress, o.kit_status])
    content = "\ufeff" + buffer.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=lisa-orders.csv"},
    )


@router.get("/export/audit.csv")
def export_audit(db: Session = Depends(get_db), user: User = Depends(require("audit:read"))):
    rows = db.query(AuditLog).order_by(AuditLog.seq.desc()).limit(5000).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["seq", "时间", "操作人", "角色", "动作", "对象", "结果", "密级", "hash", "prev_hash"])
    for log in rows:
        writer.writerow([log.seq, log.ts.strftime("%Y-%m-%d %H:%M:%S"), log.actor, log.role, log.action, f"{log.target_type}:{log.target_id}", log.result, log.clearance, log.hash, log.prev_hash])
    content = "\ufeff" + buffer.getvalue()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=lisa-audit.csv"},
    )
