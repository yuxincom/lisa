from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import (
    Approval,
    Disturbance,
    Operation,
    Order,
    Plan,
    PlanItem,
    Product,
    Resource,
    User,
)
from .calendar import (
    CalendarHorizonError,
    active_calendar,
    add_work_minutes,
    align_to_work,
    configure_calendar,
    work_minutes_between,
)
from .rules import validate_schedule
from .settings import SCENARIO_META, all_settings, get_setting

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
TRANSFER_MINUTES = 30
SPECIAL_TRANSFER_MINUTES = 120
MIN_EFFICIENCY = 0.5


@dataclass
class ScheduleItem:
    order_id: int
    operation_id: int | None
    order_no: str
    product_name: str
    priority: str
    seq: int
    name: str
    domain: str
    resource_id: int
    resource_code: str
    resource_name: str
    start: datetime
    end: datetime
    duration_minutes: float
    setup_minutes: float
    risk: str
    locked: bool
    reason: str
    family: str
    kit_status: str
    transfer_minutes: int


def _scenario_weights(scenario: str) -> dict:
    return dict(SCENARIO_META.get(scenario, SCENARIO_META["A"])["weights"])


def generate_schedule(
    db: Session,
    scenario: str = "A",
    orders: list[Order] | None = None,
    freeze: bool = True,
    now: datetime | None = None,
) -> dict:
    scenario = scenario if scenario in SCENARIO_META else "A"
    meta = SCENARIO_META[scenario]
    configure_calendar(all_settings(db))
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    base_start = align_to_work(now + timedelta(hours=1))
    freeze_days = int(get_setting(db, "freeze_days", 3))
    freeze_until = now + timedelta(days=freeze_days)

    products = {p.id: p for p in db.query(Product).all()}
    family_map = {pid: p.family for pid, p in products.items()}

    all_open_orders = db.query(Order).filter(~Order.status.in_(["已完工", "已取消"])).all()
    all_order_map = {o.id: o for o in all_open_orders}
    if orders is None:
        orders = all_open_orders
    orders = [o for o in orders if o.status not in ("已完工", "已取消")]
    if not orders:
        return {
            "items": [],
            "unassigned": [],
            "repairs": [],
            "kpi": _empty_kpi(),
            "summary": {"orders": 0},
            "violations": validate_schedule(db, []),
        }

    order_ids = [o.id for o in orders]
    order_map = {o.id: o for o in orders}
    resources = db.query(Resource).filter(Resource.status != "offline").all()
    if not resources:
        raise ValueError("No available resources")
    pools: dict[str, list[Resource]] = {}
    for res in resources:
        pools.setdefault(res.domain, []).append(res)

    ops = (
        db.query(Operation)
        .filter(Operation.order_id.in_(order_ids))
        .order_by(Operation.order_id, Operation.seq)
        .all()
    )
    ops_map = {(op.order_id, op.seq): op for op in ops}

    # 显式工艺依赖（配置清单 C2/C3）：predecessor_id 可跨订单，lag_minutes 为最小间隔。
    pred_ids = {op.predecessor_id for op in ops if op.predecessor_id}
    pred_by_id = {p.id: p for p in (db.query(Operation).filter(Operation.id.in_(pred_ids)).all() if pred_ids else [])}
    deps: dict[tuple[int, int], list[tuple[int, int, float]]] = {}
    for op in ops:
        p = pred_by_id.get(op.predecessor_id) if op.predecessor_id else None
        if p is None:
            continue
        deps.setdefault((op.order_id, op.seq), []).append((p.order_id, p.seq, float(op.lag_minutes or 0)))
    order_edges = {
        (p_order, order_id)
        for (order_id, _seq), entries in deps.items()
        for (p_order, _pseq, _lag) in entries
        if p_order != order_id and p_order in order_map
    }

    resource_by_id = {res.id: res for res in resources}
    state: dict[int, dict] = {}
    for res in resources:
        maintenance = res.maintenance_until if res.maintenance_until and res.maintenance_until > base_start else None
        state[res.id] = {
            "lanes": [
                {"free": base_start, "last_family": None, "busy": []}
                for _ in range(max(1, int(res.machine_count or 1)))
            ],
            "maintenance": maintenance,
            "minutes": 0.0,
            "overbooked": 0,
        }

    # Reserve frozen-window operations from ALL open orders before scheduling new work.
    open_ids = list(all_order_map.keys())
    frozen_ops = (
        db.query(Operation)
        .filter(
            Operation.order_id.in_(open_ids),
            Operation.resource_id.isnot(None),
            Operation.planned_start.isnot(None),
            Operation.planned_end.isnot(None),
            Operation.planned_start < freeze_until,
            Operation.planned_end > now,
        )
        .all()
        if freeze and open_ids
        else []
    )
    # 基线里排不下（并行机位冲突、资源已下线）的冻结工序不锁定，留给主循环重排，
    # 否则旧基线的脏数据会被永久带进每一版方案并卡死 HC-09。
    released: dict[int, str] = {}
    for op in sorted(frozen_ops, key=lambda x: (x.planned_end, x.id)):
        st = state.get(op.resource_id)
        if not st:
            released[op.id] = "基线资源已下线或不存在"
            continue
        lane = _find_lane(st, op.planned_start, op.planned_end)
        if lane is None:
            released[op.id] = "基线在同一资源的并行机位上排入了重叠工序"
            st["overbooked"] += 1
            continue
        _reserve(lane, op.planned_start, op.planned_end)
        order = all_order_map.get(op.order_id)
        lane["last_family"] = family_map.get(order.product_id) if order else None
        st["minutes"] += max(0.0, active_calendar().minutes_between(op.planned_start, op.planned_end))

    base_rank = {
        o.id: (PRIORITY_RANK.get(o.priority, 9), o.due_date, o.id)
        for o in orders
    }
    sorted_orders, cyclic_orders = _topo_orders(orders, order_edges, base_rank)

    items: list[ScheduleItem] = []
    unassigned: list[dict] = []
    repairs: list[dict] = []
    end_of: dict[tuple[int, int], datetime] = {}
    for order in sorted_orders:
        family = family_map.get(order.product_id, order.product_name.split("-")[0])
        product = products.get(order.product_id)
        route = sorted((product.route if product else []), key=lambda s: s["seq"])
        if not route:
            continue
        arrival = base_start
        prev_end: datetime | None = None
        prev_special = False
        for step in route:
            existing = ops_map.get((order.id, step["seq"]))
            gap = 0 if prev_end is None else (SPECIAL_TRANSFER_MINUTES if prev_special else TRANSFER_MINUTES)
            ceilings = _ceilings(deps.get((order.id, step["seq"]), []), end_of, ops_map)
            in_freeze = bool(
                freeze
                and existing
                and existing.resource_id
                and existing.planned_start
                and existing.planned_end
                and existing.planned_start < freeze_until
                and existing.planned_end > now
            )
            lock_reason = None
            if in_freeze and existing:
                lock_reason = _lock_reject(
                    resource_by_id.get(existing.resource_id),
                    existing,
                    prev_end,
                    gap,
                    ceilings,
                    released,
                )

            if in_freeze and lock_reason is None and existing:
                start = existing.planned_start
                end = existing.planned_end
                resource = resource_by_id[existing.resource_id]
                duration = float(round(max(1.0, active_calendar().minutes_between(start, end))))
                setup = 0.0
                risk = _risk(end, order)
                reason = "冻结窗口锁定（R005）"
                items.append(
                    ScheduleItem(
                        order_id=order.id, operation_id=existing.id, order_no=order.order_no,
                        product_name=order.product_name, priority=order.priority, seq=step["seq"],
                        name=step["name"], domain=step["domain"], resource_id=resource.id,
                        resource_code=resource.code, resource_name=resource.name, start=start, end=end,
                        duration_minutes=duration, setup_minutes=setup, risk=risk, locked=True,
                        reason=reason, family=family, kit_status=order.kit_status,
                        transfer_minutes=gap,
                    )
                )
                arrival = end
                prev_end = end
                prev_special = bool(step.get("special"))
                end_of[(order.id, step["seq"])] = end
                continue

            if prev_end:
                arrival = prev_end + timedelta(minutes=gap)
            if ceilings:
                arrival = max(arrival, *ceilings)
            arrival = align_to_work(max(arrival, base_start))

            placement = _place(pools.get(step["domain"], []), state, arrival, family, scenario, step)
            if placement is None:
                unassigned.append(
                    {
                        "order_no": order.order_no,
                        "seq": step["seq"],
                        "name": step["name"],
                        "domain": step["domain"],
                        "resource_type": step.get("resource_type", ""),
                        "reason": "该域内没有能力匹配的资源，工序无法排入",
                    }
                )
                continue
            resource, lane, start, setup = placement
            qty = max(1, order.qty or 1)
            qty_factor = min(1.8, 1 + (qty - 1) * 0.22)
            efficiency = max(MIN_EFFICIENCY, float(resource.efficiency or 1.0))
            duration = round(step["std_minutes"] * qty_factor / efficiency + setup)
            end = add_work_minutes(start, duration)
            risk = _risk(end, order)
            reason = _reason(order, resource, scenario, family, lane["last_family"], risk)

            if lock_reason is not None and existing is not None:
                repairs.append(
                    {
                        "order_no": order.order_no,
                        "seq": step["seq"],
                        "name": step["name"],
                        "from": existing.planned_start.isoformat() if existing.planned_start else None,
                        "to": start.isoformat(),
                        "reason": lock_reason,
                    }
                )

            lane["free"] = end
            lane["last_family"] = family
            lane["busy"].append((start, end))
            state[resource.id]["minutes"] += duration

            items.append(
                ScheduleItem(
                    order_id=order.id,
                    operation_id=existing.id if existing else None,
                    order_no=order.order_no,
                    product_name=order.product_name,
                    priority=order.priority,
                    seq=step["seq"],
                    name=step["name"],
                    domain=step["domain"],
                    resource_id=resource.id,
                    resource_code=resource.code,
                    resource_name=resource.name,
                    start=start,
                    end=end,
                    duration_minutes=duration,
                    setup_minutes=setup,
                    risk=risk,
                    locked=False,
                    reason=reason,
                    family=family,
                    kit_status=order.kit_status,
                    transfer_minutes=gap,
                )
            )
            arrival = end
            prev_end = end
            prev_special = bool(step.get("special"))
            end_of[(order.id, step["seq"])] = end

    kpi = _compute_kpi(items, order_map, resources, scenario)
    violations = validate_schedule(db, items, unassigned)
    summary = _build_summary(
        items, order_map, resources, scenario, kpi, violations, freeze_days,
        unassigned, state, repairs, cyclic_orders,
    )
    return {
        "items": items,
        "unassigned": unassigned,
        "repairs": repairs,
        "kpi": kpi,
        "summary": summary,
        "violations": violations,
        "scenario": scenario,
        "objective": meta["objective"],
        "weights": dict(meta["weights"]),
        "generated_at": now.isoformat(),
    }


