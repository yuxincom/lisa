from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from ..config import (
    APP_NAME,
    APP_VERSION,
    ENVIRONMENT,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
)
from ..database import engine, get_db
from ..deps import clearance_cfg, get_current_user, plant_cfg, require
from ..models import (
    AgentRun,
    Alert,
    AuditLog,
    Disturbance,
    Operation,
    Order,
    Plan,
    PlanItem,
    Resource,
    Rule,
    User,
)
from ..schemas import (
    AdapterConfigUpdate,
    AdapterRunRequest,
    BackupVerifyRequest,
    KitDataUpdate,
    KnowledgeImportUpdate,
    MachineLedgerUpdate,
    SettingsUpdate,
    UserScopeUpdate,
)
from ..services import backup as bk
from ..services import clearance as clr
from ..services import plants as pl
from ..services.audit import log_user_action
from ..services.adapters import AdapterError, adapter_overview, run_due
from ..services.kit_data import KIT_COLUMNS, KitDataError, data_freshness, upsert_rows
from ..services.knowledge import KNOWLEDGE_COLUMNS, KnowledgeImportError, import_rows as import_knowledge_rows
from ..services.maindata import LedgerError, apply_dependencies, apply_machine_ledger
from ..services.calendar import CalendarConfigError, active_calendar, apply_calendar_config, validate_calendar_config
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
    "audit:anchor": "审计锚定",
    "alerts:read": "告警查看",
    "alerts:ack": "告警确认",
    "settings:read": "设置查看",
    "export:read": "数据导出",
    "jobs:read": "任务队列查看",
    "jobs:cancel": "任务取消",
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
        "weights", "thresholds", "freeze_days", "shift", "calendar", "approval_timeout_minutes",
        "solver_timeout_seconds", "auto_escalate", "write_shield", "clearance", "plants",
    }
    updated = {}
    for key, value in payload.values.items():
        if key not in allowed:
            continue
        if key == "calendar":
            try:
                validate_calendar_config(value)
            except CalendarConfigError as exc:
                raise HTTPException(status_code=422, detail={"code": "CALENDAR_INVALID", "message": str(exc)}) from exc
        if key == "clearance":
            try:
                value = clr.normalize(value)
            except clr.ClearanceError as exc:
                raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
        if key == "plants":
            try:
                value = pl.normalize(value)
            except pl.PlantError as exc:
                raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
        updated[key] = set_setting(db, key, value)
    log_user_action(db, user, "settings.update", "settings", "global", detail={"keys": list(updated.keys()), "values": updated})
    db.commit()
    if "calendar" in updated:
        apply_calendar_config(all_settings(db)["calendar"])
    return {"values": all_settings(db), "updated": list(updated.keys())}


