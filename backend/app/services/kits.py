from __future__ import annotations

import zlib
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import KitCheck, Order

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

CHECKPOINT_LABELS = {
    "pre_schedule": "排产前",
    "post_schedule": "排产后",
    "pre_start": "开工前",
}

MISS_RATE = {"pre_schedule": 38, "post_schedule": 10, "pre_start": 4}


def _hash_int(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode("utf-8")) % 1000


def build_check(order: Order, checkpoint: str) -> dict:
    bucket = _hash_int(order.order_no, checkpoint)
    missing_bucket = MISS_RATE.get(checkpoint, 10)
    missing = bucket < missing_bucket * 10
    missing_count = 1 + (_hash_int(order.order_no, "count") % 2) if missing else 0
    missing_indexes = {
        (_hash_int(order.order_no, checkpoint, str(i)) % len(ELEMENTS)) for i in range(missing_count)
    }

    elements = []
    gaps = []
    ok_count = 0
    for idx, element in enumerate(ELEMENTS):
        if idx in missing_indexes:
            status = "missing"
            reason = {
                "tooling": "专用工装未归位，台账显示检修中",
                "main_material": "主材批次未到料，ETA 延后 36h",
                "aux_material": "辅材安全库存低于下限",
                "cutter": "刀具寿命剩余不足 20%",
                "route": "工艺路线版本与 PLM 不一致",
                "skill": "关键工序持证人员不足 1 人",
                "wip": "上道工序检验结论待判",
                "equipment": "设备处于计划保养窗口",
                "capability": "设备能力矩阵未覆盖工序要求",
            }[element["key"]]
            gaps.append(
                {
                    "key": element["key"],
                    "name": element["name"],
                    "reason": reason,
                    "action": element["action"],
                    "owner": {
                        "tooling": "工装室", "main_material": "采购部", "aux_material": "仓储部",
                        "cutter": "工具室", "route": "工艺部", "skill": "人力资源部",
                        "wip": "质量部", "equipment": "设备部", "capability": "设备部",
                    }[element["key"]],
                    "due_hours": 2 + idx,
                    "critical": element["critical"],
                }
            )
        else:
            status = "ok"
            ok_count += 1
        elements.append(
            {
                "key": element["key"],
                "name": element["name"],
                "source": element["source"],
                "status": status,
                "critical": element["critical"],
                "value": "齐套" if status == "ok" else "缺项",
            }
        )

    critical_gap = any(g["critical"] for g in gaps)
    if gaps:
        status = "阻断" if checkpoint == "pre_start" and critical_gap else "缺项"
    else:
        status = "齐套"
    score = round(ok_count / len(ELEMENTS) * 100, 1)
    return {
        "status": status,
        "score": score,
        "elements": elements,
        "gaps": gaps,
        "passed": not (checkpoint == "pre_start" and critical_gap),
    }


def persist_check(db: Session, order: Order, checkpoint: str) -> KitCheck:
    result = build_check(order, checkpoint)
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


def kit_overview(db: Session) -> dict:
    latest: dict[tuple[int, str], KitCheck] = {}
    for check in db.query(KitCheck).order_by(KitCheck.checked_at.asc()).all():
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
        "updated_at": datetime.now().replace(microsecond=0).isoformat(),
    }
