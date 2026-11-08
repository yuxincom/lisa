from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import AgentRun, Plan, User
from ..schemas import LlmConfigUpdate, LlmTestRequest, RunScenarioRequest
from ..services import jobs as job_queue
from ..services.agents import agent_catalog, supported_scenarios
from ..services.audit import log_user_action
from ..services.llm import DEFAULT_LLM_CONFIG, LlmError, config as llm_config
from ..services.llm import test_connection, validate_config
from ..services.mcp_server import INSTRUCTIONS, PROTOCOL_VERSION, SERVER_INFO, TOOLS
from ..services.serializers import agent_run_to_dict, plan_to_dict
from ..services.settings import set_setting

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _with_plans(db: Session, data: dict) -> dict:
    """把本次运行产出的方案挂在返回里：抽屉里要能直接点进方案，不该让前端自己猜 id。"""
    plan_ids = [p.get("id") for p in (data.get("output") or {}).get("plans", []) if p.get("id")]
    plans = db.query(Plan).filter(Plan.id.in_(plan_ids)).all() if plan_ids else []
    data["plans"] = [plan_to_dict(p, db) for p in plans]
    return data


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), user: User = Depends(require("agents:read"))):
    return agent_catalog(db)


@router.get("/llm")
def llm_status(db: Session = Depends(get_db), user: User = Depends(require("agents:read"))):
    cfg = llm_config(db)
    env_name = str(cfg.get("api_key_env") or "")
    recent = db.query(AgentRun).order_by(AgentRun.started_at.desc()).limit(20).all()
    modes = [
        (r.output.get("llm") or {}).get("mode") if isinstance(r.output, dict) else None
        for r in recent
    ]
    used = [r.output.get("llm") for r in recent if isinstance(r.output, dict) and r.output.get("llm")]
    return {
        "config": cfg,
        "defaults": DEFAULT_LLM_CONFIG,
        "credential_present": bool(os.getenv(env_name)),
        "credential_source": env_name or None,
        "mcp": {
            "protocol_version": PROTOCOL_VERSION,
            "server": SERVER_INFO,
            "instructions": INSTRUCTIONS,
            "endpoint": "/api/mcp/rpc",
            "tools": [{"name": t["name"], "description": t["description"]} for t in TOOLS],
        },
        "runs": {
            "window": len(recent),
            "llm": sum(1 for mode in modes if mode == "llm"),
            "fallback": sum(1 for mode in modes if mode != "llm"),
            "last": used[0] if used else None,
        },
    }


@router.put("/llm")
def save_llm(
    payload: LlmConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可配置模型编排"})
    unknown = [key for key in payload.values if key not in DEFAULT_LLM_CONFIG]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={"code": "LLM_KEY_UNKNOWN", "message": f"不支持的配置项：{', '.join(unknown)}"},
        )
    merged = {**llm_config(db), **payload.values}
    try:
        validate_config(merged)
    except LlmError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    saved = set_setting(db, "llm", merged)
    log_user_action(
        db, user, "agents.llm_config", "llm", "config",
        detail={"enabled": merged.get("enabled"), "model": merged.get("model"),
                "base_url": merged.get("base_url"), "internal_only": merged.get("internal_only")},
    )
    db.commit()
    return {"config": saved, "credential_present": bool(os.getenv(str(merged.get("api_key_env") or "")))}


@router.post("/llm/test")
def llm_test(
    payload: LlmTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings:read")),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "ABAC_DENIED", "message": "仅系统管理员可测试模型连接"})
    try:
        return test_connection(db, payload.values)
    except LlmError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/run", status_code=202)
def run(
    payload: RunScenarioRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("agents:run")),
):
    """编排改为后台任务：全量重排可能跑几十秒，占着一次 HTTP 请求既会被网关超时掐断，
    也会让同进程的其它请求排队。这里只入队，前端轮询 /api/jobs/{id}，成功后取 run_id。"""
    if payload.scenario not in supported_scenarios():
        raise HTTPException(
            status_code=400,
            detail={"code": "AGENT_RUN_INVALID", "message": f"不支持的编排场景：{payload.scenario}"},
        )
    if payload.scenario == "change" and not payload.change_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "AGENT_RUN_INVALID", "message": "变更协同重排必须指定扰动事件"},
        )
    job = job_queue.enqueue(
        db, "agent.run",
        {"scenario": payload.scenario, "change_id": payload.change_id, "options": payload.options},
        user=user,
    )
    return {"job": job_queue.job_to_dict(job), "run": None}


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
    return _with_plans(db, agent_run_to_dict(run_obj, include_steps=True))
