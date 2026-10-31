from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import AgentRun, Approval, Disturbance, Operation, Order, Plan, User
from .audit import log_user_action
from .impact import TYPE_LABEL, assess_disturbance, create_change_plans, create_disturbance
from .kits import persist_check
from .quality import quality_summary
from .scheduler import create_plan_batch, generate_schedule, save_plan
from .serializers import agent_run_to_dict
from .settings import get_setting

AGENTS = [
    {"code": "C-01", "name": "全厂智能排产总控", "level": "C", "duty": "MPS 拉动平衡、多目标宏观排程、夜间全量重排、版本基线管理", "permission": "可写基线（须终审 + 电子签名）", "skills": ["MPS 拉动平衡", "Pareto 扫描", "模糊满意度终选"]},
    {"code": "C-02", "name": "跨厂产能协同", "level": "C", "duty": "跨厂 / 外协基地异步协商、阈值 SLA 协商状态机", "permission": "协同方案须双方调度长电子签名", "skills": ["异步协商状态机", "ABAC 脱敏交换", "PROV-O 血缘"]},
    {"code": "M-01", "name": "机加—热表链式协调", "level": "M", "duty": "链式约束传播、转运批量与时窗仲裁、涟漪影响初算", "permission": "只读 + 编排建议", "skills": ["链式约束传播", "转运批量仲裁"]},
    {"code": "M-02", "name": "装配—试车联动", "level": "M", "duty": "装配完工事件→台架窗口匹配→交接确认状态机", "permission": "只读 + 编排建议", "skills": ["台架窗口匹配", "两装两试回路"]},
    {"code": "M-03", "name": "齐套检查", "level": "M", "duty": "九要素三时点自动校验、缺口归因、处置推荐", "permission": "不齐套硬阻断", "skills": ["九要素校验", "缺口归因", "处置推荐"]},
    {"code": "M-04", "name": "变更影响面评估", "level": "M", "duty": "图谱涟漪双向推演、延误量化、A/B 双方案", "permission": "只读 + 编排建议", "skills": ["图谱涟漪推演", "A/B 方案生成", "SLA 升级"]},
    {"code": "M-05", "name": "锻造—钣金外协协调", "level": "M", "duty": "外协 ETA 预测、延误分级预警、替代产能匹配", "permission": "替代产能须审批", "skills": ["ETA 生存分析", "替代产能匹配"]},
    {"code": "M-06", "name": "特殊过程联动", "level": "M", "duty": "检测窗口预约、有效期跨工序校验、违规阻断", "permission": "违规硬阻断不可人工放行", "skills": ["有效期校验", "检测窗口优化"]},
    {"code": "A-00", "name": "数据点检与产能核算", "level": "A", "duty": "五维点检门禁、缺口归因、产能核算、瓶颈台账", "permission": "只读", "skills": ["五维点检", "产能核算", "瓶颈识别"]},
    {"code": "A-01", "name": "锻造排产", "level": "A", "duty": "组批合炉、加热炉排程、锻造节拍优化", "permission": "只读建议，输出 A/B/C 三方案", "skills": ["组批合炉", "换型优化"]},
    {"code": "A-02", "name": "机加排产", "level": "A", "duty": "作业序列、换型优化、瓶颈保护、齐套联动", "permission": "只读建议，输出 A/B/C 三方案", "skills": ["作业排序", "换型优化", "瓶颈保护"]},
    {"code": "A-03", "name": "表面热处理排产", "level": "A", "duty": "组批合炉、工艺曲线约束、有效期管控", "permission": "只读建议，输出 A/B/C 三方案", "skills": ["合炉优化", "特殊过程有效期"]},
    {"code": "A-04", "name": "钣金焊接排产", "level": "A", "duty": "模具匹配、焊接资质约束、外协联动", "permission": "只读建议，输出 A/B/C 三方案", "skills": ["模具匹配", "焊接资质校验"]},
    {"code": "A-05", "name": "装配排产", "level": "A", "duty": "齐套联动、部装/总装节拍、军检节点匹配", "permission": "只读建议，输出 A/B/C 三方案", "skills": ["齐套联动", "节拍平衡"]},
    {"code": "A-06", "name": "试车排产", "level": "A", "duty": "台架窗口、试车队列、返工回路编排", "permission": "只读建议，输出 A/B/C 三方案", "skills": ["台架排程", "返工回路"]},
    {"code": "A-07", "name": "大修排产", "level": "A", "duty": "区间排程、分解检查、维修 ETA 预测", "permission": "只读建议，输出 A/B/C 三方案", "skills": ["区间排程", "维修 ETA 生存分析"]},
]

