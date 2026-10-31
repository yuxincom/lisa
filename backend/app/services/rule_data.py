from __future__ import annotations

PLAN_RULES = [
    {
        "code": "R001", "category": "计划拉动", "title": "异常事件必须系统录入",
        "description": "插单、故障、缺料、ECN、军检等扰动必须通过事件总线录入，口头/微信/邮件不作为排产依据。",
        "priority": 10, "trigger": "发生扰动事件", "action": "阻断人工口头变更，要求补录事件后进入影响评估", "domain": "全厂",
    },
    {
        "code": "R002", "category": "计划拉动", "title": "L0 五维点检门禁",
        "description": "完整性/及时性/一致性/准确性/唯一性均≥90%方可进入排产链路。",
        "priority": 10, "trigger": "每次全量/增量排产前", "action": "未达标阻断排产并生成数据整改单", "domain": "全厂",
    },
    {
        "code": "R003", "category": "计划拉动", "title": "齐套三时点校验",
        "description": "排产前、排产后、开工前三个时点对九要素齐套状态自动校验。",
        "priority": 10, "trigger": "计划生成/开工前置", "action": "缺项硬阻断，缺口归因并推送处置建议", "domain": "齐套",
    },
    {
        "code": "R004", "category": "计划拉动", "title": "MPS 拉动平衡",
        "description": "月计划经 MPS/MRP 拉平后驱动周计划，禁止各工序自行放大投料。",
        "priority": 9, "trigger": "月/周计划发布", "action": "按拉动平衡结果锁定投料节奏", "domain": "全厂",
    },
    {
        "code": "R005", "category": "计划拉动", "title": "周滚动 3 锁 1 下发 3 展望",
        "description": "前 3 天冻结、锁定期内不调整；1 天正式下发、3 天滚动展望。",
        "priority": 9, "trigger": "每周滚动排产", "action": "冻结窗口内工单保持基线，窗外重排", "domain": "全厂",
    },
    {
        "code": "R006", "category": "计划拉动", "title": "锁定期调整审批",
        "description": "冻结窗口内调整必须走审批，且留下调整原因与电子签名。",
        "priority": 9, "trigger": "冻结窗口调整申请", "action": "提交生产指挥部终审，未批不得写入 APS", "domain": "全厂",
    },
    {
        "code": "R007", "category": "计划拉动", "title": "排产基线版本留痕",
        "description": "每次排产生成不可变版本，基线切换保留新旧差分与归因。",
        "priority": 8, "trigger": "方案发布", "action": "写入版本库并挂载 PROV-O 血缘", "domain": "全厂",
    },
    {
        "code": "R008", "category": "计划拉动", "title": "方案白盒归因",
        "description": "方案必须输出命中规则、约束、目标权重与 A/B 取舍说明。",
        "priority": 8, "trigger": "方案生成", "action": "缺失归因的方案不得提交审批", "domain": "全厂",
    },
    {
        "code": "R009", "category": "计划拉动", "title": "终审 15min 自动升级",
        "description": "方案审批 15 分钟未决自动升级至厂长/生产指挥部。",
        "priority": 8, "trigger": "审批超时", "action": "自动升级并发送致命级提醒", "domain": "全厂",
    },
    {
        "code": "R010", "category": "计划拉动", "title": "实绩回传偏差回流",
        "description": "T+1 将实绩与计划偏差回流影子数据集，用于模型与规则回校。",
        "priority": 7, "trigger": "每日 06:00", "action": "计算偏差并更新影子库，触发异常归因", "domain": "评测",
    },
]

DISTURBANCE_TYPES = [
    {
        "prefix": "GZ", "label": "设备故障", "priority": 9, "severity": "critical",
        "trigger": "MES 设备状态 / EAM 保养日历", "action": "锁定故障设备产能，启用备选资源并局部重排",
    },
    {
        "prefix": "WL", "label": "物料缺料", "priority": 8, "severity": "warning",
        "trigger": "WMS 库存 / 到料 ETA / BOM", "action": "齐套阻断，触发替代料、外协或顺延方案",
    },
    {
        "prefix": "CJ", "label": "紧急插单", "priority": 10, "severity": "critical",
        "trigger": "军品急件 / 临时订单录入", "action": "按 P0 优先级抢占并评估全链涟漪影响",
    },
    {
        "prefix": "FG", "label": "返工返修", "priority": 7, "severity": "warning",
        "trigger": "QMS 检测结论 / 探伤不合格", "action": "激活两装两试回路并生成返工工单",
    },
    {
        "prefix": "DD", "label": "订单变更", "priority": 7, "severity": "warning",
        "trigger": "ERP 交期 / 数量 / 客户变更", "action": "重算交期影响面并生成 A/B 应对方案",
    },
    {
        "prefix": "TS", "label": "检测军检", "priority": 8, "severity": "warning",
        "trigger": "QMS 检测结论 / 军检窗口日历", "action": "预约检测窗口，联动装配试车与交付节点",
    },
    {
        "prefix": "ECN", "label": "工艺变更", "priority": 8, "severity": "critical",
        "trigger": "PLM ECN 生效 / 工艺版本切换", "action": "执行断点排查、版本切换与双签确认",
    },
]

