from __future__ import annotations

"""厂区（plant）读取范围。

客户是单一法人、两厂区 / 10 个分厂，所以这里不是 SaaS 多租户：
数据仍在同一个库里，只是「一厂调度员不该看到二厂的工单与产能」。
与密级同为读取范围，两条过滤必须叠加生效，缺一不可。

口径：
- enabled=False（出厂默认）→ 全部厂区可见，升级后不会有人突然看不见东西；
- 账号没勾任何厂区（plants 为空）→ 全厂区可见，代表「不受厂区限制」，不是「什么都看不见」；
- 账号勾了厂区 → 只看这些厂区的数据；勾了主数据里不存在的厂区名 → 一条都看不到（fail-closed，
  并在界面上如实报「被厂区范围隐去」的数量，看不见不等于不存在）。
"""

from typing import Any

from sqlalchemy import func, true
from sqlalchemy.orm import Session

from ..models import Order, Resource, User
from .settings import get_setting

DEFAULT_PLANT_CONFIG = {
    "enabled": False,
    "names": ["一厂", "二厂"],
    "data_default": "一厂",
}


class PlantError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize(raw: Any) -> dict:
    merged = dict(DEFAULT_PLANT_CONFIG)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if k in DEFAULT_PLANT_CONFIG})
    names = [str(x).strip() for x in (merged.get("names") or [])]
    if any(not x for x in names):
        raise PlantError("PLANT_NAMES_INVALID", "厂区清单里不能有空值")
    if not names:
        raise PlantError("PLANT_NAMES_INVALID", "厂区清单不能为空：至少给出一个厂区名")
    if len(set(names)) != len(names):
        raise PlantError("PLANT_NAMES_INVALID", f"厂区清单里有重名：{', '.join(names)}")
    default = str(merged.get("data_default") or "").strip()
    if default not in names:
        raise PlantError("PLANT_DEFAULT_INVALID", f"未标注厂区的数据默认归入「{default or '空'}」，但它不在厂区清单里")
    return {"enabled": bool(merged.get("enabled")), "names": names, "data_default": default}


def config(db: Session) -> dict:
    return normalize(get_setting(db, "plants"))


def label_expr(column, cfg: dict):
    return func.coalesce(func.nullif(column, ""), cfg["data_default"])


def allowed(user: Any, cfg: dict) -> list[str] | None:
    """None = 不受厂区限制。勾了但全不在清单里的账号返回空表，什么也看不到。"""
    if not cfg["enabled"] or user is None:
        return None
    claimed = [str(x).strip() for x in (getattr(user, "plants", None) or []) if str(x).strip()]
    if not claimed:
        return None
    return [name for name in cfg["names"] if name in set(claimed)]


def visible_filter(user: Any, column, cfg: dict):
    if not cfg.get("enabled"):
        return true()
    names = allowed(user, cfg)
    if names is None:
        return true()
    if not names:
        # 勾了厂区名但都不认识：fail-closed，且界面上会把他看到的数据量报成「被厂区隐去」
        return label_expr(column, cfg).in_(["__none__"])
    return label_expr(column, cfg).in_(names)


def can_read(user: Any, record: Any, cfg: dict) -> bool:
    if not cfg.get("enabled") or record is None:
        return True
    names = allowed(user, cfg)
    if names is None:
        return True
    value = ((getattr(record, "plant", "") or "").strip() or cfg["data_default"])
    return value in names


def guard(user: Any, record: Any, cfg: dict) -> None:
    if not can_read(user, record, cfg):
        raise PlantError(
            "PLANT_DENIED",
            f"{getattr(user, 'username', '?')} 的厂区范围（{('、'.join(x for x in (getattr(user, 'plants', None) or [])) or '未勾选')}"
            f"）不含 {(getattr(record, 'plant', '') or '').strip() or cfg['data_default']}，已按 fail-closed 拒绝",
        )


def hidden_breakdown(db: Session, model, user: Any, cfg: dict) -> dict[str, int]:
    if not cfg["enabled"] or not hasattr(model, "plant"):
        return {}
    names = allowed(user, cfg)
    if names is None:
        return {}
    label = label_expr(model.plant, cfg)
    allowed_set = set(names)
    rows = db.query(label, func.count(model.id)).group_by(label).all()
    return {str(value): count for value, count in rows if str(value) not in allowed_set}


def hidden_count(db: Session, model, user: Any, cfg: dict) -> int:
    return sum(hidden_breakdown(db, model, user, cfg).values())


def report(db: Session, user: Any) -> dict:
    cfg = config(db)
    label = label_expr(Order.plant, cfg)
    counts = {str(value): count for value, count in db.query(label, func.count(Order.id)).group_by(label).all()}
    by_plant = {name: counts.get(name, 0) for name in cfg["names"]}
    orphan = {value: count for value, count in counts.items() if value not in by_plant}
    people = [
        {"username": row.username, "name": row.name, "role": row.role,
         "plants": [str(x) for x in (row.plants or []) if str(x).strip()]}
        for row in db.query(User).order_by(User.id).all()
    ]
    unknown_claimed = sorted({
        name for person in people for name in person["plants"] if name not in cfg["names"]
    })
    return {
        **cfg,
        "your_scope": allowed(user, cfg),
        "orders_by_plant": by_plant,
        "orders_outside_plants": orphan,
        "people": people,
        "unknown_claimed_plants": unknown_claimed,
        "resource_count": db.query(Resource).filter(visible_filter(user, Resource.plant, cfg)).count(),
        "hidden_orders": hidden_breakdown(db, Order, user, cfg),
    }


def visible_order_ids(user: Any, clr_cfg: dict, plant_cfg: dict):
    """按「密级 + 厂区」两条一起算出可读工单 id 子查询；None = 不加限制。

    齐套 / 计划条目 / 工序这些表自己没有范围列，只能挂在工单维度上过滤，
    所以这里是所有派生口径的唯一入口——漏一条就等于那条面没过滤。
    """
    from sqlalchemy import select

    from . import clearance as clr

    clr_scope = clr.visible_order_ids(user, clr_cfg)
    if not plant_cfg.get("enabled") or user is None:
        return clr_scope
    names = allowed(user, plant_cfg)
    if names is None:
        return clr_scope
    plant_condition = visible_filter(user, Order.plant, plant_cfg)
    if clr_scope is None:
        return select(Order.id).where(plant_condition).scalar_subquery()
    # 两条都要：把已算出的密级子查询再按厂区收窄
    return select(Order.id).where(Order.id.in_(clr_scope), plant_condition).scalar_subquery()
