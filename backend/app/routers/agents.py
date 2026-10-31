from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import AgentRun, Plan, User
from ..schemas import RunScenarioRequest
from ..services.agents import agent_catalog, run_scenario
from ..services.serializers import agent_run_to_dict, plan_to_dict

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), user: User = Depends(require("agents:read"))):
    return agent_catalog(db)


@router.post("/run")
def run(
    payload: RunScenarioRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("agents:run")),
):
    try:
        agent_run = run_scenario(db, user, payload.scenario, payload.change_id, payload.options)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail={"code": "AGENT_RUN_INVALID", "message": str(exc)})
    db.commit()
    db.refresh(agent_run)
    data = agent_run_to_dict(agent_run, include_steps=True)
    plan_ids = [p.get("id") for p in (agent_run.output or {}).get("plans", []) if p.get("id")]
    plans = db.query(Plan).filter(Plan.id.in_(plan_ids)).all() if plan_ids else []
    data["plans"] = [plan_to_dict(p, db) for p in plans]
    return data


@router.get("/runs")
def runs(
    agent_code: str | None = None,
    scenario: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require("agents:read")),
):
    query = db.query(AgentRun)
    if agent_code:
        query = query.filter(AgentRun.agent_code == agent_code)
    if scenario:
        query = query.filter(AgentRun.scenario == scenario)
    rows = query.order_by(AgentRun.started_at.desc()).limit(limit).all()
    return {"items": [agent_run_to_dict(r) for r in rows], "total": len(rows)}


@router.get("/runs/{run_id}")
def run_detail(run_id: int, db: Session = Depends(get_db), user: User = Depends(require("agents:read"))):
    run_obj = db.get(AgentRun, run_id)
    if not run_obj:
        raise HTTPException(status_code=404, detail={"code": "RUN_NOT_FOUND", "message": "智能体运行记录不存在"})
    return agent_run_to_dict(run_obj, include_steps=True)