LEVEL_LABEL = {"C": "化合物级 · 全厂总控", "M": "分子级 · 跨工序协调", "A": "原子级 · 单工序排产"}

DOMAIN_AGENT = {
    "锻造": "A-01", "机加": "A-02", "热表": "A-03", "钣焊": "A-04",
    "装配": "A-05", "试车": "A-06", "大修": "A-07",
}

TYPE_AGENT = {
    "fault": "M-01", "material": "M-05", "insert": "M-04", "rework": "M-02",
    "order_change": "M-04", "inspection": "M-06", "ecn": "M-04",
}

TYPE_SEVERITY = {
    "fault": "critical", "material": "warning", "insert": "critical", "rework": "warning",
    "order_change": "warning", "inspection": "warning", "ecn": "critical",
}

TYPE_DEFAULT_TITLE = {
    "fault": "关键设备突发故障",
    "material": "主材到料延误",
    "insert": "军品紧急插单",
    "rework": "探伤不合格返工",
    "order_change": "客户交期变更",
    "inspection": "军检窗口调整",
    "ecn": "工艺变更 ECN 生效",
}


def agent_catalog(db: Session) -> dict:
    runs = db.query(AgentRun).order_by(AgentRun.started_at.desc()).all()
    by_agent: dict[str, list[AgentRun]] = {}
    for run in runs:
        by_agent.setdefault(run.agent_code, []).append(run)
    now = datetime.now()
    agents = []
    for agent in AGENTS:
        recent = by_agent.get(agent["code"], [])
        last = recent[0] if recent else None
        recent_cutoff = now - timedelta(minutes=10)
        status = "idle"
        if last and last.started_at >= recent_cutoff:
            status = "active"
        elif last and last.status == "failed":
            status = "degraded"
        else:
            status = "online"
        simulated = [r.output.get("simulated_minutes", 0) for r in recent if r.output]
        agents.append(
            {
                **agent,
                "level_label": LEVEL_LABEL[agent["level"]],
                "status": status,
                "runs": len(recent),
                "success_rate": round(
                    sum(1 for r in recent if r.status == "succeeded") / len(recent) * 100, 1
                ) if recent else 100.0,
                "avg_minutes": round(sum(simulated) / len(simulated), 1) if simulated else 0,
                "last_run_at": last.started_at.isoformat() if last else None,
                "last_summary": last.summary if last else "待命",
            }
        )
    return {
        "levels": [
            {"level": "C", "label": LEVEL_LABEL["C"], "count": sum(1 for a in agents if a["level"] == "C")},
            {"level": "M", "label": LEVEL_LABEL["M"], "count": sum(1 for a in agents if a["level"] == "M")},
            {"level": "A", "label": LEVEL_LABEL["A"], "count": sum(1 for a in agents if a["level"] == "A")},
        ],
        "agents": agents,
        "recent_runs": [agent_run_to_dict(r) for r in runs[:24]],
        "summary": {
            "total": len(agents),
            "active": sum(1 for a in agents if a["status"] == "active"),
            "online": sum(1 for a in agents if a["status"] in ("online", "active")),
            "total_runs": len(runs),
        },
    }