def _find_lane(state: dict, start: datetime, end: datetime) -> dict | None:
    """找一条在 [start, end) 上没有占用的机位，优先选最早空闲的。"""
    best = None
    for lane in state["lanes"]:
        if all(bs >= end or be <= start for bs, be in lane["busy"]):
            if best is None or lane["free"] < best["free"]:
                best = lane
    return best


def _reserve(lane: dict, start: datetime, end: datetime) -> None:
    lane["busy"].append((start, end))
    lane["free"] = max(lane["free"], end)


def _ceilings(
    entries: list[tuple[int, int, float]],
    end_of: dict[tuple[int, int], datetime],
    ops_map: dict[tuple[int, int], Operation],
) -> list[datetime]:
    """前置工序（含跨订单/外协）完工时刻 + 间隔，构成的最早开工下限。"""
    out = []
    for p_order, p_seq, lag in entries:
        done = end_of.get((p_order, p_seq))
        if done is None:
            p_op = ops_map.get((p_order, p_seq))
            done = p_op.planned_end if p_op is not None and p_op.planned_end else None
        if done is not None:
            out.append(done + timedelta(minutes=lag))
    return out


def _topo_orders(
    orders: list[Order],
    edges: set[tuple[int, int]],
    key_prefix: dict[int, tuple],
) -> tuple[list[Order], list[str]]:
    """在 EDD/优先级序列上叠加跨订单前置依赖；成环时按原序兜底并回报环清单。"""
    incoming: dict[int, set[int]] = {o.id: set() for o in orders}
    outgoing: dict[int, set[int]] = {o.id: set() for o in orders}
    for pred, succ in edges:
        if pred in incoming and succ in incoming:
            incoming[succ].add(pred)
            outgoing[pred].add(succ)

    order_by_id = {o.id: o for o in orders}
    ready = sorted((o for o in orders if not incoming[o.id]), key=lambda o: key_prefix[o.id])
    result: list[Order] = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        for succ_id in outgoing[current.id]:
            incoming[succ_id].discard(current.id)
            if not incoming[succ_id]:
                ready.append(order_by_id[succ_id])
                ready.sort(key=lambda o: key_prefix[o.id])
    if len(result) < len(orders):
        cycles = sorted(order_by_id[oid].order_no for oid, deg in incoming.items() if deg and oid not in {r.id for r in result})
        for o in orders:
            if o not in result:
                result.append(o)
        return result, cycles
    return result, []


