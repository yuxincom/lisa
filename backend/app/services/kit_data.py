from __future__ import annotations

"""齐套外部主数据的落地（ERP BOM / WMS 库存 / 在途 / 工装刀具 / 人员资质 / 检验结论）。

每个来源都是一张独立表 + 一个自然键 upsert：适配器（CSV 落地、HTTP 轮询、DB 中间库）
只负责把源系统的数据映射进来，不参与排产决策，也不写 APS/MES。
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import (
    Inbound,
    Inspection,
    Material,
    Qualification,
    StockItem,
    Tool,
    User,
)
from .audit import log_user_action

DATE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d")
MATERIAL_CATEGORIES = {"main_material", "aux_material"}
STOCK_QUALITY = {"合格", "待判", "隔离"}
INBOUND_STATUS = {"在途", "已到料", "延期"}
TOOL_KINDS = {"tooling", "cutter"}
TOOL_STATUS = {"可用", "检修", "未归位"}
INSPECTION_CONCLUSIONS = {"合格", "待判", "不合格"}


class KitDataError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _num(row: dict[str, Any], key: str, default: float = 0.0, label: str = "") -> float:
    raw = row.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        raise KitDataError("KIT_ROW_INVALID", f"{label or key}={raw!r} 不是数字")


def _moment(row: dict[str, Any], key: str, label: str = "") -> datetime | None:
    raw = row.get(key)
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(second=0, microsecond=0)
        except ValueError:
            continue
    raise KitDataError("KIT_ROW_INVALID", f"{label or key}={text!r} 不是可识别的时间")


def _enum(value: str, allowed: set[str], label: str, default: str) -> str:
    if not value:
        return default
    if value not in allowed:
        raise KitDataError("KIT_ROW_INVALID", f"{label}={value!r} 不在受控值域 {sorted(allowed)}")
    return value


def _material_row(row: dict[str, Any]) -> dict[str, Any]:
    code = _text(row, "code")
    if not code:
        raise KitDataError("KIT_ROW_INVALID", "物料行缺少 code")
    qty_per = _num(row, "qty_per", 1.0, "qty_per")
    if qty_per <= 0:
        raise KitDataError("KIT_ROW_INVALID", f"{code} 的单台用量必须大于 0")
    lead = _num(row, "lead_time_days", 0.0, "lead_time_days")
    if lead < 0:
        raise KitDataError("KIT_ROW_INVALID", f"{code} 的采购提前期不能为负")
    return {
        "code": code,
        "name": _text(row, "name"),
        "unit": _text(row, "unit") or "件",
        "category": _enum(_text(row, "category"), MATERIAL_CATEGORIES, "category", "main_material"),
        "product_code": _text(row, "product_code"),
        "qty_per": qty_per,
        "lead_time_days": lead,
        "source_system": _text(row, "source_system") or "ERP",
    }


def _stock_row(row: dict[str, Any]) -> dict[str, Any]:
    code = _text(row, "material_code")
    if not code:
        raise KitDataError("KIT_ROW_INVALID", "库存行缺少 material_code")
    on_hand = _num(row, "on_hand", 0.0, "on_hand")
    allocated = _num(row, "allocated", 0.0, "allocated")
    if on_hand < 0 or allocated < 0:
        raise KitDataError("KIT_ROW_INVALID", f"{code} 的库存数量不能为负")
    if allocated > on_hand:
        raise KitDataError("KIT_ROW_INVALID", f"{code} 已占用 {allocated} 超过现库存 {on_hand}")
    return {
        "material_code": code,
        "on_hand": on_hand,
        "allocated": allocated,
        "quality_status": _enum(_text(row, "quality_status"), STOCK_QUALITY, "quality_status", "合格"),
        "batch": _text(row, "batch"),
        "location": _text(row, "location"),
        "source_system": _text(row, "source_system") or "WMS",
    }


def _inbound_row(row: dict[str, Any]) -> dict[str, Any]:
    code = _text(row, "material_code")
    if not code:
        raise KitDataError("KIT_ROW_INVALID", "在途行缺少 material_code")
    qty = _num(row, "qty", 0.0, "qty")
    if qty <= 0:
        raise KitDataError("KIT_ROW_INVALID", f"{code} 的在途数量必须大于 0")
    eta = _moment(row, "eta", "eta")
    if eta is None:
        raise KitDataError("KIT_ROW_INVALID", f"{code} 缺少 ETA，无法判断能否赶上开工")
    return {
        "reference": _text(row, "reference") or f"{code}-{eta:%Y%m%d%H%M}",
        "material_code": code,
        "qty": qty,
        "eta": eta,
        "supplier": _text(row, "supplier"),
        "status": _enum(_text(row, "status"), INBOUND_STATUS, "status", "在途"),
    }


def _tool_row(row: dict[str, Any]) -> dict[str, Any]:
    code = _text(row, "code")
    if not code:
        raise KitDataError("KIT_ROW_INVALID", "工装/刀具行缺少 code")
    kind = _enum(_text(row, "kind"), TOOL_KINDS, "kind", "tooling")
    life_raw = row.get("life_remaining")
    life = None if life_raw in (None, "") else _num(row, "life_remaining", 0.0, "life_remaining")
    if life is not None and not 0.0 <= life <= 100.0:
        raise KitDataError("KIT_ROW_INVALID", f"{code} 的剩余寿命 {life} 应在 0~100 之间")
    return {
        "code": code,
        "name": _text(row, "name"),
        "kind": kind,
        "domain": _text(row, "domain"),
        "status": _enum(_text(row, "status"), TOOL_STATUS, "status", "可用"),
        "life_remaining": life,
        "owner": _text(row, "owner"),
    }


def _qualification_row(row: dict[str, Any]) -> dict[str, Any]:
    person = _text(row, "person_name")
    if not person:
        raise KitDataError("KIT_ROW_INVALID", "资质行缺少 person_name")
    capability = _text(row, "capability")
    if not capability:
        raise KitDataError("KIT_ROW_INVALID", f"{person} 的资质行缺少 capability")
    level = _num(row, "level", 1.0, "level")
    if level < 1:
        raise KitDataError("KIT_ROW_INVALID", f"{person} 的资质等级必须 >= 1")
    return {
        "person_name": person,
        "capability": capability,
        "certificate": _text(row, "certificate"),
        "level": int(level),
        "valid_until": _moment(row, "valid_until", "valid_until"),
        "active": _text(row, "active").lower() not in {"0", "false", "no", "否"},
    }


def _inspection_row(row: dict[str, Any]) -> dict[str, Any]:
    order_no = _text(row, "order_no")
    if not order_no:
        raise KitDataError("KIT_ROW_INVALID", "检验行缺少 order_no")
    seq = _num(row, "seq", 1.0, "seq")
    if seq < 1:
        raise KitDataError("KIT_ROW_INVALID", f"{order_no} 的工序序号必须从 1 开始")
    return {
        "order_no": order_no,
        "seq": int(seq),
        "conclusion": _enum(_text(row, "conclusion"), INSPECTION_CONCLUSIONS, "conclusion", "合格"),
        "inspector": _text(row, "inspector"),
        "checked_at": _moment(row, "checked_at", "checked_at") or datetime.now().replace(microsecond=0),
    }


BUILDERS = {
    "materials": _material_row,
    "stock": _stock_row,
    "inbound": _inbound_row,
    "tools": _tool_row,
    "qualifications": _qualification_row,
    "inspections": _inspection_row,
}
NATURAL_KEYS = {
    "materials": ("code",),
    "stock": ("material_code",),
    "inbound": ("reference",),
    "tools": ("code",),
    "qualifications": ("person_name", "capability"),
    "inspections": ("order_no", "seq"),
}
MODELS = {
    "materials": Material,
    "stock": StockItem,
    "inbound": Inbound,
    "tools": Tool,
    "qualifications": Qualification,
    "inspections": Inspection,
}

# 每类来源的 CSV 表头口径：交付方按这张表导出，导入时缺列直接拒绝而不是静默补空。
KIT_COLUMNS = {
    "materials": ("code", "product_code", "category", "qty_per", "lead_time_days"),
    "stock": ("material_code", "on_hand", "allocated", "quality_status"),
    "inbound": ("reference", "material_code", "qty", "eta", "status"),
    "tools": ("code", "kind", "domain", "status", "life_remaining"),
    "qualifications": ("person_name", "capability", "certificate", "valid_until"),
    "inspections": ("order_no", "seq", "conclusion", "inspector"),
}


def upsert_rows(db: Session, kind: str, rows: list[dict[str, Any]], actor: User) -> dict:
    """按自然键 upsert；返回 created/updated/unchanged 计数，非法行整批拒绝。"""
    builder = BUILDERS.get(kind)
    model = MODELS.get(kind)
    if builder is None or model is None:
        raise KitDataError("KIT_KIND_UNKNOWN", f"未知的齐套数据类型：{kind}")
    if not rows:
        raise KitDataError("KIT_DATA_EMPTY", f"{kind} 数据为空，拒绝写入")
    prepared = [builder(row) for row in rows]
    keys = NATURAL_KEYS[kind]
    existing = {
        tuple(getattr(item, key) for key in keys): item for item in db.query(model).all()
    }
    created = updated = unchanged = 0
    for payload in prepared:
        identity = tuple(payload[key] for key in keys)
        current = existing.get(identity)
        if current is None:
            record = model(**payload, updated_at=datetime.now().replace(microsecond=0))
            db.add(record)
            existing[identity] = record
            created += 1
            continue
        changed = False
        for field, value in payload.items():
            if getattr(current, field, None) != value:
                setattr(current, field, value)
                changed = True
        if hasattr(current, "updated_at") and current.updated_at is not None:
            current.updated_at = datetime.now().replace(microsecond=0)
        if changed:
            updated += 1
        else:
            unchanged += 1
    db.flush()
    log_user_action(
        db, actor, "maindata.kit_data", "kit_data", kind,
        detail={"created": created, "updated": updated, "unchanged": unchanged, "rows": len(prepared)},
    )
    return {"kind": kind, "rows": len(prepared), "created": created, "updated": updated, "unchanged": unchanged}


def data_freshness(db: Session) -> dict[str, dict[str, Any]]:
    """每个来源的最新时间戳——计划员要先知道数据有多旧，才敢按齐套开工。"""
    out: dict[str, dict[str, Any]] = {}
    for kind, model in MODELS.items():
        column = getattr(model, "updated_at", None) or getattr(model, "checked_at", None)
        rows = db.query(model).count()
        latest = db.query(column).order_by(column.desc()).first() if rows else None
        out[kind] = {
            "rows": rows,
            "as_of": latest[0].isoformat() if latest and latest[0] else None,
            "age_hours": round((datetime.now() - latest[0]).total_seconds() / 3600, 1) if latest and latest[0] else None,
        }
    return out
