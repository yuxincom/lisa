from __future__ import annotations

"""轻量列补齐。

`Base.metadata.create_all` 只建新表，不会给已存在的表加新列，所以升级 LISA
到带新字段的版本时（例如 resources.machine_count）老库会缺列。这里只加列、
不修改也不删除任何已有列，可在每次启动时安全重复执行。
"""

import json
from typing import Any

from sqlalchemy import inspect, text

from . import models  # noqa: F401  确保所有表已注册进 metadata
from .database import Base, engine


def _literal(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def sync_new_columns() -> list[str]:
    added: list[str] = []
    dialect = engine.dialect
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            spec = column.type.compile(dialect)
            with engine.begin() as conn:
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {spec} NULL')
                )
                default = column.default.arg if column.default is not None and column.default.is_scalar else None
                if default is not None:
                    conn.execute(
                        text(f'UPDATE "{table.name}" SET "{column.name}" = :value WHERE "{column.name}" IS NULL'),
                        {"value": _literal(default)},
                    )
            added.append(f"{table.name}.{column.name}")
    return added