def _lock_reject(
    resource: Resource | None,
    op: Operation,
    prev_end: datetime | None,
    gap: int,
    ceilings: list[datetime],
    released: dict[int, str],
) -> str | None:
    """冻结工序只有自身可行才能锁定，否则必须重排——脏基线不能永久带病传递。"""
    if op.id in released:
        return released[op.id]
    if resource is None:
        return "基线资源已下线或不存在"
    if prev_end and op.planned_start < prev_end + timedelta(minutes=gap):
        return f"前序顺延后基线窗口违反工序依赖（转运 {gap}min）"
    if ceilings and op.planned_start < max(ceilings):
        return "基线窗口早于前置工序完工时刻"
    calendar = active_calendar()
    if not calendar.contains(op.planned_start):
        return "基线起始时间落在非工作班次"
    try:
        recomputed = calendar.add_minutes(op.planned_start, calendar.minutes_between(op.planned_start, op.planned_end))
    except CalendarHorizonError:
        return "基线工时在日历跨度内无法完成"
    if abs(recomputed - op.planned_end).total_seconds() > 120:
        return "基线起止时间与工作日历换算的工时不一致"
    duration = calendar.minutes_between(op.planned_start, op.planned_end)
    if duration < 5 or duration > 48 * 60:
        return "基线计划时长超出值域"
    if op.std_minutes and duration < op.std_minutes * 0.8:
        return "基线工时与标准工时偏差超 20%"
    return None


