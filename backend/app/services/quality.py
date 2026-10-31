from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import DataSource, QualitySnapshot

DIMENSIONS = [
    ("完整性", "关键字段非空率与主数据覆盖度", "MES / ERP / PLM"),
    ("及时性", "执行数据时延 ≤5min、事件延迟 ≤1min", "MES / RocketMQ"),
    ("一致性", "图号↔物料号、BOM 版本、跨系统口径", "ERP / MES / PLM"),
    ("准确性", "标准工时、工艺参数与实绩偏差", "MES / QMS"),
    ("唯一性", "主键重复、订单/工单重复录入", "ERP / WMS"),
]

THRESHOLD = 90.0


def latest_snapshots(db: Session) -> list[QualitySnapshot]:
    rows: list[QualitySnapshot] = []
    for name, _, _ in DIMENSIONS:
        snap = (
            db.query(QualitySnapshot)
            .filter(QualitySnapshot.dimension == name)
            .order_by(QualitySnapshot.checked_at.desc())
            .first()
        )
        if snap:
            rows.append(snap)
    return rows


def quality_summary(db: Session) -> dict:
    latest = latest_snapshots(db)
    dims = []
    for idx, (name, desc, source) in enumerate(DIMENSIONS):
        snap = next((s for s in latest if s.dimension == name), None)
        score = snap.score if snap else 0.0
        passed = score >= THRESHOLD
        dims.append(
            {
                "key": name,
                "label": name,
                "description": desc,
                "source": source,
                "score": round(score, 1),
                "threshold": THRESHOLD,
                "passed": passed,
                "detail": snap.detail if snap else {},
                "checked_at": snap.checked_at.isoformat() if snap else None,
                "trend": _trend(db, name),
            }
        )
    overall = round(sum(d["score"] for d in dims) / len(dims), 1) if dims else 0.0
    passed = all(d["passed"] for d in dims)
    sources = db.query(DataSource).order_by(DataSource.id).all()
    return {
        "dimensions": dims,
        "overall": overall,
        "threshold": THRESHOLD,
        "gate": {
            "passed": passed,
            "label": "L0 门禁通过" if passed else "L0 门禁未通过",
            "message": (
                "五维点检全部达标，允许进入排产链路"
                if passed
                else "存在维度低于 90%，排产链路阻断并生成整改单"
            ),
        },
        "sources": [serialize_source(s) for s in sources],
        "checked_at": datetime.now().replace(microsecond=0).isoformat(),
    }


def _trend(db: Session, dimension: str) -> list[dict]:
    rows = (
        db.query(QualitySnapshot)
        .filter(QualitySnapshot.dimension == dimension)
        .order_by(QualitySnapshot.checked_at.asc())
        .all()
    )
    return [{"date": r.checked_at.strftime("%m-%d"), "score": round(r.score, 1)} for r in rows[-14:]]


def serialize_source(source: DataSource) -> dict:
    return {
        "id": source.id,
        "code": source.code,
        "name": source.name,
        "type": source.type,
        "status": source.status,
        "latency_ms": source.latency_ms,
        "last_sync": source.last_sync.isoformat() if source.last_sync else None,
        "records": source.records,
        "quality": round(source.quality, 1),
        "owner": source.owner,
    }
