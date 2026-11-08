from __future__ import annotations

"""LISA 的 MCP 工具面（F4 白名单：**只读**工具，写操作一律不注册）。

同一批工具既给内网大模型做编排（services/llm.py），也能被任何标准 MCP 客户端
（自研 Agent 框架 / Claude Desktop 之类）通过 JSON-RPC 2.0 直接调用：
`initialize` / `tools/list` / `tools/call` / `ping`。

三条硬规矩：
1. 工具只读——排产、审批、写回没有工具，模型无法绕过审批与写保护网关；
2. 每次调用都进审计哈希链，调用者身份沿用登录用户（ABAC 属性一致）；
3. 返回给模型的文本先过脱敏（services/llm.redact），凭据与连接串永不进上下文。
"""

import json
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..config import APP_NAME, APP_VERSION, DATABASE_URL, ENVIRONMENT
from ..models import Disturbance, KitCheck, Order, Plan, PlanItem, Product, Resource, Rule, User
from . import clearance
from . import knowledge as kb
from . import plants
from .audit import log_user_action
from .impact import assess_disturbance
from .kits import build_check, kit_overview
from .quality import quality_summary
from .rules import serialize_rule, validate_schedule


def _read_scope(db: Session, user: User) -> tuple[dict, dict]:
    """MCP 工具面与 HTTP 面必须用同一条读取范围：密级 + 厂区，两条一起算。"""
    return clearance.config(db), plants.config(db)


def _order_ids(db: Session, user: User):
    cfg, pcfg = _read_scope(db, user)
    return plants.visible_order_ids(user, cfg, pcfg)


def _order_filter(db: Session, user: User, clearance_column, plant_column):
    cfg, pcfg = _read_scope(db, user)
    return and_(clearance.visible_filter(user, clearance_column, cfg),
                plants.visible_filter(user, plant_column, pcfg))

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "lisa-aps", "version": APP_VERSION, "title": APP_NAME}
INSTRUCTIONS = (
    "LISA 排产域只读工具集。所有数据来自生产库实算，不含推测值；"
    "字段为「未接入/未校验」时表示上游主数据缺失，请如实转述，不要当成 0 或已满足。"
)

TOOLS: list[dict[str, Any]] = []
HANDLERS: dict[str, Callable[..., dict]] = {}

WRITE_PREFIXES = ("apply_", "approve_", "create_", "update_", "delete_", "write_", "save_")


class McpError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None,
         when: str = ""):
    def wrapper(func: Callable[..., dict]) -> Callable[..., dict]:
        if name.startswith(WRITE_PREFIXES):
            raise McpError("MCP_TOOL_WRITE_DENIED", f"只读工具面不允许注册写操作：{name}")
        TOOLS.append(
            {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": properties or {},
                    "required": required or [],
                },
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "whenToUse": when},
            }
        )
        HANDLERS[name] = func
        return func

    return wrapper


def _limit(value: Any, default: int = 20, maximum: int = 50) -> int:
    try:
        return max(1, min(maximum, int(value or default)))
    except (TypeError, ValueError):
        return default


