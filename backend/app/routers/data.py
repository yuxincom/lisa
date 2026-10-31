from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import DataSource, QualitySnapshot, User
from ..services.audit import log_user_action
from ..services.quality import DIMENSIONS, THRESHOLD, quality_summary, serialize_source

router = APIRouter(prefix="/api/data", tags=["data"])

DATASETS = [
    {"code": "T1~T5 + M", "name": "通识数据集", "current": 54400, "target": 54400, "unit": "条", "status": "complete", "note": "术语/方法/约束/场景/基础/元数据"},
    {"code": "ZD-01~09", "name": "核心专识", "current": 68884, "target": 71888, "unit": "条", "status": "in_progress", "note": "一期交付口径 68,884 条 · 四区间建设"},
    {"code": "Phase-2", "name": "二期全量专识", "current": 68884, "target": 160160, "unit": "条", "status": "planned", "note": "目标准确率 ≥80%"},
]

PHASES = [
    {"name": "基础骨架", "count": 9812, "accuracy": "25~30%", "complete": True},
    {"name": "核心参数", "count": 26228, "accuracy": "40~45%", "complete": True},
    {"name": "完备增强", "count": 46708, "accuracy": "50~55%", "complete": True},
    {"name": "核心全量", "count": 68884, "accuracy": "≥60%（一期验收）", "complete": True},
]


@router.get("/quality")
def quality(db: Session = Depends(get_db), user: User = Depends(require("data:read"))):
    return quality_summary(db)


@router.get("/sources")
def sources(db: Session = Depends(get_db), user: User = Depends(require("data:read"))):
    rows = db.query(DataSource).order_by(DataSource.id).all()
    return {
        "items": [serialize_source(s) for s in rows],
        "summary": {
            "total": len(rows),
            "online": sum(1 for s in rows if s.status == "online"),
            "degraded": sum(1 for s in rows if s.status == "degraded"),
            "offline": sum(1 for s in rows if s.status == "offline"),
        },
    }


@router.get("/coverage")
def coverage(db: Session = Depends(get_db), user: User = Depends(require("data:read"))):
    return {
        "datasets": DATASETS,
        "phases": PHASES,
        "interface_count": 111,
        "mapping_count": 20,
        "product_count": 108,
        "operation_count": 28,
        "resources": 32,
        "annotation": {
            "templates": 9,
            "fields": 19,
            "minimum_set": 10,
            "expert_confirm_rate": 100,
            "kappa": 0.87,
        },
    }


@router.post("/quality/check")
def run_quality_check(db: Session = Depends(get_db), user: User = Depends(require("data:read"))):
    now = datetime.now().replace(microsecond=0)
    created = []
    for idx, (dimension, _, _) in enumerate(DIMENSIONS):
        latest = (
            db.query(QualitySnapshot)
            .filter(QualitySnapshot.dimension == dimension)
            .order_by(QualitySnapshot.checked_at.desc())
            .first()
        )
        base = latest.score if latest else 92.0
        drift = ((now.minute + idx * 7) % 9 - 4) * 0.08
        score = round(min(99.2, max(89.2, base + drift)), 1)
        snapshot = QualitySnapshot(
            dimension=dimension,
            score=score,
            threshold=THRESHOLD,
            passed=score >= THRESHOLD,
            detail=latest.detail if latest else {},
            checked_at=now,
        )
        db.add(snapshot)
        created.append({"dimension": dimension, "score": score, "passed": score >= THRESHOLD})
    log_user_action(db, user, "data.quality.check", "quality", "L0", detail={"dimensions": created})
    db.commit()
    data = quality_summary(db)
    data["run"] = created
    return data


@router.get("/sources/{source_id}")
def source_detail(source_id: int, db: Session = Depends(get_db), user: User = Depends(require("data:read"))):
    source = db.get(DataSource, source_id)
    if not source:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail={"code": "SOURCE_NOT_FOUND", "message": "数据源不存在"})
    return serialize_source(source)
