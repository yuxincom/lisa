from __future__ import annotations

"""主数据导入（投产配置清单 A1/A2 产能台账 + C2 工序依赖）。

排产内核读取 resources.machine_count（同型可并行台数）、resources.capabilities（能力标签）
与 operations.predecessor_id / lag_minutes（跨订单前置依赖）。
演示库由 seed 写入，真实投产必须由台账导入——台账是唯一权威来源，导入全程留痕。
"""

from typing import Any

from sqlalchemy.orm import Session

from ..models import Operation, Order, Resource, User
from .audit import log_user_action

MACHINE_MAX = 32
CAPACITY_HOURS_RANGE = (0.5, 24.0)
EFFICIENCY_RANGE = (0.1, 2.0)
TRUE_TOKENS = {"1", "true", "yes", "y", "是"}
FALSE_TOKENS = {"0", "false", "no", "n", "否", ""}


class LedgerError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _number(value: Any, label: str, bounds: tuple[float, float]) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise LedgerError("LEDGER_ROW_INVALID", f"{label} 不是数字：{value!r}")
    if not bounds[0] <= parsed <= bounds[1]:
        raise LedgerError("LEDGER_ROW_INVALID", f"{label} {parsed} 超出 {bounds[0]}~{bounds[1]}")
    return parsed