def _moment(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _pick_plan(db: Session, plan_code: str = "") -> Plan:
    if plan_code:
        plan = db.query(Plan).filter(Plan.code == plan_code).first()
        if not plan:
            raise McpError("MCP_PLAN_NOT_FOUND", f"方案 {plan_code} 不存在")
        return plan
    plan = (
        db.query(Plan).filter(Plan.status.in_(["applied", "approved"])).order_by(Plan.applied_at.desc()).first()
        or db.query(Plan).filter(Plan.status == "pending").order_by(Plan.submitted_at.desc()).first()
        or db.query(Plan).order_by(Plan.created_at.desc()).first()
    )
    if not plan:
        raise McpError("MCP_NO_PLAN", "库里还没有任何排产方案，先跑一次排产")
    return plan


def _deny(db: Session, user: User, target_type: str, target_id: str, required: str, message: str) -> None:
    """密级拒绝本身是安全事件：先落审计链再报错，否则「谁试过读什么」无迹可查。"""
    log_user_action(
        db, user, "mcp.clearance.denied", target_type, target_id, result="denied",
        detail={"required": required, "reader": user.clearance or "未标注"},
    )
    db.commit()
    raise McpError("MCP_CLEARANCE_DENIED", message)


def _find_order(db: Session, order_no: str, user: User) -> Order:
    order = db.query(Order).filter(Order.order_no == (order_no or "").strip()).first()
    if not order:
        raise McpError("MCP_ORDER_NOT_FOUND", f"工单 {order_no} 不存在")
    cfg = clearance.config(db)
    if not clearance.can_read(user, order, cfg):
        _deny(
            db, user, "order", order.order_no, order.clearance or cfg["data_default"],
            f"工单 {order.order_no} 的密级高于 {user.username}（{user.clearance or '未标注'}）当前可读范围，"
            "工具面按 fail-closed 拒绝，不代表该工单不存在",
        )
    _, pcfg = _read_scope(db, user)
    if not plants.can_read(user, order, pcfg):
        _deny(
            db, user, "order", order.order_no, order.plant,
            f"工单 {order.order_no} 在 {order.plant}，不在 {user.username} 的厂区读取范围内，"
            "工具面按 fail-closed 拒绝，不代表该工单不存在",
        )
    return order


# ---------------------------------------------------------------------- 工具实现


@tool(
    "lisa_health",
    "系统自检：环境、数据库引擎、主数据规模与在制订单数，用于判断回答该基于哪一天的数据。",
)
def health(db: Session, user: User, args: dict) -> dict:
    from .adapters import source_configs

    cfg = clearance.config(db)
    visible = _order_filter(db, user, Order.clearance, Order.plant)
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "db_engine": DATABASE_URL.split("://")[0] if "://" in DATABASE_URL else "unknown",
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "counts": {
            "orders": db.query(Order).filter(visible).count(),
            "open_orders": db.query(Order).filter(visible, ~Order.status.in_(["已完工", "已取消"])).count(),
            "products": db.query(Product).count(),
            "resources": db.query(Resource).count(),
            "plans": db.query(Plan).count(),
            "rules": db.query(Rule).count(),
            "kit_checks": db.query(KitCheck).count(),
        },
        "adapter_channels": len(source_configs(db)),
    }


@tool(
    "list_orders",
    "按优先级/工序域/齐套状态列在制订单，交期升序；用于「现在最紧的是哪些单」。",
    {
        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "description": "优先级，留空=全部"},
        "kit_status": {"type": "string", "description": "齐套状态：齐套/缺项/缺料/阻断/待接入"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
    },
)
def list_orders(db: Session, user: User, args: dict) -> dict:
    cfg = clearance.config(db)
    scope = db.query(Order).filter(~Order.status.in_(["已完工", "已取消"]))
    query = scope.filter(_order_filter(db, user, Order.clearance, Order.plant))
    if args.get("priority"):
        query = query.filter(Order.priority == args["priority"])
    if args.get("kit_status"):
        query = query.filter(Order.kit_status == args["kit_status"])
    rows = query.order_by(Order.priority.asc(), Order.due_date.asc()).limit(_limit(args.get("limit"))).all()
    visible_open = scope.filter(clearance.visible_filter(user, Order.clearance, cfg)).count()
    return {
        "total_open": visible_open,
        "returned": len(rows),
        "hidden_by_clearance": clearance.hidden_count(db, Order, user, cfg),
        "orders": [
            {
                "order_no": o.order_no,
                "priority": o.priority,
                "qty": o.qty,
                "clearance": o.clearance or cfg["data_default"],
                "due_date": _moment(o.due_date),
                "status": o.status,
                "kit_status": o.kit_status,
                "progress": o.progress,
                "days_left": (o.due_date - datetime.now()).days if o.due_date else None,
            }
            for o in rows
        ],
    }


