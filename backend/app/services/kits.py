from __future__ import annotations

"""齐套九要素点检（排产前 / 排产后 / 开工前）。

九要素全部按真实主数据实算：需求侧来自 ERP BOM，供给侧来自 WMS 库存与在途承诺，
设备/能力来自 LISA 资源台账，质量状态来自 QMS 检验结论，人员资质来自 HR 技能矩阵。
源表没有数据的要素判为「未接入」——不参与齐套得分，也不冒充通过。
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import (
    Inbound,
    Inspection,
    KitCheck,
    Material,
    Operation,
    Order,
    Product,
    Qualification,
    Resource,
    StockItem,
    Tool,
)

ELEMENTS = [
    {"key": "tooling", "name": "工装", "source": "MES 工装台账", "critical": True, "action": "联系工装室调拨并确认可用性"},
    {"key": "main_material", "name": "主材", "source": "WMS 库存 / ERP BOM", "critical": True, "action": "触发替代料审批或加急到料"},
    {"key": "aux_material", "name": "辅材", "source": "WMS 库存", "critical": False, "action": "补库并核对批次"},
    {"key": "cutter", "name": "刀具", "source": "MES 刀具寿命台账", "critical": False, "action": "换刀并校验刀具寿命"},
    {"key": "route", "name": "工艺路线", "source": "PLM 工艺版本", "critical": True, "action": "工艺员确认路线有效性与版本"},
    {"key": "skill", "name": "人员资质", "source": "HR 技能矩阵", "critical": True, "action": "调整持证人员或安排培训"},
    {"key": "wip", "name": "WIP 质量状态", "source": "QMS 检验结论", "critical": False, "action": "隔离待判并推进质量处置"},
    {"key": "equipment", "name": "设备状态", "source": "MES 设备实时状态", "critical": True, "action": "启用备选设备或等待抢修"},
    {"key": "capability", "name": "设备能力", "source": "EAM 能力台账", "critical": True, "action": "匹配具备能力的替代设备"},
]

OWNERS = {
    "tooling": "工装室", "main_material": "采购部", "aux_material": "仓储部",
    "cutter": "工具室", "route": "工艺部", "skill": "人力资源部",
    "wip": "质量部", "equipment": "设备部", "capability": "设备部",
}
DUE_HOURS = {"tooling": 8, "main_material": 36, "aux_material": 24, "cutter": 12, "route": 24,
             "skill": 48, "wip": 16, "equipment": 6, "capability": 12}

CHECKPOINT_LABELS = {
    "pre_schedule": "排产前",
    "post_schedule": "排产后",
    "pre_start": "开工前",
}

CUTTER_LIFE_MIN = 20.0


def build_check(db: Session, order: Order, checkpoint: str) -> dict:
    now = datetime.now().replace(microsecond=0)
    product = db.get(Product, order.product_id) if order.product_id else None
    route = sorted((product.route or []) if product else [], key=lambda s: int(s["seq"]))
    domains = [str(s.get("domain")) for s in route if s.get("domain")]
    wanted_types = [str(s.get("resource_type") or s.get("domain")) for s in route]
    qty = max(1, int(order.qty or 1))
    horizon = order.due_date if checkpoint != "pre_start" and order.due_date else now + timedelta(days=1)
    if checkpoint == "pre_start":
        horizon = now

    meta = {element["key"]: element for element in ELEMENTS}
    elements: list[dict] = []
    gaps: list[dict] = []

    def record(key: str, status: str, value: str, reason: str = "") -> None:
        spec = meta[key]
        elements.append({
            "key": key, "name": spec["name"], "source": spec["source"],
            "status": status, "critical": spec["critical"], "value": value,
        })
        if status == "missing":
            gaps.append({
                "key": key, "name": spec["name"], "reason": reason or value, "action": spec["action"],
                "owner": OWNERS[key], "due_hours": DUE_HOURS[key], "critical": spec["critical"],
            })

    resources = db.query(Resource).all()
    usable = [
        r for r in resources
        if r.status == "running" and not (r.maintenance_until and r.maintenance_until > now)
    ]
    usable_ids = {r.id for r in usable}

    # ---- 主材 / 辅材：需求 = BOM 单台用量 × 订单数量，供给 = 可用库存 + 承诺到料
    def evaluate_material(key: str) -> None:
        if db.query(Material).count() == 0:
            record(key, "unknown", "未接入", f"{meta[key]['source']} 尚未提供 BOM 数据")
            return
        mats = (
            db.query(Material)
            .filter(Material.category == key, Material.product_code == (product.code if product else ""))
            .all()
        )
        if not mats:
            record(key, "missing", "BOM 未覆盖", f"产品 {product.code if product else order.product_name} 的{meta[key]['name']}清单未从 ERP 展开")
            return
        shortages = []
        for item in mats:
            needed = round(float(item.qty_per or 1.0) * qty, 3)
            stock = db.query(StockItem).filter(StockItem.material_code == item.code).first()
            on_hand = stock.available if stock else 0.0
            incoming = sum(
                float(row.qty or 0.0)
                for row in db.query(Inbound).filter(
                    Inbound.material_code == item.code,
                    Inbound.status != "延期",
                    Inbound.eta <= horizon,
                ).all()
            )
            if needed > on_hand + incoming:
                shortages.append({"code": item.code, "name": item.name, "unit": item.unit,
                                  "needed": needed, "short": round(needed - on_hand - incoming, 3),
                                  "lead": float(item.lead_time_days or 0.0)})
        if shortages:
            worst = sorted(shortages, key=lambda s: -s["short"])[:3]
            detail = "；".join(f"{s['code']} {s['name']} 缺 {s['short']}{s['unit']}（提前期 {s['lead']:.0f} 天）" for s in worst)
            record(key, "missing", f"缺 {len(shortages)} 项", f"{len(shortages)} 项{meta[key]['name']}不足：{detail}")
        else:
            record(key, "ok", f"{len(mats)} 项齐")

    evaluate_material("main_material")
    evaluate_material("aux_material")

    # ---- 设备状态：路线涉及的每个能力域都要至少有一台可调用设备
    usable = [
        r for r in resources
        if r.status == "running" and not (r.maintenance_until and r.maintenance_until > now)
    ]
    if not domains:
        record("equipment", "unknown", "无路线", "订单未关联工艺路线，无法判定所需设备")
    else:
        dead_domains = sorted({d for d in domains if not any(r.domain == d and r.id in usable_ids for r in resources)})
        if dead_domains:
            blocked = [r for r in resources if r.domain in dead_domains and r.id not in usable_ids]
            sample = "、".join(
                f"{r.code}{'（保养至 ' + r.maintenance_until.strftime('%m-%d %H:%M') + '）' if r.maintenance_until and r.maintenance_until > now else '（' + r.status + '）'}"
                for r in blocked[:3]
            )
            reason = f"能力域 {', '.join(dead_domains)} 无可调用设备"
            if sample:
                reason = f"{sample} 不可调用，{reason}"
            record("equipment", "missing", f"{len(dead_domains)} 个域停机", reason)
        else:
            record("equipment", "ok", f"{len(usable)} 台可调用")

    # ---- 设备能力：工序要求的 resource_type 必须落在设备能力标签里
    if not route:
        record("capability", "unknown", "无路线", "订单未关联工艺路线")
    else:
        uncovered = []
        for step, wanted in zip(route, wanted_types):
            pool = [r for r in resources if r.domain == step.get("domain")]
            if not any((not r.capabilities) or wanted in (r.capabilities or []) for r in pool):
                uncovered.append(f"#{step['seq']} {step['name']}→{wanted}")
        if uncovered:
            record("capability", "missing", f"{len(uncovered)} 道工序无能力",
                   f"设备能力台账未覆盖：{('；'.join(uncovered[:3]))}")
        else:
            record("capability", "ok", f"{len(route)} 道工序全覆盖")

    # ---- 工装：路线涉及的每个能力域都要有可用工装
    tools = db.query(Tool).all()
    if not tools:
        record("tooling", "unknown", "未接入", "MES 工装台账尚未提供数据")
        record("cutter", "unknown", "未接入", "MES 刀具寿命台账尚未提供数据")
    else:
        tooling = [t for t in tools if t.kind == "tooling"]
        wanted_domains = set(domains)
        missing_domains = sorted(
            d for d in wanted_domains if not any(t.domain == d and t.status == "可用" for t in tooling)
        )
        unavailable = [t for t in tooling if t.status != "可用" and t.domain in wanted_domains]
        if missing_domains:
            record("tooling", "missing", f"{len(missing_domains)} 个域缺工装",
                   f"能力域 {', '.join(missing_domains)} 没有可用工装")
        elif unavailable:
            record("tooling", "missing", f"{len(unavailable)} 套不可用",
                   "、".join(f"{t.code} {t.name}（{t.status}）" for t in unavailable[:3]))
        else:
            record("tooling", "ok", f"{len(tooling)} 套可用")

        cutters = [t for t in tools if t.kind == "cutter"]
        low = [t for t in cutters if t.life_remaining is not None and t.life_remaining < CUTTER_LIFE_MIN]
        if not cutters:
            record("cutter", "unknown", "无刀具台账", "刀具寿命数据未覆盖本厂刀具")
        elif low:
            record("cutter", "missing", f"{len(low)} 把寿命不足",
                   "、".join(f"{t.code} {t.name} 剩余 {t.life_remaining:.0f}%" for t in low[:3]))
        else:
            record("cutter", "ok", f"{len(cutters)} 把达标")

    # ---- 工艺路线：路线缺失或 ECN/军检有效期已过
    if not product or not route:
        record("route", "missing", "缺工艺路线", f"产品 {order.product_name} 没有可用路线版本")
    else:
        expired = (
            db.query(Operation)
            .filter(Operation.order_id == order.id, Operation.valid_until.isnot(None), Operation.valid_until < now)
            .count()
        )
        if expired:
            record("route", "missing", f"{expired} 道工序版本过期",
                   f"{expired} 道专项工序的 ECN/军检有效期已过期，需工艺员重新签发")
        else:
            record("route", "ok", f"{len(route)} 道工序有效")

    # ---- 人员资质：工序要求的能力必须有未过期且在职的持证人员覆盖
    qualifications = db.query(Qualification).all()
    if not qualifications:
        record("skill", "unknown", "未接入", "HR 技能矩阵尚未提供数据（配置清单 C4）")
    else:
        uncovered_types = []
        for wanted in sorted(set(t for t in wanted_types if t)):
            covered = [
                q for q in qualifications
                if q.active and q.capability == wanted and (q.valid_until is None or q.valid_until > now)
            ]
            if not covered:
                uncovered_types.append(wanted)
        if uncovered_types:
            record("skill", "missing", f"{len(uncovered_types)} 个能力无持证人员",
                   f"能力 {', '.join(uncovered_types[:4])} 没有有效期内的持证人员")
        else:
            record("skill", "ok", f"{len(set(qual.capability for qual in qualifications if qual.active))} 个能力已覆盖")

    # ---- WIP 质量状态：本订单存在待判/不合格结论即视为质量开口
    if db.query(Inspection).count() == 0:
        record("wip", "unknown", "未接入", "QMS 检验结论尚未提供数据")
    else:
        rows = db.query(Inspection).filter(Inspection.order_no == order.order_no).all()
        open_issues = [r for r in rows if r.conclusion in ("待判", "不合格")]
        if open_issues:
            detail = "、".join(f"#{r.seq} {r.conclusion}" for r in sorted(open_issues, key=lambda x: x.seq)[:3])
            record("wip", "missing", f"{len(open_issues)} 道未闭环", f"检验结论未闭环：{detail}")
        else:
            record("wip", "ok", "无未闭环结论")

    evaluated = [e for e in elements if e["status"] != "unknown"]
    unknown = [e["name"] for e in elements if e["status"] == "unknown"]
    critical_gap = any(gap["critical"] for gap in gaps)
    if gaps:
        status = "阻断" if checkpoint == "pre_start" and critical_gap else "缺项"
    elif len(evaluated) < len(ELEMENTS):
        # 还有外部源没接入，不能宣布齐套——未接入的要素不计分，也不算通过
        status = "待接入"
    else:
        status = "齐套"
    ok_count = sum(1 for e in evaluated if e["status"] == "ok")
    return {
        "status": status,
        "score": round(ok_count / len(ELEMENTS) * 100, 1),
        "evaluated_count": len(evaluated),
        "elements": elements,
        "gaps": gaps,
        "unevaluated": unknown,
        "checkpoint_label": CHECKPOINT_LABELS.get(checkpoint, checkpoint),
        "passed": status != "阻断",
    }


def persist_check(db: Session, order: Order, checkpoint: str) -> KitCheck:
    result = build_check(db, order, checkpoint)
    check = KitCheck(
        order_id=order.id,
        order_no=order.order_no,
        product_name=order.product_name,
        checkpoint=checkpoint,
        status=result["status"],
        score=result["score"],
        elements=result["elements"],
        gaps=result["gaps"],
        checked_at=datetime.now().replace(microsecond=0),
    )
    db.add(check)
    db.flush()
    if result["status"] == "待接入":
        order.kit_status = "待接入"
    else:
        order.kit_status = "齐套" if not result["gaps"] else "缺料"
    return check


def serialize_check(check: KitCheck) -> dict:
    return {
        "id": check.id,
        "order_id": check.order_id,
        "order_no": check.order_no,
        "product_name": check.product_name,
        "checkpoint": check.checkpoint,
        "checkpoint_label": CHECKPOINT_LABELS.get(check.checkpoint, check.checkpoint),
        "status": check.status,
        "score": check.score,
        "elements": check.elements or [],
        "gaps": check.gaps or [],
        "checked_at": check.checked_at.isoformat() if check.checked_at else None,
    }


def kit_overview(db: Session, order_scope=None) -> dict:
    """order_scope 是 visible_order_ids() 返回的子查询（KitCheck.order_id 维度）；不传则统计全量。
    必须走 in_()：把子查询当裸条件传给 filter()，SQLite 会默默取首行，PostgreSQL 直接报
    「more than one row returned by a subquery used as an expression」。"""
    latest: dict[tuple[int, str], KitCheck] = {}
    checks = db.query(KitCheck)
    if order_scope is not None:
        checks = checks.filter(KitCheck.order_id.in_(order_scope))
    for check in checks.order_by(KitCheck.checked_at.asc()).all():
        latest[(check.order_id, check.checkpoint)] = check
    by_checkpoint = []
    for checkpoint, label in CHECKPOINT_LABELS.items():
        rows = [c for (_, cp), c in latest.items() if cp == checkpoint]
        passed = sum(1 for c in rows if c.status == "齐套")
        rate = round(passed / len(rows) * 100, 1) if rows else 0.0
        by_checkpoint.append(
            {
                "checkpoint": checkpoint,
                "label": label,
                "total": len(rows),
                "passed": passed,
                "rate": rate,
                "missing": sum(1 for c in rows if c.status == "缺项"),
                "blocked": sum(1 for c in rows if c.status == "阻断"),
                "pending": sum(1 for c in rows if c.status == "待接入"),
            }
        )
    post = next((x for x in by_checkpoint if x["checkpoint"] == "post_schedule"), None)
    gaps_by_owner: dict[str, int] = {}
    for check in latest.values():
        for gap in check.gaps or []:
            gaps_by_owner[gap["owner"]] = gaps_by_owner.get(gap["owner"], 0) + 1
    return {
        "by_checkpoint": by_checkpoint,
        "post_schedule_rate": post["rate"] if post else 0,
        "gap_owners": sorted(
            [{"owner": k, "count": v} for k, v in gaps_by_owner.items()],
            key=lambda x: x["count"], reverse=True,
        ),
        "scoped": order_scope is not None,
        "updated_at": datetime.now().replace(microsecond=0).isoformat(),
    }