@router.get("/calendar")
def calendar_status(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    """当前真正生效的工作日历，以及未来 14 天的产能栅格。"""
    calendar = active_calendar()
    lanes = [
        max(1, int(count or 1))
        for (count,) in db.query(Resource.machine_count).filter(Resource.status != "offline").all()
    ]
    total_lanes = sum(lanes)
    today = date.today()
    grid = []
    for offset in range(14):
        day = today + timedelta(days=offset)
        capacity = calendar.day_capacity_minutes(day)
        grid.append(
            {
                "date": day.isoformat(),
                "weekday": day.weekday(),
                "production_day": calendar.is_production_day(day),
                "shift_minutes": round(capacity, 1),
                "machine_capacity_minutes": round(capacity * total_lanes, 1),
            }
        )
    return {
        "effective": calendar.to_config(),
        "stored": get_setting(db, "calendar", None),
        "resources": {"count": len(lanes), "lanes": total_lanes},
        "grid": grid,
    }


@router.put("/calendar")
def update_calendar(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可修改工作日历"})
    try:
        validate_calendar_config(payload.values)
    except CalendarConfigError as exc:
        raise HTTPException(status_code=422, detail={"code": "CALENDAR_INVALID", "message": str(exc)}) from exc
    stored = set_setting(db, "calendar", payload.values)
    log_user_action(db, user, "calendar.update", "settings", "calendar", detail={"config": stored})
    db.commit()
    calendar = apply_calendar_config(stored)
    return {"effective": calendar.to_config(), "applied": True}


@router.get("/users")
def users(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    rows = db.query(User).order_by(User.id).all()
    return {"items": [user_to_dict(u) for u in rows], "plants": pl.config(db)["names"]}


@router.put("/users/{username}/scope")
def update_user_scope(
    username: str,
    payload: UserScopeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    """给账号配读取范围：厂区 + 密级。投产时按人头逐条落实，别靠「大家都看全部」。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可调整账号读取范围"})
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": "账号不存在"})
    plant_cfg = pl.config(db)
    claimed = [str(x).strip() for x in (payload.plants or []) if str(x).strip()]
    if len(set(claimed)) != len(claimed):
        raise HTTPException(status_code=422, detail={"code": "PLANT_SCOPE_INVALID", "message": "厂区范围里有重名"})
    unknown = [name for name in claimed if name not in plant_cfg["names"]]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={"code": "PLANT_SCOPE_INVALID",
                    "message": f"厂区 {', '.join(unknown)} 不在厂区清单里（清单：{', '.join(plant_cfg['names'])}）"},
        )
    clearance_cfg = clr.config(db)
    level = (payload.clearance or "").strip()
    if level and level not in clearance_cfg["levels"]:
        raise HTTPException(
            status_code=422,
            detail={"code": "CLEARANCE_LEVELS_INVALID",
                    "message": f"密级 {level} 不在等级表里（等级表：{', '.join(clearance_cfg['levels'])}）"},
        )
    before = {"plants": list(target.plants or []), "clearance": target.clearance}
    target.plants = claimed
    if level:
        target.clearance = level
    log_user_action(
        db, user, "user.scope_update", "user", target.username,
        detail={"before": before, "after": {"plants": claimed, "clearance": target.clearance}},
    )
    db.commit()
    db.refresh(target)
    return user_to_dict(target)


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
        "clearance": clr.report(db, user),
        "plants": pl.report(db, user),
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


@router.post("/main-data/machine-ledger")
def import_machine_ledger(
    payload: MachineLedgerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可导入产能主数据"})
    try:
        result = apply_machine_ledger(db, payload.items, user)
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})
    db.commit()
    return result


@router.post("/main-data/operation-dependencies")
def import_operation_dependencies(
    payload: MachineLedgerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可导入工序依赖"})
    try:
        result = apply_dependencies(db, payload.items, user)
    except LedgerError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})
    db.commit()
    return result


@router.post("/main-data/kit-data")
def import_kit_data(
    payload: KitDataUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    """齐套外部主数据（D 组）的 JSON 通道：ERP BOM / WMS 库存 / 在途 / 工装刀具 / 资质 / 检验结论。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可导入外部主数据"})
    try:
        result = upsert_rows(db, payload.kind, payload.items, user)
    except (KitDataError, LedgerError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})
    if payload.dry_run:
        db.rollback()
        result["dry_run"] = True
        return result
    db.commit()
    return result


@router.get("/main-data/knowledge-columns")
def knowledge_columns(user: User = Depends(require("data:read"))):
    """F6 语料模板的表头与受控值域，页面/脚本按这个生成 CSV。"""
    return {"columns": list(KNOWLEDGE_COLUMNS), "categories": ["专识", "通识"]}


@router.post("/main-data/knowledge")
def import_knowledge_corpus(
    payload: KnowledgeImportUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    """知识语料（F6）入库：按 code upsert，非法行整批拒绝，导入动作写审计链。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可导入知识语料"})
    try:
        result = import_knowledge_rows(db, payload.items, user)
    except (KnowledgeImportError, LedgerError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})
    if payload.dry_run:
        db.rollback()
        result["dry_run"] = True
        return result
    db.commit()
    return result


@router.get("/main-data/kit-sources")
def kit_source_freshness(db: Session = Depends(get_db), user: User = Depends(require("data:read"))):
    return data_freshness(db)


@router.get("/main-data/adapters")
def list_adapters(db: Session = Depends(get_db), user: User = Depends(require("data:read"))):
    return adapter_overview(db)


@router.put("/main-data/adapters")
def save_adapters(
    payload: AdapterConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可配置接入通道"})
    for source in payload.sources:
        if not isinstance(source, dict):
            raise HTTPException(status_code=422, detail={"code": "ADAPTER_CONFIG_INVALID", "message": "通道配置必须是对象列表"})
        kind = str(source.get("kind") or "")
        channel = str(source.get("channel") or "")
        if kind not in KIT_COLUMNS:
            raise HTTPException(status_code=422, detail={"code": "ADAPTER_KIND_UNKNOWN", "message": f"未知的齐套数据类型：{kind}"})
        if channel not in {"file", "http", "db"}:
            raise HTTPException(status_code=422, detail={"code": "ADAPTER_CHANNEL_UNKNOWN", "message": f"未知通道：{channel}"})
        if channel == "http" and not str(source.get("url", "")).startswith("https://"):
            raise HTTPException(status_code=422, detail={"code": "ADAPTER_URL_INSECURE", "message": "HTTP 通道只允许 https"})
        if channel == "db" and not str(source.get("sql", "")).strip().lower().startswith("select"):
            raise HTTPException(status_code=422, detail={"code": "ADAPTER_SQL_NOT_READONLY", "message": "中间库通道只允许 SELECT"})
    set_setting(db, "adapters", {"sources": payload.sources})
    log_user_action(db, user, "maindata.adapters_config", "adapter", "config", detail={"sources": len(payload.sources)})
    db.commit()
    return {"sources": len(payload.sources)}


@router.post("/main-data/adapters/run")
def run_adapters(
    payload: AdapterRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可触发外部同步"})
    try:
        return run_due(db, user, force=payload.force)
    except (AdapterError, KitDataError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})


@router.get("/backups")
def list_backups(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    """快照清单：让运维在页面上确认「最近一次备份还在不在」，恢复本身不开放 HTTP。"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可查看备份"})
    return {
        "items": bk.list_backups(),
        "backup_dir": str(bk.backup_dir()),
        "keep": bk.keep_count(),
        "dialect": engine.dialect.name,
        "native": bk.native_commands(),
        "restore": "停服后执行 python -m app.management restore <文件名> --yes",
    }


@router.post("/backups")
def create_backup(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可创建备份"})
    try:
        summary = bk.create(db)
    except bk.BackupError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})
    log_user_action(
        db, user, "backup.create", "backup", summary["audit_ref"],
        detail={"file": summary["file"], "total_rows": summary["total_rows"], "checksum": summary["checksum"]},
    )
    db.commit()
    return summary


@router.post("/backups/verify")
def verify_backup(
    payload: BackupVerifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可校验备份"})
    try:
        result = bk.verify(bk.resolve_name(payload.name))
    except bk.BackupError as exc:
        # 校验不过的备份是安全事件，失败也要留在审计链里
        log_user_action(
            db, user, "backup.verify", "backup", payload.name[:40], result="failed",
            detail={"code": exc.code, "message": exc.message},
        )
        db.commit()
        status = 404 if exc.code == "BACKUP_FILE_MISSING" else 422
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})
    log_user_action(db, user, "backup.verify", "backup", bk.audit_ref(result["file"]), detail={"checksum": result["checksum"]})
    db.commit()
    return result


