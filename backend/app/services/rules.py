from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Operation, Order, Product, Qualification, Resource, Rule
from .calendar import CalendarHorizonError, active_calendar
from .rule_data import HARD_CONSTRAINTS, SOFT_CONSTRAINTS

PRIORITIES = {"P0", "P1", "P2", "P3"}
RISKS = {"normal", "late", "tight", "blocked"}
ORDER_STATUS = {
    "待排产", "已排产", "执行中", "已完工", "逾期", "已取消", "暂停",
}
# 关键工序要求人员持证；主数据（投产配置清单 C4）接入前无法实算，见 UNEVALUATED
UNEVALUATED_CHECKS = {
    "HC-10": "未接入人员资质主数据（配置清单 C4），本次未校验",
}
MAX_DEPENDENCY_WALK = 64


def _max_concurrent(intervals: list[tuple[datetime, datetime]]) -> int:
    """扫描线求最大同时占用数；同一时刻「先结束后开始」不算重叠。"""
    if not intervals:
        return 0
    points: list[tuple[datetime, int]] = []
    for start, end in intervals:
        points.append((start, 1))
        points.append((end, -1))
    points.sort(key=lambda x: (x[0], x[1]))
    depth = peak = 0
    for _, delta in points:
        depth += delta
        peak = max(peak, depth)
    return peak


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


def _dependency_state(op: Operation, registry: dict[int, Operation]) -> tuple[str | None, Operation | None]:
    """返回 (悬空/成环 说明, 前置工序)。"""
    if not op.predecessor_id:
        return None, None
    seen = {op.id}
    current = registry.get(op.predecessor_id)
    if current is None:
        return f"前置工序 #{op.predecessor_id} 不存在", None
    steps = 0
    while current.predecessor_id and steps < MAX_DEPENDENCY_WALK:
        if current.predecessor_id in seen:
            return "前置依赖链成环", None
        seen.add(current.id)
        nxt = registry.get(current.predecessor_id)
        if nxt is None:
            return f"前置工序 #{current.predecessor_id} 不存在", None
        current = nxt
        steps += 1
    if steps >= MAX_DEPENDENCY_WALK:
        return "前置依赖链过深，疑似成环", None
    return None, current