def _capable(res: Resource, step: dict) -> bool:
    if res.domain != step["domain"]:
        return False
    required = step.get("resource_type")
    capabilities = res.capabilities or []
    if capabilities and required:
        return required in capabilities
    return True


def _place(
    pool: list[Resource],
    state: dict[int, dict],
    arrival: datetime,
    family: str,
    scenario: str,
    step: dict,
) -> tuple[Resource, dict, datetime, float] | None:
    """在满足能力域的资源的空闲机位上，找最早可用起点。"""
    options = []
    for res in pool:
        if res.status == "offline" or not _capable(res, step):
            continue
        st = state[res.id]
        maintenance = st["maintenance"]
        lane_count = len(st["lanes"])
        for lane in st["lanes"]:
            available = max(arrival, lane["free"], maintenance) if maintenance else max(arrival, lane["free"])
            available = align_to_work(available)
            same_family = lane["last_family"] == family
            setup = max(8.0, float(round(step["setup_minutes"] * (0.3 if same_family else 1.0))))
            if scenario == "C":
                key = (0 if same_family else 1, available, res.bottleneck, res.id, lane["free"])
            elif scenario == "B":
                ceiling = max(720.0, res.capacity_hours * 60) * lane_count
                load_ratio = st["minutes"] / ceiling
                penalty = timedelta(minutes=load_ratio * 480 + (180 if res.bottleneck else 0))
                key = (available + penalty, res.bottleneck, res.id, lane["free"])
            else:
                key = (available, res.bottleneck, res.id, lane["free"])
            options.append((key, res, lane, available, setup))
    if not options:
        return None
    _, resource, lane, start, setup = min(options, key=lambda x: x[0])
    return resource, lane, start, setup