def _step(idx: int, phase: str, title: str, thought: str, action: str, observation: str, duration_ms: int, status: str = "done") -> dict:
    return {
        "index": idx,
        "phase": phase,
        "title": title,
        "thought": thought,
        "action": action,
        "observation": observation,
        "duration_ms": duration_ms,
        "status": status,
    }


def _make_run(db: Session, user: User, agent_code: str, scenario: str, steps: list[dict], output: dict, summary: str, simulated_minutes: float, plan_id: int | None = None) -> AgentRun:
    agent = next((a for a in AGENTS if a["code"] == agent_code), AGENTS[0])
    now = datetime.now().replace(microsecond=0)
    code = f"AR-{now:%Y%m%d%H%M%S}-{agent_code}-{uuid.uuid4().hex[:4].upper()}"
    run = AgentRun(
        code=code,
        agent_code=agent["code"],
        agent_name=agent["name"],
        level=agent["level"],
        scenario=scenario,
        status="succeeded",
        summary=summary,
        inputs={},
        steps=steps,
        output={**output, "simulated_minutes": simulated_minutes},
        plan_id=plan_id,
        operator=user.name,
        started_at=now - timedelta(minutes=simulated_minutes),
        ended_at=now,
        duration_ms=int(simulated_minutes * 60_000),
    )
    db.add(run)
    db.flush()
    log_user_action(
        db, user, "agent.run", "agent_run", run.code,
        detail={
            "agent": agent_code,
            "scenario": scenario,
            "simulated_minutes": simulated_minutes,
            "plans": output.get("plans", []),
            "status": "succeeded",
        },
    )
    return run


def run_scenario(db: Session, user: User, scenario: str, change_id: int | None = None, options: dict | None = None) -> AgentRun:
    options = options or {}
    if scenario in ("full", "night"):
        return _run_full(db, user)
    if scenario == "kit":
        return _run_kit(db, user, options)
    if scenario == "local":
        return _run_local(db, user, options)
    if scenario == "change":
        change = db.get(Disturbance, change_id) if change_id else None
        if not change:
            raise ValueError("变更事件不存在")
        return _run_change(db, user, change)
    if scenario in TYPE_LABEL:
        change = create_disturbance(
            db,
            scenario,
            options.get("title") or TYPE_DEFAULT_TITLE.get(scenario, TYPE_LABEL[scenario]),
            options.get("detail", ""),
            options.get("severity") or TYPE_SEVERITY.get(scenario, "warning"),
            options.get("payload", {}),
            reporter=user.name,
        )
        return _run_change(db, user, change)
    raise ValueError(f"不支持的编排场景：{scenario}")