@tool(
    "order_detail",
    "单个工单的展开视图：工序链（含能力域、资源、时间、锁定与前置依赖）+ 三个时点的齐套结论。",
    {"order_no": {"type": "string", "description": "工单号，如 MO-2026-0012"}},
    ["order_no"],
)
def order_detail(db: Session, user: User, args: dict) -> dict:
    from ..models import Operation

    order = _find_order(db, str(args.get("order_no", "")), user)
    ops = db.query(Operation).filter(Operation.order_id == order.id).order_by(Operation.seq.asc()).all()
    resource_map = {r.id: r for r in db.query(Resource).all()}
    predecessor_map = {op.id: op for op in ops}
    checkpoints = ("pre_schedule", "post_schedule", "pre_start")
    checks = [(cp, build_check(db, order, cp)) for cp in checkpoints]
    return {
        "order": {
            "order_no": order.order_no,
            "product_name": order.product_name,
            "qty": order.qty,
            "priority": order.priority,
            "clearance": order.clearance or "内部",
            "plant": order.plant,
            "due_date": _moment(order.due_date),
            "status": order.status,
            "kit_status": order.kit_status,
            "progress": order.progress,
        },
        "operations": [
            {
                "seq": op.seq,
                "name": op.name,
                "domain": op.domain,
                "planned_start": _moment(op.planned_start),
                "planned_end": _moment(op.planned_end),
                "std_minutes": float(op.std_minutes or 0),
                "setup_minutes": float(op.setup_minutes or 0),
                "resource": resource_map[op.resource_id].code if op.resource_id in resource_map else None,
                "status": op.status,
                "special_process": bool(op.special),
                "valid_until": _moment(op.valid_until),
                "locked": bool(op.locked),
                "predecessor_seq": predecessor_map[op.predecessor_id].seq if op.predecessor_id in predecessor_map else None,
                "lag_minutes": float(op.lag_minutes or 0),
            }
            for op in ops
        ],
        "kit": [
            {
                "checkpoint": cp,
                "label": c["checkpoint_label"],
                "status": c["status"],
                "score": c["score"],
                "evaluated_elements": c["evaluated_count"],
                "gaps": len(c["gaps"]),
                "unevaluated": len(c["unevaluated"]),
                "passed": c["passed"],
            }
            for cp, c in checks
        ],
    }


@tool(
    "kit_check",
    "对一个工单、一个检查点做齐套九要素实算：每要素的取值、缺口量化与责任部门。",
    {
        "order_no": {"type": "string"},
        "checkpoint": {"type": "string", "enum": ["pre_schedule", "post_schedule", "pre_start"], "default": "pre_start"},
    },
    ["order_no"],
)
def kit_check(db: Session, user: User, args: dict) -> dict:
    order = _find_order(db, str(args.get("order_no", "")), user)
    checkpoint = args.get("checkpoint") or "pre_start"
    if checkpoint not in ("pre_schedule", "post_schedule", "pre_start"):
        raise McpError("MCP_CHECKPOINT_UNKNOWN", f"未知的齐套检查点：{checkpoint}")
    return build_check(db, order, checkpoint)


@tool(
    "kit_summary",
    "全厂齐套概览：三个时点的通过率、缺项数、阻断数与未接入数，缺口的责任部门分布。",
)
def kit_summary(db: Session, user: User, args: dict) -> dict:
    cfg = clearance.config(db)
    result = kit_overview(db, _order_ids(db, user))
    result["hidden_orders_by_clearance"] = clearance.hidden_count(db, Order, user, cfg)
    return result