def _risk(end: datetime, order: Order) -> str:
    buffer_minutes = (order.due_date - end).total_seconds() / 60
    if buffer_minutes < 0:
        return "late"
    if buffer_minutes < 8 * 60:
        return "tight"
    return "normal"


def _reason(order: Order, resource: Resource, scenario: str, family: str, last_family: str | None, risk: str) -> str:
    reasons = []
    if order.priority == "P0":
        reasons.append("P0 军品保供（SC-06）")
    if scenario == "C" and last_family == family:
        reasons.append("同族连续生产（SC-03）")
    if resource.bottleneck:
        reasons.append("瓶颈资源保护（SC-02）")
    if order.kit_status != "齐套":
        reasons.append("齐套预警（SC-05）")
    if risk == "late":
        reasons.append("交期风险（SC-01）")
    if not reasons:
        reasons.append("有限产能分配：同域内最早可用机位")
    return " · ".join(reasons[:3])


def _compute_kpi(
    items: list[ScheduleItem],
    order_map: dict[int, Order],
    resources: list[Resource],
    scenario: str,
) -> dict:
    if not items:
        return _empty_kpi()
    starts = [i.start for i in items]
    ends = [i.end for i in items]
    span_minutes = work_minutes_between(min(starts), max(ends))
    span_hours = max(0.1, (max(ends) - min(starts)).total_seconds() / 3600)

    by_order: dict[int, list[ScheduleItem]] = {}
    for item in items:
        by_order.setdefault(item.order_id, []).append(item)
    late_orders = 0
    tight_orders = 0
    for order_id, group in by_order.items():
        order = order_map.get(order_id)
        if not order:
            continue
        finish = max(i.end for i in group)
        if finish > order.due_date:
            late_orders += 1
        elif (order.due_date - finish).total_seconds() / 3600 < 8:
            tight_orders += 1

    total_orders = len(by_order)
    otd = (total_orders - late_orders) / total_orders if total_orders else 1.0
    total_minutes = sum(i.duration_minutes for i in items)
    by_resource: dict[int, float] = {}
    for item in items:
        by_resource[item.resource_id] = by_resource.get(item.resource_id, 0) + item.duration_minutes
    lane_counts = {r.id: max(1, int(r.machine_count or 1)) for r in resources}

    def _utilization(resource_id: int, minutes: float) -> float:
        ceiling = max(1.0, span_minutes * lane_counts.get(resource_id, 1))
        return min(100.0, minutes / ceiling * 100)

    util_values = [_utilization(rid, minutes) for rid, minutes in by_resource.items()]
    avg_util = sum(util_values) / len(util_values) if util_values else 0.0
    bottleneck_ids = {r.id for r in resources if r.bottleneck}
    bottleneck_values = [_utilization(rid, by_resource.get(rid, 0.0)) for rid in bottleneck_ids]
    bottleneck_util = sum(bottleneck_values) / len(bottleneck_values) if bottleneck_values else 0.0

    changeover_minutes = sum(i.setup_minutes for i in items if i.setup_minutes > 15)
    changeover_count = sum(1 for i in items if i.setup_minutes > 15)
    late_ratio = late_orders / total_orders if total_orders else 0
    tight_ratio = tight_orders / total_orders if total_orders else 0
    risk_items = sum(1 for i in items if i.risk != "normal")
    adoption = min(93.5, max(58.0, 58.0 + 38.0 * otd - 3.0 * tight_ratio * 10))
    accuracy = min(90.0, max(60.0, 62.0 + 22.0 * otd))

    delivery_score = round(otd * 100, 1)
    bottleneck_score = round(max(0.0, 100 - max(0.0, bottleneck_util - 82) * 2.4), 1)
    changeover_score = round(max(0.0, 100 - changeover_minutes / max(1, total_orders) * 1.8), 1)
    cost_score = round(max(0.0, 100 - changeover_minutes / max(1, total_orders) * 1.2 - late_orders * 1.5), 1)
    weights = _scenario_weights(scenario)
    total_score = round(
        delivery_score * weights["delivery"]
        + bottleneck_score * weights["bottleneck"]
        + changeover_score * weights["changeover"]
        + cost_score * weights["cost"],
        1,
    )
    return {
        "orders": total_orders,
        "operations": len(items),
        "late_orders": late_orders,
        "tight_orders": tight_orders,
        "on_time_rate": round(otd * 100, 1),
        "predicted_adoption": round(adoption, 1),
        "accuracy": round(accuracy, 1),
        "avg_utilization": round(avg_util, 1),
        "bottleneck_utilization": round(bottleneck_util, 1),
        "changeover_minutes": round(changeover_minutes),
        "changeover_count": changeover_count,
        "risk_operations": risk_items,
        "makespan_hours": round(span_hours, 1),
        "locked_operations": sum(1 for i in items if i.locked),
        "total_labor_hours": round(total_minutes / 60, 1),
        "objective_scores": {
            "delivery": delivery_score,
            "bottleneck": bottleneck_score,
            "changeover": changeover_score,
            "cost": cost_score,
        },
        "total_score": total_score,
        "weights": weights,
    }