def _run_full(db: Session, user: User) -> AgentRun:
    quality = quality_summary(db)
    pending = db.query(Plan).filter(Plan.status == "pending").all()
    for plan in pending:
        plan.status = "expired"
    if pending:
        db.query(Approval).filter(
            Approval.plan_id.in_([p.id for p in pending]), Approval.status == "pending"
        ).update({Approval.status: "cancelled"}, synchronize_session=False)

    plans = create_plan_batch(db, user, plan_type="full", scenarios=("A", "B", "C"))
    a_plan = plans[0]
    hard = a_plan.summary.get("hard_checks", [])
    hard_failed = sum(1 for c in hard if not c.get("passed"))
    late = a_plan.kpi.get("late_orders", 0)
    codes = " / ".join(p.code for p in plans)
    steps = [
        _step(1, "感知", "读取 MPS 与订单快照",
              "夜间全量重排窗口开启，需要先固化当日计划输入快照，避免重排过程中数据漂移。",
              "mcp.query_production_orders(plant=ALL, status=OPEN)",
              f"读取 {a_plan.kpi.get('orders', 0)} 个在制订单、{a_plan.kpi.get('operations', 0)} 道工序，输入快照已锁定。", 8400),
        _step(2, "记忆", "召回调度员偏好与历史基线",
              "需要带入军品保供偏好、冻结窗口与上次基线，保证重排结果可解释且不破坏稳定区。",
              "memory.recall(scope=调度员偏好 + baseline_version)",
              "召回 P0 军品优先、冻结窗口 3 天、瓶颈保护权重；锁定工序保持不动。", 2200),
        _step(3, "点检", "L0 五维点检门禁",
              "R002 要求五维点检全部 ≥90%，否则禁止进入排产链路。",
              "tool.check_data_quality(dimensions=5)",
              f"综合得分 {quality['overall']}%，门禁：{quality['gate']['label']}。", 3600),
        _step(4, "齐套", "九要素三时点校验",
              "M-03 在排产前/后/开工前三个时点校验工装、主材、资质等九要素。",
              "mcp.kit_check(checkpoint=post_schedule)",
              "齐套基线已刷新，缺口订单进入 SC-05 软约束与风险标记。", 5200),
        _step(5, "规划", "任务分解与约束护栏预检",
              "将全量重排拆解为七大工序域子任务，先做 HC-01~14 预检，防止不可行解进入求解器。",
              "planning.decompose(domains=7) + guardrail.precheck()",
              "生成 7 个域子任务，硬约束预检通过，进入多目标求解。", 4100),
        _step(6, "求解", "三方案多目标求解",
              "采用 ε 约束锁军品交期，再做字典序可行性修复、加权求和与 Pareto 扫描，输出 A/B/C 候选。",
              "solver.solve(horizon=full, scenarios=[A,B,C], timeout=15s)",
              f"生成 {codes}，A 方案准时率 {a_plan.kpi.get('on_time_rate')}%，逾期 {late} 单。", 3_180_000),
        _step(7, "校验", "SHACL 硬约束 + 规则引擎双校验",
              "任何数学最优解都必须通过业务硬约束，否则不得呈现给调度员。",
              "shacl.validate(HC-01~14) + rules.evaluate(R001~R068)",
              f"硬约束违规 {hard_failed} 项，软约束命中 {len(a_plan.summary.get('soft_violations', []))} 类。", 9600),
        _step(8, "归因", "白盒归因与 A/B 取舍",
              "为每个方案生成命中规则、约束与取舍说明，满足军工可解释要求。",
              "explain.attribution(plan_id=%s)" % a_plan.code,
              "归因链已生成：交期优先、瓶颈保护、冻结窗口稳定、换型成本。", 3400),
        _step(9, "决策", "提交 A/B/C 方案至审批通道",
              "C 级可写基线，但必须经计划员择优、生产指挥部终审与电子签名，写保护网关拦截未授权写入。",
              "approval.create(batch=%s, deadline=15min)" % a_plan.batch_id,
              f"3 个方案已提交终审，15 分钟内未审将按 R009 自动升级。", 1800),
    ]
    output = {
        "plans": [
            {"id": p.id, "code": p.code, "scenario": p.scenario, "objective": p.objective, "score": p.kpi.get("total_score"), "status": p.status}
            for p in plans
        ],
        "kpi": a_plan.kpi,
        "hard_failed": hard_failed,
        "quality": quality["overall"],
        "kit_rate": a_plan.summary.get("kit_risk", 0),
    }
    return _make_run(
        db, user, "C-01", "full", steps, output,
        f"夜间全量重排完成：{a_plan.kpi.get('orders')} 单 / {a_plan.kpi.get('operations')} 工序，A 方案准时率 {a_plan.kpi.get('on_time_rate')}%",
        106.4, a_plan.id,
    )