@tool(
    "resource_load",
    "资源负荷：按方案实算每台/每型设备的占用工时、负荷率与状态，瓶颈设备排在前面。",
    {
        "plan_code": {"type": "string", "description": "留空=最近一次已批准/已应用方案，其次取最新方案"},
        "domain": {"type": "string", "description": "工序域，如 机加/热表/装配"},
        "horizon_days": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
        "limit": {"type": "integer", "minimum": 1, "maximum": 60, "default": 20},
    },
)
def resource_load(db: Session, user: User, args: dict) -> dict:
    plan = _pick_plan(db, str(args.get("plan_code", "")))
    cfg = clearance.config(db)
    window = _limit(args.get("horizon_days", 30), 30, 120)
    horizon = datetime.now() + timedelta(days=window)
    query = db.query(PlanItem).filter(PlanItem.plan_id == plan.id, PlanItem.start <= horizon)
    scope = _order_ids(db, user)
    if scope is not None:
        query = query.filter(PlanItem.order_id.in_(scope))
    rows = query.all()
    if args.get("domain"):
        rows = [r for r in rows if r.domain == args["domain"]]
    per_resource: dict[str, dict] = {}
    for item in rows:
        key = item.resource_code or item.resource_name or "未分配"
        bucket = per_resource.setdefault(
            key,
            {"resource": key, "name": item.resource_name, "domain": item.domain,
             "operations": 0, "minutes": 0.0, "_first": None, "_last": None},
        )
        bucket["operations"] += 1
        bucket["minutes"] += float(item.duration_minutes or 0)
        bucket["_first"] = min(filter(None, [bucket["_first"], item.start]), default=None)
        bucket["_last"] = max(filter(None, [bucket["_last"], item.end]), default=None)
    resources = {r.code: r for r in db.query(Resource).all()}
    for key, bucket in per_resource.items():
        resource = resources.get(key)
        machines = int(resource.machine_count or 1) if resource else 1
        daily = float(resource.capacity_hours or 20.0) if resource else 20.0
        available = machines * daily * window * 60.0
        bucket["minutes"] = round(bucket["minutes"], 1)
        bucket["first_start"] = _moment(bucket.pop("_first"))
        bucket["last_end"] = _moment(bucket.pop("_last"))
        bucket["machines"] = machines
        bucket["capacity_minutes_in_window"] = round(available, 1)
        bucket["load_rate"] = round(bucket["minutes"] / available * 100, 1) if available else 0.0
        bucket["status"] = resource.status if resource else "unknown"
        bucket["bottleneck"] = bool(resource.bottleneck) if resource else False
    items = sorted(per_resource.values(), key=lambda b: -b["load_rate"])
    return {
        "plan": plan.code,
        "plan_status": plan.status,
        "horizon_days": window,
        "operations": len(rows),
        "unassigned": sum(1 for b in per_resource.values() if b["resource"] == "未分配"),
        "resources": items[: _limit(args.get("limit"), 20, 60)],
    }


@tool(
    "plan_detail",
    "一个排产方案的完整口径：KPI、目标权重、方案说明、硬约束违规数、未校验项与相对基线的差异。",
    {"plan_code": {"type": "string", "description": "留空=最近一次已批准/已应用方案"}},
)
def plan_detail(db: Session, user: User, args: dict) -> dict:
    plan = _pick_plan(db, str(args.get("plan_code", "")))
    cfg = clearance.config(db)
    summary = plan.summary or {}
    return {
        "code": plan.code,
        "name": plan.name,
        "type": plan.type,
        "status": plan.status,
        "scenario": plan.scenario,
        "objective": plan.objective,
        "weights": plan.weights or {},
        "kpi": plan.kpi or {},
        "orders": summary.get("orders"),
        "operations": summary.get("operations"),
        "domains": summary.get("domains"),
        "p0_orders": summary.get("p0_orders"),
        "kit_risk": summary.get("kit_risk"),
        "late_orders": summary.get("late_orders"),
        "locked_operations": summary.get("locked_operations"),
        "unassigned_operations": summary.get("unassigned_operations"),
        "resource_lanes": summary.get("resource_lanes"),
        "dependency_cycles": summary.get("dependency_cycles"),
        "hard_count": summary.get("hard_count", 0),
        "unevaluated": summary.get("unevaluated", []),
        "soft_violations": summary.get("soft_violations", []),
        "reasoning": summary.get("reasoning", []),
        "solver": summary.get("solver"),
        "algorithm": summary.get("algorithm"),
        "diff": plan.diff or {},
        "created_at": _moment(plan.created_at),
        "applied_at": _moment(plan.applied_at),
        "orders_hidden_by_clearance": clearance.hidden_count(db, Order, user, cfg),
    }