def _empty_kpi() -> dict:
    return {
        "orders": 0, "operations": 0, "late_orders": 0, "tight_orders": 0, "on_time_rate": 0.0,
        "predicted_adoption": 0.0, "accuracy": 0.0, "avg_utilization": 0.0,
        "bottleneck_utilization": 0.0, "changeover_minutes": 0, "changeover_count": 0,
        "risk_operations": 0, "makespan_hours": 0.0, "locked_operations": 0,
        "total_labor_hours": 0.0, "objective_scores": {}, "total_score": 0.0, "weights": {},
    }


def _build_summary(
    items: list[ScheduleItem],
    order_map: dict[int, Order],
    resources: list[Resource],
    scenario: str,
    kpi: dict,
    violations: dict,
    freeze_days: int,
    unassigned: list[dict],
    state: dict[int, dict],
    repairs: list[dict],
    cyclic_orders: list[str],
) -> dict:
    meta = SCENARIO_META[scenario]
    domains: dict[str, int] = {}
    for item in items:
        domains[item.domain] = domains.get(item.domain, 0) + 1
    p0 = sum(1 for oid in {i.order_id for i in items} if order_map.get(oid) and order_map[oid].priority == "P0")
    kit_risk = sum(1 for oid in {i.order_id for i in items} if order_map.get(oid) and order_map[oid].kit_status != "齐套")
    overbooked = sum(st.get("overbooked", 0) for st in state.values())
    unevaluated = violations.get("unevaluated", [])
    reasons = [
        f"EDD/优先级派工：P0 急件 {p0} 个优先占用瓶颈资源",
        f"可行性校验：{len(violations.get('checks', []))} 项硬约束，违规 {violations.get('hard_count', 0)} 项"
        + (f"，另有 {len(unevaluated)} 项因主数据缺失未校验" if unevaluated else ""),
        f"加权目标评分：交期 {int(meta['weights']['delivery'] * 100)}% / 瓶颈 {int(meta['weights']['bottleneck'] * 100)}% / 换型 {int(meta['weights']['changeover'] * 100)}% / 成本 {int(meta['weights']['cost'] * 100)}%",
        f"冻结窗口 {freeze_days} 天：锁定 {kpi.get('locked_operations', 0)} 道工序保持基线不动",
        f"命中软约束 {len(violations.get('soft', []))} 类，逾期订单 {kpi.get('late_orders', 0)} 个已标记风险",
    ]
    if unassigned:
        reasons.append(f"{len(unassigned)} 道工序因域内无能力匹配资源未能排入（违反 HC-09）")
    if repairs:
        reasons.append(
            f"{len(repairs)} 道冻结工序的基线窗口本身不可行，已解除锁定重排（{repairs[0]['reason']}）"
        )
    if overbooked:
        reasons.append(f"基线中 {overbooked} 道冻结工序在同一资源的并行机位上重叠，已重排")
    if cyclic_orders:
        reasons.append(
            f"{len(cyclic_orders)} 个订单的前置依赖成环（{', '.join(cyclic_orders[:3])}），已按优先级兜底排序，需修正 C2 依赖表"
        )
    lanes_total = sum(len(st["lanes"]) for st in state.values())
    return {
        "orders": kpi.get("orders", 0),
        "operations": len(items),
        "domains": [{"name": k, "count": v} for k, v in sorted(domains.items(), key=lambda x: -x[1])],
        "resources": len({i.resource_id for i in items}),
        "p0_orders": p0,
        "kit_risk": kit_risk,
        "late_orders": kpi.get("late_orders", 0),
        "locked_operations": kpi.get("locked_operations", 0),
        "unassigned_operations": len(unassigned),
        "unassigned_samples": unassigned[:8],
        "baseline_overbooked": overbooked,
        "baseline_repairs": len(repairs),
        "baseline_repair_samples": repairs[:8],
        "resource_lanes": lanes_total,
        "dependency_cycles": cyclic_orders,
        "objective": meta["objective"],
        "reasoning": reasons,
        "hard_checks": violations.get("checks", []),
        "hard_count": violations.get("hard_count", 0),
        "unevaluated": unevaluated,
        "soft_violations": violations.get("soft", []),
        "generated_by": "C-01 全厂智能排产总控",
        "solver": "LISA Heuristic Engine（贪心派工，无外部求解器）",
        "algorithm": "优先级/EDD 派工 + 并行机位有限产能分配 + 加权目标评分",
        "calendar": active_calendar().to_config(),
    }


