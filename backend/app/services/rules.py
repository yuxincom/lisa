from __future__ import annotations

from datetime import datetime, time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Operation, Order, Resource, Rule
from .calendar import WORK_END, WORK_START, is_workday
from .rule_data import HARD_CONSTRAINTS, SOFT_CONSTRAINTS

PRIORITIES = {"P0", "P1", "P2", "P3"}
RISKS = {"normal", "late", "tight", "blocked"}


def _attr(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def serialize_rule(rule: Rule) -> dict:
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


def rule_catalog(db: Session) -> dict:
    rules = db.query(Rule).order_by(Rule.code.asc()).all()
    hard = [r for r in rules if r.kind == "hard"]
    soft = [r for r in rules if r.kind == "soft"]
    plain = [r for r in rules if r.kind == "rule"]
    categories: dict[str, int] = {}
    for rule in plain:
        categories[rule.category] = categories.get(rule.category, 0) + 1
    return {
        "summary": {
            "total": len(rules),
            "rules": len(plain),
            "hard": len(hard),
            "soft": len(soft),
            "enabled": sum(1 for r in rules if r.enabled),
            "categories": [{"name": k, "count": v} for k, v in categories.items()],
        },
        "rules": [serialize_rule(r) for r in plain],
        "hard_constraints": [serialize_rule(r) for r in hard],
        "soft_constraints": [serialize_rule(r) for r in soft],
    }


def validate_schedule(db: Session, items: list[Any]) -> dict:
    resource_map = {r.id: r for r in db.query(Resource).all()}
    op_ids = [int(_attr(i, "operation_id")) for i in items if _attr(i, "operation_id")]
    op_map = {o.id: o for o in db.query(Operation).filter(Operation.id.in_(op_ids)).all()} if op_ids else {}
    order_ids = list({int(_attr(i, "order_id")) for i in items})
    order_map = {o.id: o for o in db.query(Order).filter(Order.id.in_(order_ids)).all()}

    issues: dict[str, dict] = {}

    def add(code: str, message: str, target: str = ""):
        bucket = issues.setdefault(code, {"code": code, "count": 0, "samples": []})
        bucket["count"] += 1
        if len(bucket["samples"]) < 5:
            bucket["samples"].append({"target": target, "message": message})

    groups: dict[int, list[Any]] = {}
    for item in items:
        groups.setdefault(int(_attr(item, "order_id")), []).append(item)

    for order_id, group in groups.items():
        group.sort(key=lambda x: int(_attr(x, "seq")))
        seqs = [int(_attr(x, "seq")) for x in group]
        if seqs != list(range(1, len(seqs) + 1)):
            add("HC-05", f"订单 {_attr(group[0], 'order_no')} 工艺路线不连续", str(order_id))
        for idx in range(1, len(group)):
            prev, cur = group[idx - 1], group[idx]
            prev_end = _attr(prev, "end")
            cur_start = _attr(cur, "start")
            if prev_end and cur_start and cur_start < prev_end:
                add("HC-12", f"{_attr(cur, 'order_no')} 工序 {_attr(cur, 'seq')} 早于前序完工", str(_attr(cur, 'operation_id')))
    for item in items:
        label = f"{_attr(item, 'order_no')} #{_attr(item, 'seq')} {_attr(item, 'name')}"
        start: datetime | None = _attr(item, "start")
        end: datetime | None = _attr(item, "end")
        resource_id = _attr(item, "resource_id")
        resource = resource_map.get(int(resource_id)) if resource_id else None
        if not _attr(item, "order_no") or not _attr(item, "name") or not resource:
            add("HC-02", f"{label} 必填字段缺失", label)
        if not start or not end:
            add("HC-02", f"{label} 缺少计划起止时间", label)
            continue
        duration = _attr(item, "duration_minutes") or (end - start).total_seconds() / 60
        if duration < 5 or duration > 48 * 60:
            add("HC-06", f"{label} 计划时长 {duration:.0f}min 超出值域", label)
        op = op_map.get(int(_attr(item, "operation_id"))) if _attr(item, "operation_id") else None
        if op and duration < op.std_minutes * 0.8:
            add("HC-07", f"{label} 计划工时与标准工时偏差超 20%", label)
        if not is_workday(start) or not (WORK_START <= start.time() < WORK_END):
            add("HC-08", f"{label} 起始时间落在非工作班次", label)
        if resource and _attr(item, "domain") != resource.domain:
            add("HC-09", f"{label} 资源 {resource.name} 能力域不匹配", label)
        if resource and resource.efficiency < 0.6:
            add("HC-13", f"{label} 资源技能覆盖不足", label)
        priority = _attr(item, "priority")
        if priority and priority not in PRIORITIES:
            add("HC-03", f"{label} 优先级取值非法", label)
        risk = _attr(item, "risk")
        if risk and risk not in RISKS:
            add("HC-11", f"{label} 风险等级取值非法", label)

    checks = []
    for code, title, description in HARD_CONSTRAINTS:
        issue = issues.get(code)
        checks.append(
            {
                "code": code,
                "title": title,
                "description": description,
                "passed": issue is None,
                "count": issue["count"] if issue else 0,
                "samples": issue["samples"] if issue else [],
            }
        )

    soft = []
    late_by_order: dict[str, int] = {}
    for item in items:
        if _attr(item, "risk") == "late":
            late_by_order[str(_attr(item, "order_no"))] = late_by_order.get(str(_attr(item, "order_no")), 0) + 1
    if late_by_order:
        soft.append(
            {
                "code": "SC-01",
                "title": "交期优先",
                "severity": "warning",
                "count": len(late_by_order),
                "message": f"{len(late_by_order)} 个订单存在逾期风险",
                "samples": list(late_by_order.keys())[:5],
            }
        )
    kit_gaps = [order_map[oid] for oid in groups if oid in order_map and order_map[oid].kit_status != "齐套"]
    if kit_gaps:
        soft.append(
            {
                "code": "SC-05",
                "title": "齐套优先",
                "severity": "warning",
                "count": len(kit_gaps),
                "message": f"{len(kit_gaps)} 个订单齐套状态异常",
                "samples": [o.order_no for o in kit_gaps[:5]],
            }
        )
    if items:
        starts = [_attr(i, "start") for i in items if _attr(i, "start")]
        ends = [_attr(i, "end") for i in items if _attr(i, "end")]
        if starts and ends:
            span_hours = max(1.0, (max(ends) - min(starts)).total_seconds() / 3600)
            by_res: dict[int, float] = {}
            for item in items:
                rid = _attr(item, "resource_id")
                if rid:
                    by_res[int(rid)] = by_res.get(int(rid), 0) + float(_attr(item, "duration_minutes") or 0)
            overloaded = [
                resource_map[rid].name
                for rid, minutes in by_res.items()
                if rid in resource_map and resource_map[rid].bottleneck and minutes / 60 / span_hours > 0.88
            ]
            if overloaded:
                soft.append(
                    {
                        "code": "SC-02",
                        "title": "瓶颈保护",
                        "severity": "info",
                        "count": len(overloaded),
                        "message": f"{len(overloaded)} 个瓶颈资源负荷超过 88%",
                        "samples": overloaded[:5],
                    }
                )

    hard_count = sum(c["count"] for c in checks if not c["passed"])
    return {
        "passed": hard_count == 0,
        "hard_count": hard_count,
        "soft_count": sum(s["count"] for s in soft),
        "checks": checks,
        "soft": soft,
        "evaluated_at": datetime.now().replace(microsecond=0).isoformat(),
        "engine": "LISA SHACL/HC 双校验通道 + 规则引擎",
        "rule_version": "ZD-01-2026",
        "constraint_version": "HC-01~14 / SC-01~13",
    }


def increment_rule_hits(db: Session, codes: list[str]) -> None:
    if not codes:
        return
    db.query(Rule).filter(Rule.code.in_(codes)).update({Rule.hits: Rule.hits + 1}, synchronize_session=False)