def validate_schedule(db: Session, items: list[Any], unassigned: list[dict] | None = None) -> dict:
    resource_map = {r.id: r for r in db.query(Resource).all()}
    op_ids = [int(_attr(i, "operation_id")) for i in items if _attr(i, "operation_id")]
    op_map = {o.id: o for o in db.query(Operation).filter(Operation.id.in_(op_ids)).all()} if op_ids else {}
    order_ids = list({int(_attr(i, "order_id")) for i in items})
    order_map = {o.id: o for o in db.query(Order).filter(Order.id.in_(order_ids)).all()} if order_ids else {}

    issues: dict[str, dict] = {}

    def add(code: str, message: str, target: str = ""):
        bucket = issues.setdefault(code, {"code": code, "count": 0, "samples": []})
        bucket["count"] += 1
        if len(bucket["samples"]) < 5:
            bucket["samples"].append({"target": target, "message": message})

    # ---------------- HC-01 概念完备性：订单—产品—工艺路线—工序—资源 链必须齐备
    product_ids = {o.product_id for o in order_map.values() if o.product_id}
    product_map = {p.id: p for p in db.query(Product).filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    for order in order_map.values():
        if not order.product_id:
            add("HC-01", f"订单 {order.order_no} 未关联产品，本体链路断裂", order.order_no)
            continue
        product = product_map.get(order.product_id)
        if product is None:
            add("HC-01", f"订单 {order.order_no} 的产品 {order.product_name} 不在产品主数据中", order.order_no)
        elif not (product.route or []):
            add("HC-01", f"产品 {product.name} 缺少工艺路线定义", product.name)

    # ---------------- HC-05 / HC-12：订单内工艺链顺序 + 转运间隔
    groups: dict[int, list[Any]] = {}
    for item in items:
        groups.setdefault(int(_attr(item, "order_id")), []).append(item)
    calendar = active_calendar()

    for order_id, group in groups.items():
        group.sort(key=lambda x: int(_attr(x, "seq")))
        seqs = [int(_attr(x, "seq")) for x in group]
        if seqs != list(range(1, len(seqs) + 1)):
            add("HC-05", f"订单 {_attr(group[0], 'order_no')} 工艺路线不连续", str(order_id))
        for idx in range(1, len(group)):
            prev, cur = group[idx - 1], group[idx]
            prev_end = _attr(prev, "end")
            cur_start = _attr(cur, "start")
            gap = int(_attr(cur, "transfer_minutes", 0) or 0)
            if prev_end and cur_start and cur_start < prev_end + timedelta(minutes=gap):
                add(
                    "HC-12",
                    f"{_attr(cur, 'order_no')} 工序 {_attr(cur, 'seq')} 早于前序完工 + 转运 {gap}min",
                    str(_attr(cur, "operation_id")),
                )

    # ---------------- HC-04 / HC-12：显式工序依赖图谱（含跨订单、外协前置）
    pred_ids = {o.predecessor_id for o in op_map.values() if o.predecessor_id}
    registry = dict(op_map)
    if pred_ids:
        for extra in db.query(Operation).filter(Operation.id.in_(pred_ids)).all():
            registry.setdefault(extra.id, extra)
    item_by_op = {int(_attr(i, "operation_id")): i for i in items if _attr(i, "operation_id")}
    for item in items:
        op = registry.get(int(_attr(item, "operation_id"))) if _attr(item, "operation_id") else None
        if op is None:
            continue
        label = f"{_attr(item, 'order_no')} #{_attr(item, 'seq')} {_attr(item, 'name')}"
        problem, predecessor = _dependency_state(op, registry)
        if problem:
            add("HC-04", f"{label} {problem}", label)
            continue
        if predecessor is None:
            continue
        pred_item = item_by_op.get(predecessor.id)
        pred_end = _attr(pred_item, "end") if pred_item is not None else predecessor.planned_end
        if pred_end is None:
            add("HC-04", f"{label} 的前置工序尚无计划完工时间", label)
            continue
        lag = float(op.lag_minutes or 0)
        cur_start = _attr(item, "start")
        if cur_start and cur_start < pred_end + timedelta(minutes=lag):
            add(
                "HC-12",
                f"{label} 早于前置工序 #{predecessor.seq} 完工 + 间隔 {lag:.0f}min",
                label,
            )

    # ---------------- 逐工序校验
    intervals_by_resource: dict[int, list[tuple[datetime, datetime]]] = {}
    for item in items:
        label = f"{_attr(item, 'order_no')} #{_attr(item, 'seq')} {_attr(item, 'name')}"
        start: datetime | None = _attr(item, "start")
        end: datetime | None = _attr(item, "end")
        resource_id = _attr(item, "resource_id")
        resource = resource_map.get(int(resource_id)) if resource_id else None
        if not _attr(item, "order_no") or not _attr(item, "name") or not resource:
            add("HC-02", f"{label} 必填字段缺失", label)
        if _attr(item, "operation_id") and int(_attr(item, "operation_id")) not in op_map:
            add("HC-04", f"{label} 指向的工序实例不存在", label)
        if not start or not end:
            add("HC-02", f"{label} 缺少计划起止时间", label)
            continue
        duration = _attr(item, "duration_minutes") or (end - start).total_seconds() / 60
        if duration < 5 or duration > 48 * 60:
            add("HC-06", f"{label} 计划时长 {duration:.0f}min 超出值域", label)
        if resource:
            if resource.capacity_hours is None or not 0 < float(resource.capacity_hours) <= 168:
                add("HC-06", f"{label} 资源 {resource.name} 产能参数超出值域", label)
            if resource.efficiency is None or not 0 < float(resource.efficiency) <= 2:
                add("HC-06", f"{label} 资源 {resource.name} 效率参数超出值域", label)
        op = op_map.get(int(_attr(item, "operation_id"))) if _attr(item, "operation_id") else None
        if op and duration < op.std_minutes * 0.8:
            add("HC-07", f"{label} 计划工时与标准工时偏差超 20%", label)
        if not calendar.contains(start):
            add("HC-08", f"{label} 起始时间落在非工作班次", label)
        else:
            try:
                expected_end = calendar.add_minutes(start, duration)
            except CalendarHorizonError:
                add("HC-08", f"{label} 工时在日历跨度内无法完成（检查停产窗口）", label)
            else:
                if abs(expected_end - end).total_seconds() > 120:
                    add("HC-08", f"{label} 起止时间与工作日历换算的工时不一致", label)
        if resource and _attr(item, "domain") != resource.domain:
            add("HC-09", f"{label} 资源 {resource.name} 能力域不匹配", label)
        if resource and float(resource.efficiency or 1) < 0.6:
            add("HC-13", f"{label} 资源技能覆盖不足", label)
        priority = _attr(item, "priority")
        if priority and priority not in PRIORITIES:
            add("HC-03", f"{label} 优先级取值非法", label)
        risk = _attr(item, "risk")
        if risk and risk not in RISKS:
            add("HC-11", f"{label} 风险等级取值非法", label)
        intervals_by_resource.setdefault(int(resource_id), []).append((start, end))

    # ---------------- HC-03 订单状态值域
    for order in order_map.values():
        if order.status not in ORDER_STATUS:
            add("HC-03", f"订单 {order.order_no} 状态 {order.status} 不在受控值域", order.order_no)

    # ---------------- HC-09 并行机位上限（区间重叠实算）
    for rid, spans in intervals_by_resource.items():
        resource = resource_map.get(rid)
        if not resource:
            continue
        limit = max(1, int(resource.machine_count or 1))
        peak = _max_concurrent(spans)
        if peak > limit:
            add("HC-09", f"资源 {resource.name} 同时占用 {peak} 个机位，超出并行上限 {limit}", resource.code)

    for gap in unassigned or []:
        add(
            "HC-09",
            f"{gap.get('order_no')} #{gap.get('seq')} {gap.get('name')} 无法排入：{gap.get('reason')}",
            str(gap.get("order_no")),
        )

    # ---------------- HC-14 数量平衡
    for order in order_map.values():
        if not order.qty or int(order.qty) <= 0:
            add("HC-14", f"订单 {order.order_no} 数量 {order.qty} 非法", order.order_no)
        progress = int(order.progress or 0)
        if progress < 0 or progress > 100:
            add("HC-14", f"订单 {order.order_no} 进度 {progress}% 越界（负库存/超额产出）", order.order_no)
    completed_ids = [o.id for o in order_map.values() if o.status == "已完工"]
    if completed_ids:
        unfinished = (
            db.query(Operation.order_id, func.count(Operation.id))
            .filter(Operation.order_id.in_(completed_ids), Operation.status != "已完工")
            .group_by(Operation.order_id)
            .all()
        )
        for order_id, count in unfinished:
            order = order_map.get(order_id)
            add(
                "HC-14",
                f"订单 {order.order_no if order else order_id} 已标记完工但仍有 {count} 道工序未完工",
                order.order_no if order else str(order_id),
            )

    # ---------------- HC-10：人员资质覆盖度——只有拿到 C4 技能矩阵才实算
    qualifications = [q for q in db.query(Qualification).all() if q.active]
    clock = datetime.now()
    if qualifications:
        for item in items:
            op = registry.get(int(_attr(item, "operation_id"))) if _attr(item, "operation_id") else None
            wanted = (op.resource_type or op.domain) if op else None
            if not wanted:
                continue
            covered = any(
                q.capability == wanted and (q.valid_until is None or q.valid_until > clock)
                for q in qualifications
            )
            if not covered:
                label = f"{_attr(item, 'order_no')} #{_attr(item, 'seq')} {_attr(item, 'name')}"
                add("HC-10", f"{label} 要求能力「{wanted}」，无有效期内持证人员", label)

    unevaluated_map = dict(UNEVALUATED_CHECKS)
    if qualifications:
        unevaluated_map.pop("HC-10", None)

    checks = []
    unevaluated = []
    for code, title, description in HARD_CONSTRAINTS:
        reason = unevaluated_map.get(code)
        if reason:
            unevaluated.append({"code": code, "title": title, "reason": reason})
            checks.append(
                {
                    "code": code,
                    "title": title,
                    "description": description,
                    "passed": False,
                    "count": 0,
                    "samples": [],
                    "evaluated": False,
                    "message": reason,
                }
            )
            continue
        issue = issues.get(code)
        checks.append(
            {
                "code": code,
                "title": title,
                "description": description,
                "passed": issue is None,
                "count": issue["count"] if issue else 0,
                "samples": issue["samples"] if issue else [],
                "evaluated": True,
                "message": "" if issue is None else issue["samples"][0]["message"],
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

    hard_count = sum(c["count"] for c in checks if c.get("evaluated", True) and not c["passed"])
    return {
        "passed": hard_count == 0,
        "hard_count": hard_count,
        "hard_failed": sum(1 for c in checks if c.get("evaluated", True) and not c["passed"]),
        "soft_count": sum(s["count"] for s in soft),
        "checks": checks,
        "soft": soft,
        "unevaluated": unevaluated,
        "evaluated_at": datetime.now().replace(microsecond=0).isoformat(),
        "engine": "LISA 硬约束校验（逐条实算；SHACL 通道未实现）",
        "rule_version": "ZD-01-2026",
        "constraint_version": "HC-01~14 / SC-01~13",
    }


def increment_rule_hits(db: Session, codes: list[str]) -> None:
    if not codes:
        return
    db.query(Rule).filter(Rule.code.in_(codes)).update({Rule.hits: Rule.hits + 1}, synchronize_session=False)