@tool(
    "hard_constraint_scan",
    "对某个方案的排程结果重新逐条实算 HC-01~14 硬约束与 SC 软约束，返回每条的判定与样本。",
    {"plan_code": {"type": "string"}, "only_failed": {"type": "boolean", "default": False}},
)
def hard_constraint_scan(db: Session, user: User, args: dict) -> dict:
    plan = _pick_plan(db, str(args.get("plan_code", "")))
    cfg = clearance.config(db)
    query = db.query(PlanItem).filter(PlanItem.plan_id == plan.id)
    scope = _order_ids(db, user)
    if scope is not None:
        query = query.filter(PlanItem.order_id.in_(scope))
    items = query.all()
    if not items:
        raise McpError("MCP_PLAN_EMPTY", f"方案 {plan.code} 没有工序明细，无法校验")
    report = validate_schedule(db, items)
    checks = report["checks"]
    if args.get("only_failed"):
        checks = [c for c in checks if c.get("evaluated", True) and not c.get("passed")]
    return {
        "plan": plan.code,
        "items": len(items),
        "passed": report["passed"],
        "hard_count": report["hard_count"],
        "hard_failed": report["hard_failed"],
        "soft_count": report["soft_count"],
        "unevaluated": report["unevaluated"],
        "checks": checks,
        "engine": report["engine"],
        "constraint_version": report["constraint_version"],
    }


@tool(
    "data_quality",
    "L0 数据质量五维点检与门禁结论：完整性/及时性/一致性/准确性/唯一性，任一维 <90% 禁止进入排产链路。",
)
def data_quality(db: Session, user: User, args: dict) -> dict:
    summary = quality_summary(db)
    return {
        "overall": summary["overall"],
        "gate": summary["gate"],
        "dimensions": [
            {"key": d["key"], "label": d["label"], "score": d["score"], "threshold": d["threshold"],
             "passed": d["passed"], "issues": (d.get("detail") or {}).get("issues"), "source": d["source"]}
            for d in summary["dimensions"]
        ],
        "sources": [
            {"code": s["code"], "name": s["name"], "status": s["status"], "records": s["records"],
             "quality": s["quality"], "last_sync": s["last_sync"], "owner": s["owner"]}
            for s in summary.get("sources", [])
        ],
    }


@tool(
    "main_data_freshness",
    "齐套外部主数据的时效（ERP BOM / WMS 库存 / 在途 / 工装刀具 / 资质 / 检验结论）与接入通道状态。",
)
def main_data_freshness(db: Session, user: User, args: dict) -> dict:
    from .adapters import adapter_overview

    overview = adapter_overview(db)
    return {
        "freshness": overview["freshness"],
        "channels": [
            {"name": s["name"], "kind": s["kind"], "channel": s["channel"], "enabled": s["enabled"],
             "last_sync": s["last_sync"], "rows": s["rows"], "error": s["error"]}
            for s in overview["sources"]
        ],
        "note": "rows=0 表示该类主数据尚未接入，齐套对应要素会判「未接入」而不是满足",
    }


@tool(
    "change_impact",
    "一次扰动事件（故障/缺料/插单/返工/ECN…）的涟漪影响：受影响订单与工序、延误量化、置信度。",
    {"change_code": {"type": "string", "description": "事件编号，如 CHG-2026-0007"}},
    ["change_code"],
)
def change_impact(db: Session, user: User, args: dict) -> dict:
    code = str(args.get("change_code", "")).strip()
    cfg = clearance.config(db)
    change = db.query(Disturbance).filter(Disturbance.code == code).first()
    if not change:
        raise McpError("MCP_CHANGE_NOT_FOUND", f"变更事件 {code} 不存在")
    if not clearance.can_read(user, change, cfg) and change.reporter != (user.name or ""):
        _deny(
            db, user, "change", code, change.clearance or cfg["data_default"],
            f"变更事件 {code} 的影响面高于 {user.username}（{user.clearance or '未标注'}）的密级，按 fail-closed 拒绝",
        )
    impact = assess_disturbance(db, change)
    summary = impact["summary"]
    allowed = set(clearance.allowed_values(user, cfg))
    visible_affected = [
        o for o in impact.get("affected_orders", [])
        if (o.get("clearance") or cfg.get("data_default")) in allowed
    ]
    return {
        "change": {"code": change.code, "type": change.type, "title": change.title,
                   "severity": change.severity, "status": change.status, "clearance": change.clearance},
        "summary": summary,
        "affected_orders": [
            {"order_no": o.get("order_no"), "priority": o.get("priority"),
             "delay_days": o.get("delay_days"), "domains": o.get("domains")}
            for o in visible_affected[:15]
        ],
        "affected_orders_total": summary.get("affected_orders", len(impact.get("affected_orders", []))),
        "affected_orders_hidden_by_clearance": len(impact.get("affected_orders", [])) - len(visible_affected),
        "options": {k: v for k, v in (change.options or {}).items()},
        "recommendation": impact.get("recommendation"),
    }