def _run_change(db: Session, user: User, change: Disturbance) -> AgentRun:
    impact = assess_disturbance(db, change)
    plans = create_change_plans(db, user, change, scenarios=("A", "B"))
    agent_code = TYPE_AGENT.get(change.type, "M-04")
    summary = impact["summary"]
    codes = " / ".join(p.code for p in plans)
    steps = [
        _step(1, "感知", "扰动事件接入事件总线",
              "口头/邮件变更不构成排产依据，先校验事件是否完整录入（R001）。",
              f"event.ingest(type={change.type})",
              f"事件 {change.code} 已入库，等级 {change.severity}，进入 M-04 影响评估。", 1200),
        _step(2, "推演", "图谱涟漪双向推演",
              "沿工序依赖 DAG 与装配树双向推演，识别受影响工单、工序与交付节点。",
              "graph.ripple(resource=%s, depth=all)" % change.payload.get("resource_name", "cross-chain"),
              f"影响 {summary['affected_orders']} 个订单、{summary['affected_operations']} 道工序，覆盖 {len(summary['domains'])} 个工序域。", 6800),
        _step(3, "量化", "延误量化与军品风险判定",
              "量化交期延误、瓶颈占用与军品风险，防止把外部不确定性当成零值。",
              "impact.quantify(confidence=0.93)",
              f"平均延误 {summary['avg_delay_days']} 天，P0 订单 {summary['critical_orders']} 个，置信度 93%。", 3400),
        _step(4, "求解", "局部重排 A/B 方案",
              "只重排受影响链路，保留冻结窗口，生成协同重排与原地顺延双方案。",
              "solver.solve(scope=impacted, scenarios=[A,B])",
              f"生成 {codes}；A 方案吸收约 72% 延误，B 方案保持基线稳定。", 465_000),
        _step(5, "校验", "硬约束复核与有效期校验",
              "变更后重新执行 SHACL 硬约束与特殊过程有效期校验，违规方案不得提交。",
              "shacl.revalidate() + valid_until.check()",
              "硬约束全部通过，特殊过程有效期无冲突。", 3900),
        _step(6, "决策", "提交择优审批",
              "A/B 方案与影响面一并提交，15 分钟未审自动升级。",
              "approval.create(scope=change, deadline=15min)",
              f"变更 {change.code} 已生成待审批方案，影响面报告已归档。", 1500),
    ]
    output = {
        "change": {
            "id": change.id, "code": change.code, "type": change.type,
            "type_label": TYPE_LABEL.get(change.type, change.type),
            "status": change.status, "title": change.title,
        },
        "impact": impact["summary"],
        "plans": [
            {"id": p.id, "code": p.code, "scenario": p.scenario, "objective": p.objective, "score": p.kpi.get("total_score"), "status": p.status}
            for p in plans
        ],
    }
    return _make_run(
        db, user, agent_code, "change", steps, output,
        f"{TYPE_LABEL.get(change.type, change.type)}影响评估完成：{summary['affected_orders']} 单受影响，A/B 方案待审批",
        summary["elapsed_minutes"], plans[0].id if plans else None,
    )


def _run_kit(db: Session, user: User, options: dict) -> AgentRun:
    order_id = options.get("order_id")
    order = db.get(Order, int(order_id)) if order_id else (
        db.query(Order).filter(~Order.status.in_(["已完工", "已取消"])).order_by(Order.priority.asc(), Order.due_date.asc()).first()
    )
    if not order:
        raise ValueError("无可用订单执行齐套检查")
    checks = [persist_check(db, order, cp) for cp in ("pre_schedule", "post_schedule", "pre_start")]
    blocked = next((c for c in checks if c.status == "阻断"), None)
    gap_count = sum(len(c.gaps) for c in checks)
    steps = [
        _step(1, "触发", "齐套检查三时点触发",
              "M-03 在排产前、排产后、开工前三个时点执行九要素校验，任何时点缺口都要归因。",
              f"kit.trigger(order={order.order_no})",
              f"订单 {order.order_no} 三时点校验已启动。", 800),
        _step(2, "读取", "九要素多源取数",
              "从 MES/WMS/ERP/QMS/PLM/HR 六类系统读取工装、主材、辅材、刀具、路线、资质、WIP、设备状态与能力。",
              "mcp.batch_read(systems=6, elements=9)",
              f"九要素快照读取完成，最新检查得分 {checks[-1].score}%。", 2200),
        _step(3, "归因", "缺口归因与责任分派",
              "对缺口做要素归因、责任部门匹配和处置时限建议，避免只报缺口不给动作。",
              "kit.attribute_gaps()",
              f"发现 {gap_count} 项缺口，已分派工装室/采购部/质量部等责任部门。", 1700),
        _step(4, "决策", "阻断/放行判定",
              "开工前关键要素缺口执行硬阻断，不可人工放行；其他时点缺口进入风险标记。",
              "kit.gate(checkpoint=pre_start, strict=true)",
              "开工前存在关键缺口，已硬阻断并生成处置单。" if blocked else "关键要素齐套，允许放行至开工。", 900),
    ]
    output = {
        "order": {"id": order.id, "order_no": order.order_no, "product_name": order.product_name},
        "checks": [
            {"checkpoint": c.checkpoint, "status": c.status, "score": c.score, "gaps": len(c.gaps)}
            for c in checks
        ],
        "blocked": bool(blocked),
    }
    return _make_run(
        db, user, "M-03", "kit", steps, output,
        f"齐套检查完成：{order.order_no}，{checks[-1].status}，缺口 {gap_count} 项",
        3.2,
    )