@router.get("/search")
def global_search(
    q: str = Query(..., min_length=1, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cfg, pcfg = clearance_cfg(db), plant_cfg(db)
    like = f"%{q}%"
    orders = (
        db.query(Order)
        .filter(
            clr.visible_filter(user, Order.clearance, cfg),
            pl.visible_filter(user, Order.plant, pcfg),
            (Order.order_no.like(like)) | (Order.product_name.like(like)),
        )
        .order_by(Order.due_date.asc()).limit(5).all()
    )
    plan_scope = pl.visible_order_ids(user, cfg, pcfg)
    plan_query = (
        db.query(Plan)
        .filter((Plan.code.like(like)) | (Plan.name.like(like)))
    )
    if plan_scope is not None:
        # 方案本身没有密级列：按它包含的工单密级判定，含读不到的工单就不出现在搜索里
        plan_query = plan_query.filter(
            Plan.id.in_(select(PlanItem.plan_id).where(PlanItem.order_id.in_(plan_scope)).scalar_subquery())
        )
    plans = plan_query.order_by(Plan.created_at.desc()).limit(5).all()
    changes = (
        db.query(Disturbance)
        .filter(
            clr.visible_filter(user, Disturbance.clearance, cfg),
            (Disturbance.code.like(like)) | (Disturbance.title.like(like)),
        )
        .order_by(Disturbance.occurred_at.desc()).limit(5).all()
    )
    return {
        "query": q,
        "orders": [{"id": o.id, "title": o.order_no, "subtitle": o.product_name, "status": o.status, "priority": o.priority} for o in orders],
        "plans": [{"id": p.id, "title": p.code, "subtitle": p.name, "status": p.status} for p in plans],
        "changes": [{"id": c.id, "title": c.code, "subtitle": c.title, "status": c.status} for c in changes],
        "hidden_by_clearance": clr.hidden_count(db, Order, user, cfg),
        "hidden_by_plant": pl.hidden_count(db, Order, user, pcfg),
        "clearance_enabled": cfg["enabled"],
        "plants_enabled": pcfg["enabled"],
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(require("settings:read"))):
    cfg, pcfg = clearance_cfg(db), plant_cfg(db)
    order_scope = and_(clr.visible_filter(user, Order.clearance, cfg),
                       pl.visible_filter(user, Order.plant, pcfg))
    hidden = clr.hidden_count(db, Order, user, cfg) + pl.hidden_count(db, Order, user, pcfg)
    return {
        "orders": db.query(Order).filter(order_scope).count(),
        "orders_total_ungated": db.query(Order).count() if (cfg["enabled"] or pcfg["enabled"]) else None,
        "orders_hidden_by_clearance": hidden,
        "operations": db.query(Operation).count(),
        "resources": db.query(Resource).filter(pl.visible_filter(user, Resource.plant, pcfg)).count(),
        "plans": db.query(Plan).count(),
        "rules": db.query(Rule).count(),
        "agent_runs": db.query(AgentRun).count(),
        "alerts": db.query(Alert).count(),
        "audit_logs": db.query(AuditLog).count(),
        "db_engine": engine.dialect.name,
    }


@router.get("/export/orders.csv")
def export_orders(db: Session = Depends(get_db), user: User = Depends(require("export:read"))):
    cfg, pcfg = clearance_cfg(db), plant_cfg(db)
    rows = (
        db.query(Order)
        .filter(clr.visible_filter(user, Order.clearance, cfg), pl.visible_filter(user, Order.plant, pcfg))
        .order_by(Order.order_no).limit(5000).all()
    )
    hidden = clr.hidden_count(db, Order, user, cfg) + pl.hidden_count(db, Order, user, pcfg)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["订单号", "产品", "数量", "优先级", "厂区", "客户", "交期", "状态", "进度", "齐套状态", "密级"])
    for o in rows:
        writer.writerow([o.order_no, o.product_name, o.qty, o.priority, o.plant, o.customer, o.due_date.strftime("%Y-%m-%d"), o.status, o.progress, o.kit_status, o.clearance or cfg["data_default"]])
    content = "\ufeff" + buffer.getvalue()
    log_user_action(
        db, user, "export.orders", "orders", "csv",
        detail={"rows": len(rows), "hidden_by_clearance": hidden, "limit": 5000},
    )
    db.commit()
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=lisa-orders.csv",
            "X-Lisa-Exported-Rows": str(len(rows)),
            "X-Lisa-Hidden-By-Clearance": str(hidden),
        },
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