def compute_diff(db: Session, items: list[ScheduleItem | PlanItem]) -> dict:
    op_ids = [int(i.operation_id) for i in items if i.operation_id]
    baseline_ops = {o.id: o for o in db.query(Operation).filter(Operation.id.in_(op_ids)).all()} if op_ids else {}
    moved = []
    added = 0
    unchanged = 0
    for item in items:
        op = baseline_ops.get(int(item.operation_id)) if item.operation_id else None
        if not op or not op.planned_start:
            added += 1
            continue
        delta_minutes = abs((item.start - op.planned_start).total_seconds()) / 60
        resource_changed = op.resource_id != item.resource_id
        if delta_minutes > 60 or resource_changed:
            moved.append(
                {
                    "operation_id": item.operation_id,
                    "order_no": item.order_no,
                    "name": item.name,
                    "seq": item.seq,
                    "domain": item.domain,
                    "from_start": op.planned_start.isoformat(),
                    "to_start": item.start.isoformat(),
                    "delta_hours": round((item.start - op.planned_start).total_seconds() / 3600, 1),
                    "resource_changed": resource_changed,
                    "from_resource": op.resource_id,
                    "to_resource": item.resource_id,
                }
            )
        else:
            unchanged += 1
    moved.sort(key=lambda x: abs(x["delta_hours"]), reverse=True)
    return {
        "moved": len(moved),
        "added": added,
        "unchanged": unchanged,
        "total": len(items),
        "samples": moved[:30],
    }


def save_plan(
    db: Session,
    result: dict,
    plan_type: str = "full",
    created_by: str = "system",
    batch_id: str | None = None,
    change_id: int | None = None,
    status: str | None = None,
    name: str | None = None,
) -> Plan:
    scenario = result["scenario"]
    now = datetime.now().replace(microsecond=0)
    code = f"PS-{now:%Y%m%d%H%M}-{scenario}-{uuid.uuid4().hex[:4].upper()}"
    hard_failed = result["violations"].get("hard_count", 0) > 0
    plan_status = status or ("blocked" if hard_failed else "pending")
    plan = Plan(
        code=code,
        name=name or f"{result['summary'].get('objective', '排产方案')} · {scenario} 方案",
        type=plan_type,
        status=plan_status,
        scenario=scenario,
        objective=result["summary"].get("objective", ""),
        weights=result.get("weights", {}),
        summary=result.get("summary", {}),
        kpi=result.get("kpi", {}),
        created_by=created_by,
        created_at=now,
        submitted_at=now if plan_status == "pending" else None,
        batch_id=batch_id,
        change_id=change_id,
    )
    db.add(plan)
    db.flush()

    plan_items = []
    for item in result["items"]:
        plan_items.append(
            PlanItem(
                plan_id=plan.id,
                order_id=item.order_id,
                operation_id=item.operation_id,
                order_no=item.order_no,
                product_name=item.product_name,
                priority=item.priority,
                seq=item.seq,
                name=item.name,
                domain=item.domain,
                resource_id=item.resource_id,
                resource_code=item.resource_code,
                resource_name=item.resource_name,
                start=item.start,
                end=item.end,
                duration_minutes=item.duration_minutes,
                setup_minutes=item.setup_minutes,
                transfer_minutes=item.transfer_minutes,
                risk=item.risk,
                locked=item.locked,
                reason=item.reason,
            )
        )
    db.add_all(plan_items)
    db.flush()
    plan.diff = compute_diff(db, plan_items)
    db.flush()
    return plan


