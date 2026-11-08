from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Setting

DEFAULT_SETTINGS: dict = {
    "weights": {"delivery": 0.4, "bottleneck": 0.25, "changeover": 0.2, "cost": 0.15},
    "thresholds": {"data_quality": 90, "confidence": 0.7, "kit": 100},
    "freeze_days": 3,
    "shift": {"start": 8, "end": 20, "days": 6},
    "calendar": {
        "shifts": [{"name": "白班", "start": "08:00", "end": "20:00"}],
        "workdays": [0, 1, 2, 3, 4, 5],
        "holidays": [],
        "workday_overrides": [],
        "horizon_days": 400,
    },
    "approval_timeout_minutes": 15,
    "solver_timeout_seconds": 15,
    "auto_escalate": True,
    "write_shield": True,
    "adapters": {"sources": []},
    "clearance": {
        "enabled": True,
        "levels": ["公开", "内部", "秘密", "机密"],
        "data_default": "内部",
        "report_hidden": True,
    },
    "plants": {
        "enabled": False,
        "names": ["一厂", "二厂"],
        "data_default": "一厂",
    },
    "llm": {
        "enabled": False,
        "base_url": "",
        "model": "",
        "api_key_env": "LISA_LLM_API_KEY",
        "timeout_seconds": 25,
        "max_steps": 8,
        "temperature": 0.2,
        "internal_only": True,
        "internal_suffixes": [".intra", ".internal", ".lan", ".corp", ".local"],
        "redact_fields": ["customer", "product_name", "supplier", "person_name", "drawing_no"],
        "max_observation_chars": 1600,
    },
}

SCENARIO_META = {
    "A": {"objective": "交期优先 · 军品保供", "code": "A", "weights": {"delivery": 0.5, "bottleneck": 0.15, "changeover": 0.15, "cost": 0.2}},
    "B": {"objective": "瓶颈均衡 · 负荷平滑", "code": "B", "weights": {"delivery": 0.25, "bottleneck": 0.45, "changeover": 0.15, "cost": 0.15}},
    "C": {"objective": "换型优化 · 成本优先", "code": "C", "weights": {"delivery": 0.2, "bottleneck": 0.2, "changeover": 0.4, "cost": 0.2}},
}


def get_setting(db: Session, key: str, default=None):
    row = db.query(Setting).filter(Setting.key == key).first()
    if row is not None:
        return row.value
    return deepcopy(DEFAULT_SETTINGS.get(key, default))


def set_setting(db: Session, key: str, value):
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
        row.updated_at = datetime.now().replace(microsecond=0)
    else:
        row = Setting(key=key, value=value, updated_at=datetime.now().replace(microsecond=0))
        db.add(row)
    db.flush()
    return value


def all_settings(db: Session) -> dict:
    result = deepcopy(DEFAULT_SETTINGS)
    for row in db.query(Setting).all():
        result[row.key] = row.value
    return result