def _flag(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    raise LedgerError("LEDGER_ROW_INVALID", f"{label} 取值无法识别：{value!r}")


def _capabilities(value: Any, code: str) -> list[str]:
    if isinstance(value, str):
        raw = value.replace("，", "|").replace(",", "|").replace("/", "|").split("|")
    elif isinstance(value, list):
        raw = value
    else:
        raise LedgerError("LEDGER_ROW_INVALID", f"{code} 的能力标签必须是字符串数组或 | 分隔字符串")
    return sorted({str(item).strip() for item in raw if str(item).strip()})


def validate_ledger(rows: list[dict], known_domains: set[str]) -> list[dict]:
    if not rows:
        raise LedgerError("LEDGER_EMPTY", "台账为空，拒绝写入")
    seen: set[str] = set()
    clean: list[dict] = []
    for idx, row in enumerate(rows, start=1):
        code = str(row.get("code") or "").strip()
        if not code:
            raise LedgerError("LEDGER_ROW_INVALID", f"第 {idx} 行缺少资源编码")
        if code in seen:
            raise LedgerError("LEDGER_DUPLICATE", f"资源编码 {code} 重复")
        seen.add(code)
        try:
            lanes = int(row.get("machine_count", 1))
        except (TypeError, ValueError):
            raise LedgerError("LEDGER_ROW_INVALID", f"{code} 的并行台数不是整数")
        if lanes < 1 or lanes > MACHINE_MAX:
            raise LedgerError("LEDGER_ROW_INVALID", f"{code} 的并行台数 {lanes} 超出 1~{MACHINE_MAX}")
        caps = _capabilities(row.get("capabilities") or [], code)
        unknown = [c for c in caps if c not in known_domains]
        if unknown:
            raise LedgerError("LEDGER_DOMAIN_UNKNOWN", f"{code} 引用未知能力域：{', '.join(unknown)}")
        entry: dict[str, Any] = {"code": code, "machine_count": lanes, "capabilities": caps}
        if row.get("capacity_hours") not in (None, ""):
            entry["capacity_hours"] = _number(row["capacity_hours"], f"{code}.capacity_hours", CAPACITY_HOURS_RANGE)
        if row.get("efficiency") not in (None, ""):
            entry["efficiency"] = _number(row["efficiency"], f"{code}.efficiency", EFFICIENCY_RANGE)
        if row.get("bottleneck") not in (None, ""):
            entry["bottleneck"] = _flag(row["bottleneck"], f"{code}.bottleneck")
        clean.append(entry)
    return clean


def apply_machine_ledger(db: Session, rows: list[dict], actor: User) -> dict:
    resources = db.query(Resource).all()
    if not resources:
        raise LedgerError("LEDGER_EMPTY", "资源台账为空，请先初始化主数据")
    known_domains = {r.domain for r in resources}
    clean = validate_ledger(rows, known_domains)
    by_code = {r.code: r for r in resources}

    updated = 0
    unknown: list[str] = []
    for row in clean:
        resource = by_code.get(row["code"])
        if resource is None:
            unknown.append(row["code"])
            continue
        changed = False
        if max(1, int(resource.machine_count or 1)) != row["machine_count"]:
            resource.machine_count = row["machine_count"]
            changed = True
        if row["capabilities"] and sorted(set(resource.capabilities or [])) != row["capabilities"]:
            resource.capabilities = row["capabilities"]
            changed = True
        for field in ("capacity_hours", "efficiency", "bottleneck"):
            if field in row and float(getattr(resource, field) or 0) != float(row[field]):
                setattr(resource, field, row[field])
                changed = True
        if not changed:
            continue
        log_user_action(
            db, actor, "maindata.machine_ledger", "resource", resource.code,
            detail={
                "machine_count": row["machine_count"],
                "capabilities": row["capabilities"],
                "capacity_hours": row.get("capacity_hours"),
                "efficiency": row.get("efficiency"),
                "bottleneck": row.get("bottleneck"),
            },
        )
        updated += 1
    db.flush()
    return {
        "ledger_rows": len(clean),
        "updated": updated,
        "unchanged": len(clean) - updated - len(unknown),
        "unknown_codes": unknown,
        "total_lanes": sum(max(1, int(r.machine_count or 1)) for r in resources),
        "multi_lane_resources": sum(1 for r in resources if int(r.machine_count or 1) > 1),
    }


def validate_dependencies(rows: list[dict]) -> list[dict]:
    if not rows:
        raise LedgerError("LEDGER_EMPTY", "依赖表为空，拒绝写入")
    clean: list[dict] = []
    for idx, row in enumerate(rows, start=1):
        order_no = str(row.get("order_no") or "").strip()
        pred_no = str(row.get("predecessor_order_no") or "").strip()
        if not order_no or not pred_no:
            raise LedgerError("LEDGER_ROW_INVALID", f"第 {idx} 行缺少工单号或前置工单号")
        try:
            seq = int(row.get("seq", 1))
            pred_seq = int(row.get("predecessor_seq", 1))
            lag = float(row.get("lag_minutes", 0) or 0)
        except (TypeError, ValueError):
            raise LedgerError("LEDGER_ROW_INVALID", f"{order_no} 的工序序号或间隔不是数字")
        if seq < 1 or pred_seq < 1:
            raise LedgerError("LEDGER_ROW_INVALID", f"{order_no} 的工序序号必须从 1 开始")
        if lag < 0:
            raise LedgerError("LEDGER_ROW_INVALID", f"{order_no} #{seq} 的间隔不能为负")
        clean.append(
            {
                "order_no": order_no,
                "seq": seq,
                "predecessor_order_no": pred_no,
                "predecessor_seq": pred_seq,
                "lag_minutes": lag,
            }
        )
    return clean


def apply_dependencies(db: Session, rows: list[dict], actor: User) -> dict:
    """把 (order_no, seq) → (predecessor_order_no, predecessor_seq) 邻接表落到工序实例上。"""
    clean = validate_dependencies(rows)
    order_by_no = {o.order_no: o for o in db.query(Order).all()}
    op_by_key = {(o.order_id, o.seq): o for o in db.query(Operation).all()}

    linked = 0
    missing_orders: set[str] = set()
    missing_operations: set[str] = set()
    self_references: set[str] = set()
    for row in clean:
        order = order_by_no.get(row["order_no"])
        pred_order = order_by_no.get(row["predecessor_order_no"])
        if order is None or pred_order is None:
            missing_orders.add(row["order_no"] if order is None else row["predecessor_order_no"])
            continue
        current = op_by_key.get((order.id, row["seq"]))
        predecessor = op_by_key.get((pred_order.id, row["predecessor_seq"]))
        if current is None or predecessor is None:
            missing_operations.add(
                f"{row['order_no']}#{row['seq']}" if current is None else f"{row['predecessor_order_no']}#{row['predecessor_seq']}"
            )
            continue
        if current.id == predecessor.id:
            self_references.add(f"{row['order_no']}#{row['seq']}")
            continue
        if current.predecessor_id == predecessor.id and float(current.lag_minutes or 0) == row["lag_minutes"]:
            continue
        current.predecessor_id = predecessor.id
        current.lag_minutes = row["lag_minutes"]
        log_user_action(
            db, actor, "maindata.operation_dependency", "operation", f"{row['order_no']}#{row['seq']}",
            detail={
                "predecessor": f"{row['predecessor_order_no']}#{row['predecessor_seq']}",
                "lag_minutes": row["lag_minutes"],
            },
        )
        linked += 1
    db.flush()
    return {
        "dependency_rows": len(clean),
        "linked": linked,
        "missing_orders": sorted(missing_orders),
        "missing_operations": sorted(missing_operations),
        "self_references": sorted(self_references),
    }