@tool(
    "search_knowledge",
    "检索工艺/制度知识与规则条目，命中结果带 source_ref 与 trace_version，可回查原始出处。",
    {"query": {"type": "string", "maxLength": 200}, "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 6}},
    ["query"],
)
def search_knowledge(db: Session, user: User, args: dict) -> dict:
    query = str(args.get("query", "")).strip()[:200]
    if not query:
        raise McpError("MCP_QUERY_EMPTY", "检索词不能为空")
    result = kb.search(db, query, _limit(args.get("top_k", 6), 6, 20))
    for item in result["items"]:
        item["content"] = (item["content"] or "")[:320]
    return result


@tool(
    "rule_detail",
    "按编号取一条硬约束/软约束/业务规则的完整定义：判定口径、命中次数、适用域与出处。",
    {"code": {"type": "string", "description": "如 HC-04、SC-05、R002"}},
    ["code"],
)
def rule_detail(db: Session, user: User, args: dict) -> dict:
    code = str(args.get("code", "")).strip().upper()
    rule = db.query(Rule).filter(Rule.code == code).first()
    if not rule:
        raise McpError("MCP_RULE_NOT_FOUND", f"规则 {code} 不在 ZD-01-2026 台账里")
    return serialize_rule(rule)


# ------------------------------------------------------------------- JSON-RPC


def list_tools() -> dict:
    return {"tools": TOOLS}


def call_tool(db: Session, user: User, name: str, arguments: dict | None, commit: bool = True) -> dict:
    handler = HANDLERS.get(name)
    if handler is None:
        raise McpError("MCP_TOOL_UNKNOWN", f"未注册的工具：{name}（写操作一律不开放）")
    args = arguments or {}
    if not isinstance(args, dict):
        raise McpError("MCP_ARGS_INVALID", f"{name} 的参数必须是对象")
    started = datetime.now()
    try:
        payload = handler(db, user, args)
    except McpError:
        raise
    except Exception as exc:  # noqa: BLE001 - 源数据异常回传错误码，不把堆栈透给调用方
        db.rollback()
        raise McpError("MCP_TOOL_FAILED", f"{name} 执行失败：{type(exc).__name__}: {exc}") from exc
    elapsed = int((datetime.now() - started).total_seconds() * 1000)
    text = json.dumps(payload, ensure_ascii=False, default=str)
    log_user_action(
        db, user, "mcp.tool_call", "mcp_tool", name,
        detail={"arguments": {k: str(v)[:80] for k, v in args.items()}, "ms": elapsed, "chars": len(text)},
    )
    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "content": [{"type": "text", "text": text}],
        "isError": False,
        "structured": payload,
        "latency_ms": elapsed,
    }


def handle_request(db: Session, user: User, request: dict) -> dict | None:
    """MCP 2024-11-05 的 JSON-RPC 子集：只实现只读能力，notifications 返回 None。"""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32600, "message": "必须是 JSON-RPC 2.0 请求对象"}}
    method = str(request.get("method") or "")
    request_id = request.get("id")
    params = request.get("params") or {}

    def result(payload: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": payload}

    def error(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return result(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            }
        )
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return result({})
    if method == "tools/list":
        return result(list_tools())
    if method == "tools/call":
        name = str(params.get("name") or "")
        try:
            return result(call_tool(db, user, name, params.get("arguments")))
        except McpError as exc:
            return result({"content": [{"type": "text", "text": exc.message}], "isError": True,
                           "error": {"code": exc.code, "message": exc.message}})
    return error(-32601, f"不支持的方法：{method}（本服务只提供 initialize / tools/list / tools/call / ping）")