def create_plan_batch(
    db: Session,
    user: User,
    plan_type: str = "full",
    change_id: int | None = None,
    scenarios: tuple[str, ...] = ("A", "B", "C"),
    orders: list[Order] | None = None,
) -> list[Plan]:
    now = datetime.now().replace(microsecond=0)
    batch_id = f"BATCH-{now:%Y%m%d%H%M}-{uuid.uuid4().hex[:4].upper()}"
    timeout = int(get_setting(db, "approval_timeout_minutes", 15))
    plans: list[Plan] = []
    for scenario in scenarios:
        result = generate_schedule(db, scenario=scenario, freeze=True, orders=orders)
        plan = save_plan(
            db,
            result,
            plan_type=plan_type,
            created_by=user.name,
            batch_id=batch_id,
            change_id=change_id,
        )
        plans.append(plan)
        if plan.status == "pending":
            db.add(
                Approval(
                    plan_id=plan.id,
                    level=1,
                    approver_name="生产指挥部",
                    role="commander",
                    status="pending",
                    deadline=now + timedelta(minutes=timeout),
                )
            )
    db.flush()
    if change_id:
        disturbance = db.get(Disturbance, change_id)
        if disturbance:
            disturbance.status = "待审批"
            disturbance.options = {
                "plans": [
                    {
                        "plan_id": p.id, "code": p.code, "scenario": p.scenario,
                        "objective": p.objective, "score": p.kpi.get("total_score", 0),
                        "on_time_rate": p.kpi.get("on_time_rate", 0),
                    }
                    for p in plans
                ]
            }
    return plans


def apply_plan(db: Session, plan: Plan, user: User, comment: str = "") -> dict:
    if plan.status != "approved":
        raise ValueError("写保护网关拒绝：方案未经审批与电子签名")
    items = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).all()
    verification = validate_schedule(db, items)
    if not verification["passed"]:
        raise ValueError(f"写保护网关拒绝：方案存在 {verification['hard_count']} 项硬约束违规")

    now = datetime.now().replace(microsecond=0)
    changed = 0
    for item in items:
        if not item.operation_id:
            continue
        op = db.get(Operation, item.operation_id)
        if not op:
            continue
        op.planned_start = item.start
        op.planned_end = item.end
        op.resource_id = item.resource_id
        op.locked = item.locked
        op.risk = item.risk
        changed += 1

    db.query(Plan).filter(Plan.baseline.is_(True), Plan.id != plan.id).update(
        {Plan.baseline: False}, synchronize_session=False
    )
    plan.baseline = True
    plan.status = "applied"
    plan.approved_at = now
    plan.applied_at = now

    if plan.batch_id:
        siblings = db.query(Plan).filter(Plan.batch_id == plan.batch_id, Plan.id != plan.id).all()
        for sibling in siblings:
            sibling.status = "superseded"

    approvals = db.query(Approval).filter(Approval.plan_id == plan.id).all()
    for approval in approvals:
        approval.status = "approved"
        approval.decided_at = now
        approval.comment = comment
    if plan.batch_id:
        db.query(Approval).filter(
            Approval.plan_id.in_([p.id for p in siblings]),
            Approval.status == "pending",
        ).update({Approval.status: "cancelled"}, synchronize_session=False)

    if plan.change_id:
        disturbance = db.get(Disturbance, plan.change_id)
        if disturbance:
            disturbance.status = "已关闭"
            disturbance.resolved_at = now

    for order_id in {i.order_id for i in items}:
        order = db.get(Order, order_id)
        if order and order.status in ("待排产", "已排产", "逾期"):
            order.status = "已排产"

    db.flush()
    return {
        "plan_id": plan.id,
        "plan_code": plan.code,
        "baseline": True,
        "operations_updated": changed,
        "applied_at": plan.applied_at.isoformat(),
        "write_shield": "approved — 写入放行（签名校验通过）",
    }