ASPECTS = [
    ("事件分级与录入", "按影响范围与军品属性自动分级，仅系统录入事件有效。"),
    ("影响面评估", "沿工序依赖图谱推演受影响工单、工序与交付节点。"),
    ("触发阈值", "满足阈值自动触发评估，不依赖人工电话通知。"),
    ("响应时限", "在 SLA 内完成评估与处置建议，超时自动升级。"),
    ("处置策略", "输出协同重排 / 原地顺延 / 替代资源等可选策略。"),
    ("升级路径", "重大影响升级至生产指挥部并直达调度室。"),
    ("审批要求", "涉及基线写入需电子签名审批，未审批不得写入。"),
    ("留痕复盘", "全链路留痕，纳入月度规则评分卡复盘。"),
]


def _build_disturbance_rules() -> list[dict]:
    rules: list[dict] = []
    code_no = 11
    for kind in DISTURBANCE_TYPES:
        for idx, (aspect, aspect_desc) in enumerate(ASPECTS, start=1):
            rules.append(
                {
                    "code": f"R{code_no:03d}",
                    "category": f"扰动-{kind['label']}",
                    "title": f"{kind['label']}·{aspect}",
                    "description": f"{aspect_desc} 触发源：{kind['trigger']}。",
                    "priority": max(1, kind["priority"] - (1 if idx > 5 else 0)),
                    "trigger": kind["trigger"],
                    "action": kind["action"],
                    "domain": kind["label"],
                }
            )
            code_no += 1
    return rules


EXTRA_RULES = [
    {
        "code": "R067", "category": "扰动-工艺变更", "title": "ECN 断点排查",
        "description": "ECN 生效时对在制、待制、已完工三类工单做断点排查，确定换版边界与返工范围。",
        "priority": 9, "trigger": "ECN 发布", "action": "输出断点清单与换版方案，双签后执行", "domain": "工艺变更",
    },
    {
        "code": "R068", "category": "扰动-工艺变更", "title": "ECN 归档与版本回滚",
        "description": "ECN 处理完成后归档至知识库并保留版本快照，异常时 10 分钟内可回滚。",
        "priority": 7, "trigger": "ECN 关闭", "action": "归档血缘并演练回滚", "domain": "工艺变更",
    },
]

RULES = PLAN_RULES + _build_disturbance_rules() + EXTRA_RULES

HARD_CONSTRAINTS = [
    ("HC-01", "概念完备性", "本体 7 核心类与关键对象属性必须完整定义，缺失即阻断。"),
    ("HC-02", "实例完备性", "必填数据属性（优先级、交期、工时、资源）不得为空。"),
    ("HC-03", "值域约束", "枚举、密级、优先级、状态取值必须在受控值域内。"),
    ("HC-04", "三元组结构", "语义三元组主谓宾类型必须匹配，禁止悬空引用。"),
    ("HC-05", "业务闭环", "订单—零件—工序—资源链路必须闭环，工艺路线完整。"),
    ("HC-06", "设备参数值域", "设备能力、速度、温度等参数必须落在工艺允许范围。"),
    ("HC-07", "工时一致性 ±20%", "计划工时与标准工时偏差不得超过 ±20%，否则阻断。"),
    ("HC-08", "日历边界", "作业必须落在工作班次与法定日历内，禁止排入停机窗口。"),
    ("HC-09", "资源需求可满足", "工序资源类型必须与设备能力域匹配，禁止跨域占用。"),
    ("HC-10", "人员资质匹配", "关键工序操作人员资质必须覆盖工序要求。"),
    ("HC-11", "扰动分级一致", "扰动等级与处置路径、升级链路必须一致。"),
    ("HC-12", "工序依赖闭环", "后继工序不得早于前序完工 + 转运时间。"),
    ("HC-13", "技能覆盖度", "资源池技能覆盖度不足时不得形成排产结论。"),
    ("HC-14", "数量平衡", "在制、投料、产出数量必须平衡，禁止负库存。"),
]

SOFT_CONSTRAINTS = [
    ("SC-01", "交期优先", 0.35), ("SC-02", "瓶颈保护", 0.28), ("SC-03", "换型最少", 0.18),
    ("SC-04", "负荷均衡", 0.16), ("SC-05", "齐套优先", 0.30), ("SC-06", "军品保供", 0.32),
    ("SC-07", "冻结窗口稳定", 0.25), ("SC-08", "连续生产", 0.10), ("SC-09", "转运距离", 0.05),
    ("SC-10", "能耗优化", 0.06), ("SC-11", "人员均衡", 0.08), ("SC-12", "外协成本", 0.02),
    ("SC-13", "试车窗口", 0.22),
]