def _run_local(db: Session, user: User, options: dict) -> AgentRun:
    domain = options.get("domain", "机加")
    agent_code = DOMAIN_AGENT.get(domain, "A-02")
    orders = (
        db.query(Order)
        .filter(Order.id.in_(
            db.query(Operation.order_id).filter(Operation.domain == domain)
        ))
        .filter(~Order.status.in_(["已完工", "已取消"]))
        .limit(24)
        .all()
    )
    result = generate_schedule(db, scenario=options.get("scenario", "A"), freeze=True, orders=orders or None)
    plan = save_plan(db, result, plan_type="incremental", created_by=user.name, status="draft")
    kpi = plan.kpi
    steps = [
        _step(1, "感知", f"{domain}域订单与资源感知",
              "原子级只读建议，必须先读取本域资源池状态与齐套状态。",
              "mcp.query_resource_pool(domain=%s)" % domain,
              f"读取 {kpi.get('orders', 0)} 单、{kpi.get('operations', 0)} 道工序，资源状态正常。", 1200),
        _step(2, "核算", "产能核算与瓶颈识别",
              "A-00 对本域产能与负荷做核算，识别瓶颈资源与溢出工序。",
              "capacity.calc(domain=%s)" % domain,
              f"平均负荷 {kpi.get('avg_utilization')}%，瓶颈利用率 {kpi.get('bottleneck_utilization')}%。", 2100),
        _step(3, "求解", "原子级局部排产建议",
              "在冻结窗口约束下生成本域建议排程，输出 A/B/C 三方案供上层协调。",
              "solver.solve(scope=%s, scenarios=[A,B,C])" % domain,
              f"建议方案 {plan.code} 已生成，准时率 {kpi.get('on_time_rate')}%。", 1_620_000),
        _step(4, "校验", "硬约束与规则复核",
              "原子级输出同样必须通过 HC 硬约束与规则引擎，只读建议不得绕过。",
              "shacl.validate() + rules.evaluate()",
              f"硬约束违规 {sum(1 for c in plan.summary.get('hard_checks', []) if not c.get('passed'))} 项。", 1800),
        _step(5, "输出", "只读建议归档",
              "A 级智能体不得写基线，建议方案归档给 M/C 级协调与调度员参考。",
              "output.archive(status=draft)",
              "建议方案已归档，等待 M 级协调或人工采纳。", 600),
    ]
    output = {
        "domain": domain,
        "plan": {"id": plan.id, "code": plan.code, "scenario": plan.scenario, "status": plan.status},
        "kpi": kpi,
    }
    return _make_run(
        db, user, agent_code, "local", steps, output,
        f"{domain}域局部排产建议完成：{kpi.get('orders')} 单，准时率 {kpi.get('on_time_rate')}%",
        27.0, plan.id,
    )
