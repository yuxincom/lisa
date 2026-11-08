from __future__ import annotations

"""密级过滤：让 User.clearance 真的参与查询，而不是只写不读。

fail-closed 取向：人的密级不认识/为空 → 当作最低级（看得最少）；数据的密级不在等级表里
→ 谁都看不到；数据完全没标注 → 按 clearance.data_default 标注（默认「内部」）。
查询级过滤和单条 can_read 用同一个「有效密级」口径，避免出现列表看得到、详情看不到。
E1 给出真实等级表后，只改设置项 clearance.levels 的顺序即可，不用动代码。
"""

from typing import Any

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from ..models import Order, User
from .settings import get_setting

DEFAULT_CLEARANCE_CONFIG: dict[str, Any] = {
    "enabled": True,
    "levels": ["公开", "内部", "秘密", "机密"],
    "data_default": "内部",
    "report_hidden": True,
}


class ClearanceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize(raw: Any) -> dict:
    """补齐默认值并校验等级表；写设置和读设置走同一个口径，避免存进去一个读不出来的配置。"""
    merged = dict(DEFAULT_CLEARANCE_CONFIG)
    if isinstance(raw, dict):
        merged.update({key: value for key, value in raw.items() if key in DEFAULT_CLEARANCE_CONFIG})
    levels = [str(level).strip() for level in merged.get("levels") or []]
    if any(not level for level in levels):
        raise ClearanceError("CLEARANCE_LEVELS_INVALID", "密级等级表里不能有空值")
    if len(levels) < 2 or len(set(levels)) != len(levels):
        raise ClearanceError("CLEARANCE_LEVELS_INVALID", "密级等级表必须是 2 个以上、互不重复的有序值")
    default = str(merged.get("data_default") or "").strip()
    if default not in levels:
        raise ClearanceError(
            "CLEARANCE_DEFAULT_INVALID",
            f"未标注数据的默认密级「{default or '空'}」不在等级表里：这些工单会变得谁都无法配置可读",
        )
    merged["levels"] = levels
    merged["data_default"] = default
    merged["enabled"] = bool(merged.get("enabled"))
    merged["report_hidden"] = bool(merged.get("report_hidden"))
    return merged


def config(db: Session) -> dict:
    return normalize(get_setting(db, "clearance"))


def _rank(value: str, levels: list[str], *, fail_high: bool) -> int:
    cleaned = (value or "").strip()
    if cleaned in levels:
        return levels.index(cleaned)
    return len(levels) - 1 if fail_high else 0


def _label_expr(column, cfg: dict):
    """SQL 侧的「有效密级」，与 can_read 的 Python 侧口径一致。"""
    return func.coalesce(func.nullif(column, ""), cfg.get("data_default") or "")


def allowed_values(user: Any, cfg: dict) -> list[str]:
    """user=None 表示系统内部调用（排产引擎、Agent 服务），不是「某个读者」，不过滤。
    请求路径必须传真实 User，漏传会在这里退化成不过滤——所以路由层不要图省事传 None。"""
    levels = cfg["levels"]
    if user is None:
        return list(levels)
    top = _rank(getattr(user, "clearance", "") or "", levels, fail_high=False)
    return levels[: top + 1]


def highest(values: list[str], cfg: dict) -> str:
    """若干数据里最高的密级，用来给派生记录（扰动事件、方案）打标；空输入落到 data_default。
    这里 fail_high=True：认不出的标签按最高级处理，宁可高标也不要低估。"""
    levels = cfg["levels"]
    default = cfg.get("data_default") or levels[0]
    ranked = [_rank(value, levels, fail_high=True) for value in values if (value or "").strip()]
    return levels[max(ranked, default=_rank(default, levels, fail_high=False))]


def visible_filter(user: Any, column, cfg: dict):
    """查询级过滤条件。关闭过滤或系统内部调用（user=None）时返回恒真条件——
    不能返回 None：SQLAlchemy 会把 filter(None) 渲染成 `WHERE NULL`，结果一条都不匹配，
    「不做密级过滤」于是变成「什么都看不见」。"""
    if not cfg.get("enabled") or user is None:
        return true()
    return _label_expr(column, cfg).in_(allowed_values(user, cfg))


def visible_order_ids(user: Any, cfg: dict):
    """挂在工单上、自身没有密级列的表（齐套检查 / 计划条目 / 工序）按工单密级过滤。"""
    if not cfg.get("enabled") or user is None:
        return None
    return select(Order.id).where(visible_filter(user, Order.clearance, cfg)).scalar_subquery()


def can_read(user: Any, record: Any, cfg: dict) -> bool:
    if not cfg.get("enabled") or record is None or user is None:
        return True
    value = ((getattr(record, "clearance", "") or "").strip() or cfg.get("data_default") or "").strip()
    return value in allowed_values(user, cfg)


def guard(user: Any, record: Any, cfg: dict) -> None:
    if not can_read(user, record, cfg):
        raise ClearanceError(
            "CLEARANCE_DENIED",
            f"{getattr(user, 'username', '?')}（密级 {getattr(user, 'clearance', '') or '未标注'}）"
            "无权读取该记录，已按 fail-closed 拒绝",
        )


def hidden_breakdown(db: Session, model, user: Any, cfg: dict) -> dict[str, int]:
    """被密级挡住的行按等级分布——如实报给界面，避免「看不见 = 不存在」的错觉。"""
    if not cfg.get("enabled") or not cfg.get("report_hidden", True):
        return {}
    allowed = set(allowed_values(user, cfg))
    label = _label_expr(model.clearance, cfg)
    rows = db.query(label, func.count(model.id)).group_by(label).all()
    return {str(value): count for value, count in rows if value not in allowed}


def hidden_count(db: Session, model, user: Any, cfg: dict) -> int:
    return sum(hidden_breakdown(db, model, user, cfg).values())


def report(db: Session, user: Any) -> dict:
    """给设置页的一屏体检：等级表长什么样、每一级有多少数据和人、有没有标签落在表外。
    表外的标签谁都读不到（fail-closed），这里必须显式列出来，否则改完等级表只会静默丢数据。"""
    cfg = config(db)
    label = _label_expr(Order.clearance, cfg)
    order_rows = db.query(label, func.count(Order.id)).group_by(label).all()
    counts = {str(value): count for value, count in order_rows}
    known = {level: counts.get(level, 0) for level in cfg["levels"]}
    orphan = {value: count for value, count in counts.items() if value not in known}
    people: dict[str, int] = {}
    for value, count in db.query(User.clearance, func.count(User.id)).group_by(User.clearance).all():
        people[str((value or "").strip() or "未标注")] = count
    return {
        **cfg,
        "your_level": (getattr(user, "clearance", "") or "") or None,
        "you_can_read": allowed_values(user, cfg),
        "orders_by_level": known,
        "orders_outside_levels": orphan,
        "users_by_level": people,
        "visible_levels": len(allowed_values(user, cfg)),
        "total_levels": len(cfg["levels"]),
    }
