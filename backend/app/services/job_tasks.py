from __future__ import annotations

"""已登记的后台任务处理器。

在这里 import 的模块才会被注册进队列。加新任务 = 写一个 @jobs.handler 函数，
入队端点做参数校验，别把「谁都能拼出来的 SQL/路径」放进 payload。

任务结果里只放引用（id / code / 计数）与聚合口径，不放被密级保护的正文字段——
读取方案、工单本身仍然走各自端点的密级过滤，队列不是第二条绕过通道。
"""

from sqlalchemy.orm import Session

from ..models import Job, Plan, User
from . import jobs
from .adapters import AdapterError, run_due
from .agents import run_scenario
from .audit import log_user_action
from .kit_data import KitDataError


def _actor(db: Session, job: Job) -> User:
    user = db.get(User, job.actor_id) if job.actor_id else None
    if user is None:
        raise jobs.JobError("JOB_ACTOR_MISSING", "任务发起人不存在或已被停用，后台拒绝以匿名身份执行排产")
    return user


@jobs.handler("agent.run")
def agent_run(db: Session, job: Job) -> dict:
    """一次智能体编排：把原来卡在 HTTP 请求里的重排挪到后台跑。"""
    user = _actor(db, job)
    payload = job.payload or {}
    scenario = str(payload.get("scenario") or "")
    if not scenario:
        raise jobs.JobError("AGENT_SCENARIO_MISSING", "任务缺少编排场景")
    jobs.heartbeat(db, job, 15)
    agent_run_row = run_scenario(
        db, user, scenario,
        int(payload["change_id"]) if payload.get("change_id") else None,
        payload.get("options") or {},
    )
    jobs.heartbeat(db, job, 80)
    db.commit()
    db.refresh(agent_run_row)
    plan_ids = [p.get("id") for p in (agent_run_row.output or {}).get("plans", []) if p.get("id")]
    plans = db.query(Plan).filter(Plan.id.in_(plan_ids)).all() if plan_ids else []
    return {
        "run_id": agent_run_row.id,
        "code": agent_run_row.code,
        "agent_code": agent_run_row.agent_code,
        "scenario": agent_run_row.scenario,
        "status": agent_run_row.status,
        "summary": agent_run_row.summary,
        "plan_ids": [p.id for p in plans],
        "plan_codes": [p.code for p in plans],
    }


@jobs.handler("adapter.pull")
def adapter_pull(db: Session, job: Job) -> dict:
    """把到点的外部通道同步搬进队列：跑一次可能几十秒，不该占着一次 HTTP 请求。"""
    user = _actor(db, job)
    summary = run_due(db, user, force=bool((job.payload or {}).get("force")))
    ran = summary.get("ran") or []
    failed = [item for item in ran if item.get("error")]
    log_user_action(
        db, user, "job.adapter_pull", "job", str(job.id),
        detail={"ran": len(ran), "failed": len(failed), "sources": [item.get("name") for item in ran]},
    )
    db.commit()
    if failed and not ran:
        raise jobs.JobError("ADAPTER_ALL_FAILED", f"{len(failed)} 个通道同步失败")
    return {
        "ran": len(ran),
        "failed": len(failed),
        "sources": [{"name": item.get("name"), "rows": item.get("rows"), "error": item.get("error")} for item in ran],
    }


# 处理器里可能抛出的异常类型，供 worker 日志区分「业务拒绝」与「代码 bug」
BUSINESS_ERRORS = (AdapterError, KitDataError, ValueError)
