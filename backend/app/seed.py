from __future__ import annotations

import os
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import (
    AgentRun,
    Alert,
    AuditLog,
    Approval,
    DataSource,
    Disturbance,
    KitCheck,
    Knowledge,
    Operation,
    Order,
    Plan,
    PlanItem,
    Product,
    QualitySnapshot,
    Resource,
    Rule,
    Setting,
    User,
)
from .security import hash_password
from .services.audit import append_audit
from .services.impact import assess_disturbance, create_change_plans, relabel_disturbance_clearance
from .services.kit_data import upsert_rows
from .services.kits import persist_check
from .services.rule_data import HARD_CONSTRAINTS, RULES, SOFT_CONSTRAINTS
from .services.scheduler import generate_schedule, save_plan
from .services.settings import DEFAULT_SETTINGS

RNG = random.Random(20261031)
NOW = datetime.now().replace(second=0, microsecond=0)

USERS = [
    ("admin", "admin123", "系统管理员 · 赵磊", "admin", "机密", "信息中心", "#8b7cf6"),
    ("commander", "commander123", "生产指挥部 · 王振国", "commander", "机密", "生产指挥部", "#f0a83c"),
    ("planner", "planner123", "计划员 · 李静", "planner", "内部", "生产运营部", "#4f9dff"),
    ("dispatcher", "dispatcher123", "调度员 · 陈涛", "dispatcher", "内部", "调度室", "#38d6c0"),
    ("engineer", "engineer123", "工艺员 · 周敏", "engineer", "内部", "工艺部", "#f472b6"),
    ("expert", "expert123", "领域专家 · 孙工", "expert", "机密", "技术专家委", "#fbbf24"),
]

FAMILIES = [
    ("高压涡轮叶片", "关键件", 0.32),
    ("低压涡轮盘", "关键件", 0.30),
    ("压气机机匣", "重要件", 0.26),
    ("燃烧室火焰筒", "关键件", 0.34),
    ("加力筒体", "重要件", 0.24),
    ("主轴组件", "关键件", 0.36),
    ("传动齿轮箱", "重要件", 0.22),
    ("燃油喷嘴", "一般件", 0.18),
    ("密封环组件", "一般件", 0.16),
    ("机匣前段", "重要件", 0.24),
    ("涡轮导向器", "关键件", 0.30),
    ("尾喷管组件", "一般件", 0.20),
]

DOMAIN_ROUTES = {
    "锻造": [
        ("下料", 140, 30, False), ("镦粗", 220, 40, False), ("模锻成型", 280, 70, True),
    ],
    "机加": [
        ("粗车", 180, 30, False), ("精车", 210, 30, False), ("铣削", 160, 25, False),
        ("钻孔", 120, 20, False), ("镗削", 150, 25, False), ("磨削", 200, 35, False),
        ("去毛刺", 60, 10, False), ("尺寸检测", 50, 10, False), ("终检", 45, 10, False),
    ],
    "热表": [
        ("预热", 90, 20, False), ("真空热处理", 300, 60, True), ("表面强化", 180, 40, True),
        ("无损探伤", 90, 20, True),
    ],
    "钣焊": [
        ("钣金成形", 140, 25, False), ("真空焊接", 180, 45, True),
    ],
    "装配": [
        ("部装", 240, 30, False), ("总装", 300, 40, False), ("管路装配", 150, 20, False),
        ("电气装配", 120, 20, False), ("动平衡测试", 90, 15, False),
    ],
    "试车": [
        ("台架准备", 120, 30, False), ("试车运行", 360, 60, True), ("性能复测", 150, 25, True),
    ],
    "大修": [
        ("分解检查", 180, 30, False), ("修复装配", 240, 40, False),
    ],
}

RESOURCE_DEFS = [
    ("FRG", "锻造", "2000T 模锻压机", "一厂", 22, 0.91, True),
    ("FRG", "锻造", "1250T 模锻压机", "一厂", 20, 0.88, False),
    ("FRG", "锻造", "环轧机", "二厂", 20, 0.86, False),
    ("FRG", "锻造", "加热炉-01", "一厂", 24, 0.93, False),
    ("FRG", "锻造", "加热炉-02", "二厂", 24, 0.90, False),
    ("FRG", "锻造", "锻后冷却线", "一厂", 20, 0.89, False),
    ("MC", "机加", "五轴加工中心-DMC01", "一厂", 22, 0.92, True),
    ("MC", "机加", "五轴加工中心-DMC02", "一厂", 22, 0.90, True),
    ("MC", "机加", "数控车床-CK01", "一厂", 20, 0.89, False),
    ("MC", "机加", "数控车床-CK02", "二厂", 20, 0.87, False),
    ("MC", "机加", "精密磨床-MK01", "一厂", 20, 0.85, False),
    ("MC", "机加", "坐标镗床-TX01", "二厂", 18, 0.84, False),
    ("HT", "热表", "真空热处理炉-VHT01", "一厂", 24, 0.94, True),
    ("HT", "热表", "真空热处理炉-VHT02", "二厂", 24, 0.92, False),
    ("HT", "热表", "表面强化线-SP01", "一厂", 20, 0.88, False),
    ("HT", "热表", "无损探伤-NDT01", "一厂", 18, 0.86, False),
    ("HT", "热表", "无损探伤-NDT02", "二厂", 18, 0.85, False),
    ("HT", "热表", "清洗线-WS01", "一厂", 20, 0.90, False),
    ("SH", "钣焊", "真空焊接炉-VW01", "一厂", 20, 0.90, True),
    ("SH", "钣焊", "钣金成形机-BJ01", "二厂", 18, 0.86, False),
    ("SH", "钣焊", "激光焊-LW01", "一厂", 18, 0.88, False),
    ("SH", "钣焊", "氩弧焊-TIG01", "二厂", 18, 0.84, False),
    ("AS", "装配", "部装线-AS01", "一厂", 22, 0.92, False),
    ("AS", "装配", "总装线-AS02", "一厂", 22, 0.93, False),
    ("AS", "装配", "管路装配工位-AS03", "二厂", 20, 0.88, False),
    ("AS", "装配", "动平衡测试台-BAL01", "一厂", 18, 0.90, False),
    ("TS", "试车", "试车台-TB01", "二厂", 24, 0.94, True),
    ("TS", "试车", "试车台-TB02", "二厂", 24, 0.91, False),
    ("TS", "试车", "台架准备工位-TBP01", "二厂", 20, 0.89, False),
    ("OH", "大修", "大修分解线-OH01", "二厂", 20, 0.87, False),
    ("OH", "大修", "修复装配线-OH02", "二厂", 20, 0.86, False),
    ("OH", "大修", "探伤复检工位-OH03", "二厂", 18, 0.85, False),
]

# 演示用的并行机位数（同一资源条目代表几个可并行工位/机台）。
# 投产时这一列必须来自设备台账，见 docs/投产配置清单.md 的 A1/A2。
MACHINE_COUNTS = {
    "加热炉-01": 2,
    "加热炉-02": 2,
    "锻后冷却线": 2,
    "数控车床-CK01": 2,
    "数控车床-CK02": 2,
    "精密磨床-MK01": 2,
    "表面强化线-SP01": 2,
    "无损探伤-NDT01": 2,
    "无损探伤-NDT02": 2,
    "清洗线-WS01": 2,
    "钣金成形机-BJ01": 2,
    "激光焊-LW01": 2,
    "氩弧焊-TIG01": 3,
    "部装线-AS01": 2,
    "总装线-AS02": 3,
    "管路装配工位-AS03": 4,
    "台架准备工位-TBP01": 2,
    "大修分解线-OH01": 2,
    "修复装配线-OH02": 3,
    "探伤复检工位-OH03": 2,
}

# 齐套外部主数据的演示源（投产时由 ERP BOM / WMS 库存 / MES 工装刀具 / HR 技能矩阵 / QMS 检验结论
# 经导入通道或适配器写入，见 docs/投产配置清单.md 的 D 组）。
MATERIAL_LIB = {
    "高压涡轮叶片": (("DD99 单晶母合金", "kg", 6.5, 150), ("陶瓷型芯", "件", 24, 60)),
    "低压涡轮盘": (("GH4169 真空自耗锭", "kg", 42, 120), ("耐热垫片", "件", 12, 30)),
    "压气机机匣": (("Ti-6Al-4V 锻棒", "kg", 28, 90), ("密封环坯", "件", 18, 45)),
    "燃烧室火焰筒": (("Inconaloy 625 薄板", "kg", 9.5, 110), ("钎焊箔", "件", 30, 40)),
    "加力筒体": (("GH3536 板材", "kg", 16, 85), ("膨胀节组件", "件", 6, 50)),
    "主轴组件": (("12CrNi4HA 锻件", "kg", 55, 100), ("保持架", "件", 8, 35)),
    "传动齿轮箱": (("20CrMnTiH 锻环", "kg", 22, 75), ("油封", "件", 14, 25)),
    "燃油喷嘴": (("不锈钢精密铸件", "件", 4, 60), ("雾化芯", "件", 10, 30)),
    "密封环组件": (("镍基粉材", "kg", 3.2, 70), ("弹簧片", "件", 40, 20)),
    "机匣前段": (("铝合金锻坯", "kg", 18, 55), ("紧固件组", "件", 60, 15)),
    "涡轮导向器": (("K417 熔模铸件", "件", 12, 95), ("冷却套管", "件", 9, 40)),
    "尾喷管组件": (("钛合金焊接板", "kg", 24, 80), ("调节连杆", "件", 16, 35)),
}

KNOWLEDGE_ITEMS = [
    ("T1-001", "通识", "冻结窗口定义", "周计划前 3 天为冻结窗口，锁定工单原则上不调整；任何调整必须经审批并留电子签名。", "T1 术语库", ["冻结窗口", "周滚动", "锁定期"]),
    ("T1-002", "通识", "两装两试", "试车不合格后进入再装配—再试车返工回路，返工工单必须线上化并纳入不确定性排程。", "T1 术语库", ["两装两试", "返工"]),
    ("T1-003", "通识", "齐套九要素", "工装、主材、辅材、刀具、工艺路线、人员资质、WIP 质量状态、设备状态、设备能力。", "T1 术语库", ["齐套", "九要素"]),
    ("T2-001", "通识", "有限产能排产方法", "以资源日历、换型时间、人员资质与设备能力为约束，生成可执行的有限产能排程，禁止无限产能倒排。", "T2 方法库", ["有限产能", "排产方法"]),
    ("T2-002", "通识", "多目标优化方法", "ε 约束锁定军品交期，再做字典序可行性修复、加权求和、Pareto 扫描与模糊满意度终选。", "T2 方法库", ["多目标", "Pareto", "ε约束"]),
    ("T3-001", "通识", "硬约束与软约束", "硬约束 HC-01~14 违反即阻断，不可人工放行；软约束 SC-01~13 以 0.02~0.35 权重参与目标函数。", "T3 约束库", ["HC", "SC", "约束"]),
    ("T4-001", "通识", "典型扰动场景", "设备故障、物料缺料、紧急插单、返工返修、订单变更、检测军检、工艺变更七类扰动。", "T4 场景库", ["扰动", "场景"]),
    ("T5-001", "通识", "军工审计要求", "决策链路全程留痕，审计日志防篡改，方案终审须电子签名，数据不出内网。", "T5 基础库", ["审计", "军工", "合规"]),
    ("ZD-01-001", "专识", "计划拉动主线规则", "五维点检门禁、齐套三时点、MPS 拉动平衡、周滚动 3 锁 1 下发 3 展望、方案白盒归因与终审验签构成计划主线。", "ZD-01 规则集", ["R001-R010", "计划拉动"]),
    ("ZD-02-001", "专识", "钛合金焊接有效期", "钛合金真空焊接后的特殊过程有效期为 20 个自然日，跨节假日按日历衰减，超期必须重新处理。", "ZD-02 工艺路线", ["钛合金", "焊接", "有效期"]),
    ("ZD-02-002", "专识", "真空热处理工艺曲线", "真空热处理升温速率、保温时间与冷却速率必须落在材料工艺窗口内，违反 HC-06 设备参数值域即阻断。", "ZD-02 工艺路线", ["真空热处理", "工艺曲线"]),
    ("ZD-03-001", "专识", "五轴加工换型时间", "五轴加工中心同族产品换型 12min，跨族换型 45min，夹具切换超过 4 组时追加 20min。", "ZD-03 工序参数", ["五轴", "换型", "setup"]),
    ("ZD-04-001", "专识", "探伤合格率与返工缓冲", "关键件荧光探伤合格率按 60% 建模，返工缓冲纳入不确定性区间，禁止把返工概率当作零。", "ZD-04 工艺变更", ["探伤", "返工", "贝叶斯"]),
    ("ZD-05-001", "专识", "试车台架窗口", "试车台按 12h 窗口排程，台架准备、试车运行与性能复测为一个不可拆分窗口链。", "ZD-05 设备能力", ["试车台", "窗口", "试车"]),
    ("ZD-06-001", "专识", "关键工序人员资质", "焊接、热处理、无损检测与试车为特殊过程，操作人员必须持有效资质，资质缺口触发 HC-10 阻断。", "ZD-06 人员技能", ["资质", "特殊过程"]),
    ("ZD-07-001", "专识", "插单影响面处置案例", "军品 P0 急件插单优先抢占瓶颈资源，采用局部重排并沿依赖链评估涟漪，15 分钟内提交 A/B 方案。", "ZD-07 扰动案例", ["插单", "影响面", "P0"]),
    ("ZD-08-001", "专识", "装配齐套缺口处置经验", "主材缺口优先触发替代料审批，工装缺口由工装室 4h 内调拨，人员资质缺口由调度室跨线调剂。", "ZD-08 专家经验", ["齐套", "缺口", "处置"]),
    ("ZD-09-001", "专识", "密级与脱敏", "人员姓名、成本、供应商等字段按密级规则不可逆脱敏；涉密数据禁止明文落日志与出内网。", "ZD-09 安全伦理", ["脱敏", "密级", "安全"]),
]

ALERT_DEFS = [
    ("fatal", "equipment", "五轴加工中心 DMC02 主轴振动异常", "设备实时监测触发故障阈值，已锁定产能并进入 M-04 影响评估。", "MES 设备监控", "resource", "MC-DMC02", 0),
    ("critical", "kit", "3 个订单主材齐套缺口", "主材批次未到料，开工前时点存在硬阻断风险，缺口已分派采购部。", "M-03 齐套检查", "kit", "KIT-0031", 1),
    ("critical", "approval", "排产方案审批即将超时", "全量重排 A/B/C 方案待终审，剩余时间不足 5 分钟，将按 R009 自动升级。", "审批长事务", "plan", "BATCH", 0),
    ("warning", "data", "WMS 数据同步延迟 14min", "执行数据时延超过 5min 目标，影响齐套实时性，已触发数据整改单。", "数据门禁", "source", "WMS", 0),
    ("warning", "change", "军品紧急插单进入评估队列", "P0 插单已录入事件总线，M-04 正在推演影响面。", "事件总线", "change", "CJ", 1),
    ("warning", "special", "2 道特殊过程工序接近有效期", "钛合金焊接工序有效期剩余不足 48h，需优先安排后续检测。", "M-06 特殊过程联动", "operation", "OP-SPECIAL", 0),
    ("info", "plan", "夜间全量重排完成", "108 产品 × 28 工序全量重排完成，A/B/C 方案已提交审批。", "C-01 总控", "plan", "PS", 2),
    ("info", "audit", "审计哈希链自检通过", "全量审计日志哈希链完整性校验通过，无篡改迹象。", "审计服务", "audit", "CHAIN", 3),
    ("warning", "bottleneck", "真空热处理炉 VHT01 负荷 91%", "瓶颈资源接近负荷红线，建议前置保护并评估替代炉。", "负荷监控", "resource", "HT-VHT01", 1),
    ("critical", "quality", "关键件探伤合格率低于缓冲假设", "近 7 天荧光探伤合格率 57.4%，低于贝叶斯模型 60% 假设，需回流影子数据集。", "QMS 质量", "quality", "NDT", 2),
    ("info", "system", "L0 五维点检完成", "综合得分 94.8%，门禁通过，允许进入排产链路。", "数据门禁", "quality", "L0", 0),
    ("warning", "kit", "1 个订单刀具寿命不足", "刀具寿命剩余 18%，已推荐换刀并更新刀具台账。", "M-03 齐套检查", "kit", "KIT-0044", 2),
]

CHANGE_DEFS = [
    {
        "type": "fault", "title": "五轴加工中心 DMC02 主轴故障停机",
        "detail": "MES 设备监控在 08:17 检测到主轴振动超限，EAM 判定需抢修 18h，影响机加—热表链。",
        "severity": "critical", "resource_code": "MC-DMC02", "delay_hours": 18, "hours_ago": 2.5, "make_plans": True,
    },
    {
        "type": "insert", "title": "某型发动机 P0 军品急件插单",
        "detail": "客户紧急追加 P0 订单 2 台，要求 12 天内交付，需评估对现有装配/试车窗口的影响。",
        "severity": "critical", "delay_hours": 6, "hours_ago": 5.2, "make_plans": False,
    },
    {
        "type": "material", "title": "钛合金棒材到料延误 36h",
        "detail": "供应商物流受阻，主材批次预计延误 36h，涉及 6 个锻造/机加订单。",
        "severity": "warning", "delay_hours": 36, "hours_ago": 8.0, "make_plans": False,
    },
    {
        "type": "rework", "title": "关键件荧光探伤不合格返工",
        "detail": "批次 LX-2409 荧光探伤发现 2 件裂纹，进入两装两试返工回路。",
        "severity": "warning", "delay_hours": 24, "hours_ago": 26, "make_plans": False,
    },
    {
        "type": "order_change", "title": "客户交期提前 5 天",
        "detail": "某型低压涡轮盘订单交期由 11 月 18 日提前至 11 月 13 日，需评估产能可行性。",
        "severity": "warning", "delay_hours": 0, "hours_ago": 30, "make_plans": False,
    },
    {
        "type": "inspection", "title": "军检窗口调整至 11 月 4 日",
        "detail": "军代表室通知军检窗口调整，涉及 4 个装配订单与 2 个试车订单。",
        "severity": "warning", "delay_hours": 4, "hours_ago": 50, "make_plans": False,
    },
    {
        "type": "ecn", "title": "ECN-2026-097 工艺路线升版",
        "detail": "某型机匣精车工序增加去应力退火，在制工单需执行断点排查与换版。",
        "severity": "critical", "delay_hours": 10, "hours_ago": 72, "make_plans": False,
    },
]


def _make_route(factor: float) -> list[dict]:
    route = []
    seq = 1
    for domain, steps in DOMAIN_ROUTES.items():
        for name, std, setup, special in steps:
            variation = 0.86 + RNG.random() * 0.3
            route.append(
                {
                    "seq": seq,
                    "name": name,
                    "domain": domain,
                    "resource_type": domain,
                    "std_minutes": round(std * factor * variation, 1),
                    "setup_minutes": round(setup * (0.9 + RNG.random() * 0.3), 1),
                    "special": special,
                }
            )
            seq += 1
    return route


def _seed_kit_sources(db, products, orders, resources, actor):
    """齐套外部主数据的演示快照：BOM / 库存 / 在途 / 工装刀具 / 资质 / 检验结论。"""
    materials = []
    stock = []
    inbound = []
    for i, product in enumerate(products):
        main, aux = MATERIAL_LIB.get(product.family, MATERIAL_LIB["高压涡轮叶片"])
        order = orders[i] if i < len(orders) else None
        qty = max(1, int(order.qty or 1)) if order else 1
        due = order.due_date if order and order.due_date else NOW + timedelta(days=20)
        for category, spec in (("main_material", main), ("aux_material", aux)):
            name, unit, qty_per, lead = spec
            code = f"MT-{product.code}-{'M' if category == 'main_material' else 'A'}"
            needed = round(qty_per * qty, 3)
            short = category == "main_material" and i % 4 == 1
            if short:
                on_hand, allocated = round(needed * 0.4, 3), 0.0
            else:
                on_hand, allocated = round(needed * 1.2 + 4, 3), round(needed * 0.1, 3)
            materials.append({
                "code": code, "name": name, "unit": unit, "category": category,
                "product_code": product.code, "qty_per": qty_per, "lead_time_days": lead,
            })
            stock.append({
                "material_code": code, "on_hand": on_hand, "allocated": allocated,
                "quality_status": "合格", "batch": f"B{2026 + i % 3}-{i + 1:03d}",
                "location": "一厂立体库" if i % 2 == 0 else "二厂立体库",
            })
            if short:
                covers_due = i % 8 == 1
                eta = due - timedelta(days=3) if covers_due else due + timedelta(days=90)
                inbound.append({
                    "reference": f"PO-2026-{i + 1:04d}", "material_code": code,
                    "qty": round(needed - (on_hand - allocated), 3),
                    "eta": eta.strftime("%Y-%m-%d %H:%M"),
                    "supplier": "宝钛股份" if i % 2 == 0 else "西部超导", "status": "在途",
                })
    domains = sorted({r.domain for r in resources})
    tools = []
    for d in domains:
        for k in (1, 2):
            tools.append({"code": f"TZ-{d}-{k:02d}", "name": f"{d}定位工装 #{k}", "kind": "tooling",
                          "domain": d, "status": "可用", "owner": "工装室"})
        for k in (1, 2):
            tools.append({"code": f"CT-{d}-{k:02d}", "name": f"{d}可转位铣刀 #{k}", "kind": "cutter",
                          "domain": d, "status": "可用", "life_remaining": round(RNG.uniform(45, 96), 1),
                          "owner": "工具室"})

    persons = ["王", "李", "张", "刘", "陈", "赵", "孙", "周"]
    qualifications = []
    for idx, d in enumerate(domains):
        for k in range(3):
            qualifications.append({
                "person_name": f"{persons[(idx * 3 + k) % len(persons)]}师傅", "capability": d,
                "certificate": f"ZY-{idx + 1:02d}{k + 1}", "level": 2 + (k % 2),
                "valid_until": (NOW + timedelta(days=240 - k * 30)).strftime("%Y-%m-%d"), "active": "是",
            })

    inspections = []
    for i, order in enumerate(orders):
        if order.status == "已完工":
            continue
        for seq in (1, 2, 3):
            conclusion = "合格"
            if i % 9 == 3 and seq == 2:
                conclusion = "待判"
            elif i % 17 == 5 and seq == 3:
                conclusion = "不合格"
            inspections.append({
                "order_no": order.order_no, "seq": seq, "conclusion": conclusion,
                "inspector": f"检验员{(i % 5) + 1:02d}",
            })

    for kind, rows in (
        ("materials", materials), ("stock", stock), ("inbound", inbound),
        ("tools", tools), ("qualifications", qualifications), ("inspections", inspections),
    ):
        if rows:
            upsert_rows(db, kind, rows, actor)
    db.flush()


def seed_if_empty() -> dict:
    db: Session = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return {"seeded": False, "reason": "database already initialized"}
        summary = _seed(db)
        db.commit()
        return {"seeded": True, **summary}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _order_clearance(index: int, customer: str, product) -> str:
    """演示数据的密级分布按件别而非急度：外贸与一般件公开，关键件少量秘密/极少数机密，其余内部。
    优先级不等于密级——P0 单必须排得动，只有少数关键件高于计划员的可读范围。"""
    if "外贸" in customer or product.priority_class == "一般件" and index % 5 == 0:
        return "公开"
    if product.priority_class == "关键件" and index % 17 == 0:
        return "机密"
    if product.priority_class == "关键件" and index % 6 == 0:
        return "秘密"
    return "内部"


def _seed(db: Session) -> dict:
    for key, value in DEFAULT_SETTINGS.items():
        db.add(Setting(key=key, value=value, updated_at=NOW))

    users = []
    for username, password, name, role, clearance, department, color in USERS:
        password = os.getenv(f"LISA_PASSWORD_{username.upper()}") or password
        user = User(
            username=username,
            password_hash=hash_password(password),
            name=name,
            role=role,
            clearance=clearance,
            department=department,
            avatar_color=color,
            created_at=NOW - timedelta(days=180),
        )
        db.add(user)
        users.append(user)
    db.flush()
    planner = next(u for u in users if u.role == "planner")
    commander = next(u for u in users if u.role == "commander")

    resources = []
    for prefix, domain, name, plant, capacity, efficiency, bottleneck in RESOURCE_DEFS:
        code = f"{prefix}-{len([r for r in resources if r.domain == domain]) + 1:02d}"
        resource = Resource(
            code=code, name=name, domain=domain, plant=plant, capacity_hours=capacity,
            efficiency=efficiency, bottleneck=bottleneck, status="running",
            machine_count=MACHINE_COUNTS.get(name, 1), capabilities=[domain],
        )
        db.add(resource)
        resources.append(resource)
    db.flush()

    products = []
    for i in range(108):
        family, cls, factor = FAMILIES[i % len(FAMILIES)]
        product = Product(
            code=f"LY-{i + 1:03d}",
            name=f"{family}-{2026 + (i // 12)} 型",
            family=family,
            priority_class=cls,
            route=_make_route(factor),
        )
        db.add(product)
        products.append(product)
    db.flush()

    orders = []
    completed_orders = []
    for i in range(108):
        product = products[i]
        priority = "P0" if i % 5 == 0 else ("P1" if i % 3 == 0 else "P2")
        if i < 10:
            status = "已完工"
            progress = 100
        elif i < 14:
            status = "执行中"
            progress = 35 + (i * 7) % 40
        elif i < 20:
            status = "待排产"
            progress = 0
        elif i < 22:
            status = "逾期"
            progress = 55
        else:
            status = "已排产"
            progress = 0
        days = (18 + (i * 3) % 14) if priority == "P0" else (36 + (i * 5) % 24 if priority == "P1" else (56 + (i * 7) % 26))
        due = NOW + timedelta(days=days)
        customer = "空军装备部" if i % 3 == 0 else ("中国航发" if i % 3 == 1 else "外贸客户")
        order = Order(
            order_no=f"MO-2026-{i + 1:04d}",
            product_id=product.id,
            product_name=product.name,
            qty=1 + (i % 4),
            priority=priority,
            plant="一厂" if i % 2 == 0 else "二厂",
            customer=customer,
            due_date=due,
            status=status,
            progress=progress,
            is_military=i % 10 != 9,
            clearance=_order_clearance(i, customer, product),
            kit_status="齐套",
            created_at=NOW - timedelta(days=40 - i % 20),
            released_at=NOW - timedelta(days=30 - i % 15),
        )
        db.add(order)
        orders.append(order)
        if status == "已完工":
            completed_orders.append(order)
    db.flush()

    total_ops = 0
    for order in orders:
        product = next(p for p in products if p.id == order.product_id)
        route = sorted(product.route, key=lambda s: s["seq"])
        for step in route:
            if order.status == "已完工":
                planned_start = NOW - timedelta(days=18) + timedelta(minutes=step["seq"] * 520)
                planned_end = planned_start + timedelta(minutes=step["std_minutes"])
                status = "已完工"
                actual_start, actual_end = planned_start, planned_end
                resource = RNG.choice([r for r in resources if r.domain == step["domain"]])
            else:
                planned_start = planned_end = actual_start = actual_end = None
                status = "待开工"
                resource = None
            op = Operation(
                order_id=order.id,
                seq=step["seq"],
                name=step["name"],
                domain=step["domain"],
                resource_type=step["resource_type"],
                std_minutes=step["std_minutes"],
                setup_minutes=step["setup_minutes"],
                special=step["special"],
                status=status,
                planned_start=planned_start,
                planned_end=planned_end,
                actual_start=actual_start,
                actual_end=actual_end,
                resource_id=resource.id if resource else None,
                locked=False,
                risk="normal",
                valid_until=NOW + timedelta(days=20) if step["special"] else None,
            )
            db.add(op)
            total_ops += 1
    db.flush()

    # One completed order's trial operation failed -> realistic trial achievement.
    failed_order = completed_orders[0]
    failed_op = (
        db.query(Operation)
        .filter(Operation.order_id == failed_order.id, Operation.domain == "试车")
        .order_by(Operation.seq.desc())
        .first()
    )
    if failed_op:
        failed_op.status = "返工"

    open_orders = [o for o in orders if o.status not in ("已完工", "已取消")]
    _seed_kit_sources(db, products, orders, resources, next(u for u in users if u.role == "admin"))
    for order in open_orders[:52]:
        for checkpoint in ("pre_schedule", "post_schedule", "pre_start"):
            persist_check(db, order, checkpoint)
    db.flush()

    baseline_result = generate_schedule(db, scenario="A", freeze=False)
    baseline = save_plan(
        db, baseline_result, plan_type="full", created_by="C-01 全厂智能排产总控",
        status="applied", name="夜间全量基线 · 2026-10-31",
    )
    baseline.baseline = True
    baseline.applied_at = NOW
    baseline.approved_at = NOW
    freeze_until = NOW + timedelta(days=int(DEFAULT_SETTINGS["freeze_days"]))
    for item in db.query(PlanItem).filter(PlanItem.plan_id == baseline.id).all():
        op = db.get(Operation, item.operation_id) if item.operation_id else None
        if op:
            op.planned_start = item.start
            op.planned_end = item.end
            op.resource_id = item.resource_id
            op.risk = item.risk
            if item.start < freeze_until:
                op.locked = True
                item.locked = True
    for order in open_orders:
        if order.status == "待排产":
            order.status = "已排产"
    db.flush()

    # Historical decisions for adoption KPI
    for i in range(20):
        rejected = i in (5, 11, 17)
        created = NOW - timedelta(days=28 - i, hours=i)
        plan = Plan(
            code=f"HIST-2026-{i + 1:03d}",
            name=f"历史{'局部' if i % 4 == 0 else '全量'}排产 · {'A' if i % 2 == 0 else 'B'} 方案",
            type="full" if i % 4 else "change",
            status="rejected" if rejected else "applied",
            scenario="A" if i % 2 == 0 else "B",
            objective="交期优先 · 军品保供" if i % 2 == 0 else "瓶颈均衡 · 负荷平滑",
            weights={"delivery": 0.4, "bottleneck": 0.25, "changeover": 0.2, "cost": 0.15},
            summary={"history": True, "reason": "人工驳回：需优先保障 P0 交付" if rejected else "计划员确认可直接执行"},
            kpi={
                "predicted_adoption": round(82.4 + i * 0.45, 1),
                "on_time_rate": round(84.0 + (i % 6) * 1.6, 1),
                "total_score": round(83.0 + (i % 7) * 1.4, 1),
                "accuracy": round(76.0 + i * 0.4, 1),
            },
            created_by="生产指挥部",
            created_at=created,
            submitted_at=created,
            approved_at=created + timedelta(minutes=18) if not rejected else None,
            applied_at=created + timedelta(minutes=21) if not rejected else None,
            baseline=False,
        )
        db.add(plan)
    db.flush()

    # Initial pending A/B/C batch for human-in-the-loop demo
    pending_plans = _create_initial_pending_batch(db, planner)

    rules = []
    for rule_def in RULES:
        rule = Rule(
            code=rule_def["code"], kind="rule", category=rule_def["category"], title=rule_def["title"],
            description=rule_def["description"], priority=rule_def["priority"],
            trigger=rule_def["trigger"], action=rule_def["action"], domain=rule_def["domain"],
            enabled=True, hits=18 + (int(rule_def["code"][1:]) * 7) % 160,
        )
        db.add(rule)
        rules.append(rule)
    for code, title, description in HARD_CONSTRAINTS:
        db.add(Rule(code=code, kind="hard", category="硬约束", title=title, description=description, priority=10, trigger="方案生成 / 入库校验", action="违反即阻断，不可人工放行", domain="全厂", enabled=True, hits=24 + int(code[-2:]) * 3))
    for code, title, weight in SOFT_CONSTRAINTS:
        db.add(Rule(code=code, kind="soft", category="软约束", title=title, description=f"{title}：以权重 {weight} 参与多目标加权与 Pareto 候选筛选。", priority=5, trigger="方案求解", action="计入目标函数与归因说明", weight=weight, domain="全厂", enabled=True, hits=12))
    db.flush()

    for code, category, title, content, source, tags in KNOWLEDGE_ITEMS:
        db.add(Knowledge(code=code, category=category, title=title, content=content, source_ref=source, trace_version="v1.0", tags=tags, confidence=round(0.86 + RNG.random() * 0.12, 2), created_at=NOW - timedelta(days=10)))

    source_defs = [
        ("SAP", "SAP ERP", "SOAP/MCP", "online", 180, 128400, 96.2, "信息中心"),
        ("MES", "MES 制造执行", "MCP", "online", 95, 482600, 95.1, "制造部"),
        ("QMS", "QMS 质量管理", "MCP", "online", 140, 96500, 92.8, "质量部"),
        ("WMS", "WMS 仓储", "MCP", "degraded", 840, 174300, 88.6, "仓储部"),
        ("PLM", "PLM 工艺", "MCP", "online", 210, 42800, 94.4, "工艺部"),
        ("HREAM", "HR / EAM", "REST", "online", 160, 12600, 92.1, "人力资源部"),
        ("MQ", "RocketMQ 事件总线", "Event", "online", 12, 38420, 99.4, "信息中心"),
        ("COPT", "COPT 求解集群", "Solver", "online", 45, 0, 99.9, "算法组"),
    ]
    for idx, (code, name, type_, status, latency, records, quality, owner) in enumerate(source_defs):
        db.add(DataSource(code=code, name=name, type=type_, status=status, latency_ms=latency, last_sync=NOW - timedelta(minutes=idx * 3), records=records, quality=quality, owner=owner))

    final_quality = {"完整性": 96.8, "及时性": 94.2, "一致性": 92.6, "准确性": 93.4, "唯一性": 97.1}
    detail_map = {
        "完整性": {"issues": 128, "fields": ["标准工时缺失 41", "工艺参数缺失 52", "人员资质字段缺失 35"], "sample": "MES.operation.std_time 空值率 2.4%"},
        "及时性": {"issues": 63, "fields": ["WMS 同步延迟 14min", "MES 报工延迟 3min", "QMS 检测结论延迟 8min"], "sample": "WMS 库存事件消费延迟 840ms"},
        "一致性": {"issues": 147, "fields": ["图号↔物料号映射缺失 56", "BOM 版本不一致 38", "单位口径不一致 53"], "sample": "ERP 图号 LY-047 与 MES 物料号 M00047 映射缺失"},
        "准确性": {"issues": 91, "fields": ["标准工时偏差 >20% 32", "探伤合格率偏差 19", "设备能力参数偏差 40"], "sample": "机加 CK02 标准工时偏差 +18.4%"},
        "唯一性": {"issues": 22, "fields": ["订单重复录入 6", "工单主键重复 8", "物料批次重复 8"], "sample": "ERP 订单 MO-2026-0087 重复同步"},
    }
    for dim_index, (dimension, final) in enumerate(final_quality.items()):
        for day in range(14):
            progress = day / 13
            score = round(final - (1 - progress) * (3.6 - dim_index * 0.25) + RNG.uniform(-0.5, 0.5), 1)
            db.add(
                QualitySnapshot(
                    dimension=dimension,
                    score=max(88.0, min(99.5, score)),
                    threshold=90.0,
                    passed=score >= 90,
                    detail=detail_map[dimension],
                    checked_at=NOW - timedelta(days=13 - day, hours=2),
                )
            )
        db.add(QualitySnapshot(dimension=dimension, score=final, threshold=90.0, passed=True, detail=detail_map[dimension], checked_at=NOW - timedelta(minutes=20)))
    db.flush()

    # Seed disturbances / changes
    changes = []
    for idx, change_def in enumerate(CHANGE_DEFS):
        occurred = NOW - timedelta(hours=change_def["hours_ago"])
        resource = next((r for r in resources if r.code == change_def.get("resource_code")), None)
        payload = {"delay_hours": change_def["delay_hours"]}
        if resource:
            payload.update({"resource_id": resource.id, "resource_name": resource.name, "resource_code": resource.code})
        if change_def["type"] == "insert":
            insert_orders = [o.id for o in orders if o.priority == "P0" and o.status not in ("已完工",)]
            payload["order_ids"] = insert_orders[-4:]
        prefix = {"fault": "GZ", "insert": "CJ", "material": "WL", "rework": "FG", "order_change": "DD", "inspection": "TS", "ecn": "ECN"}[change_def["type"]]
        change = Disturbance(
            code=f"{prefix}-2026-{idx + 1:03d}",
            type=change_def["type"],
            title=change_def["title"],
            detail=change_def["detail"],
            severity=change_def["severity"],
            status="评估中",
            occurred_at=occurred,
            payload=payload,
            reporter="系统事件总线" if idx % 2 == 0 else "计划员 · 李静",
        )
        db.add(change)
        db.flush()
        assess_disturbance(db, change)
        change.occurred_at = occurred
        changes.append(change)
    relabel_disturbance_clearance(db)
    db.flush()

    fault_change = changes[0]
    create_change_plans(db, planner, fault_change, scenarios=("A", "B"))
    changes[3].status = "已关闭"
    changes[3].resolved_at = NOW - timedelta(hours=4)
    changes[4].status = "已关闭"
    changes[4].resolved_at = NOW - timedelta(hours=6)
    db.flush()

    for idx, (level, type_, title, message, source, related_type, related_id, hours_ago) in enumerate(ALERT_DEFS):
        alert = Alert(
            code=f"AL-2026-{idx + 1:03d}",
            level=level, type=type_, title=title, message=message, source=source,
            related_type=related_type, related_id=related_id, status="open",
            created_at=NOW - timedelta(hours=hours_ago),
        )
        if idx in (6, 7, 10):
            alert.status = "acked"
            alert.acked_by = commander.name
            alert.acked_at = NOW - timedelta(hours=max(0, hours_ago - 1))
        db.add(alert)

    run_defs = [
        ("C-01", "全厂智能排产总控", "C", "full", 108.4, "夜间全量重排完成：108 单 / 3024 工序，A 方案准时率 91.2%", 1, 0),
        ("C-01", "全厂智能排产总控", "C", "full", 112.6, "夜间全量重排完成：A 方案准时率 89.8%，逾期 9 单", 1, 2),
        ("M-04", "变更影响面评估", "M", "change", 12.6, "设备故障影响评估完成：7 单受影响，A/B 方案待审批", 2, 5),
        ("M-04", "变更影响面评估", "M", "change", 14.1, "紧急插单影响评估完成：5 单受影响，覆盖 4 个工序域", 2, 9),
        ("M-03", "齐套检查", "M", "kit", 3.2, "齐套检查完成：3 项缺口已分派责任部门", 3, 12),
        ("A-02", "机加排产", "A", "local", 27.4, "机加域局部排产建议完成：24 单，准时率 92.4%", 4, 20),
        ("A-03", "表面热处理排产", "A", "local", 29.1, "热表域组批合炉建议完成：18 炉次，满炉率 86.2%", 4, 28),
        ("M-06", "特殊过程联动", "M", "change", 11.2, "特殊过程有效期校验完成：2 道工序需优先排程", 2, 34),
    ]
    for idx, (agent_code, agent_name, level, scenario, minutes, summary, plan_offset, hours_ago) in enumerate(run_defs):
        started = NOW - timedelta(hours=hours_ago, minutes=int(minutes))
        db.add(
            AgentRun(
                code=f"AR-202610{idx + 1:02d}-{agent_code.replace('-', '')}-{idx + 1:04d}",
                agent_code=agent_code,
                agent_name=agent_name,
                level=level,
                scenario=scenario,
                status="succeeded",
                summary=summary,
                inputs={},
                steps=[
                    {"index": 1, "phase": "感知", "title": "输入快照感知", "thought": "读取订单、资源与齐套状态", "action": "mcp.batch_read()", "observation": "输入快照已锁定", "duration_ms": 1200, "status": "done"},
                    {"index": 2, "phase": "推理", "title": "约束推演", "thought": "执行硬约束与规则校验", "action": "shacl.validate() + rules.evaluate()", "observation": "硬约束通过", "duration_ms": 2300, "status": "done"},
                    {"index": 3, "phase": "规划", "title": "方案求解", "thought": "多目标求解并生成候选", "action": "solver.solve()", "observation": summary, "duration_ms": 4300, "status": "done"},
                    {"index": 4, "phase": "决策", "title": "提交审批", "thought": "输出方案与白盒归因", "action": "approval.create()", "observation": "已归档待审批", "duration_ms": 800, "status": "done"},
                ],
                output={"simulated_minutes": minutes, "summary": summary},
                plan_id=None,
                operator="调度员 · 陈涛" if idx % 2 == 0 else "计划员 · 李静",
                started_at=started,
                ended_at=NOW - timedelta(hours=hours_ago),
                duration_ms=int(minutes * 60_000),
            )
        )
    db.flush()

    audit_events = [
        ("system", "system", "system.bootstrap", "system", "LISA", {"version": "1.0.0"}),
        ("admin", "admin", "seed.complete", "system", "LISA", {"orders": len(orders), "operations": total_ops}),
        ("C-01", "system", "plan.baseline.apply", "plan", baseline.code, {"operations": total_ops}),
        ("生产指挥部", "commander", "plan.approve", "plan", pending_plans[0].code, {"scenario": "A", "signature": "VERIFIED"}),
        ("计划员 · 李静", "planner", "plan.submit", "plan", pending_plans[0].code, {"batch": pending_plans[0].batch_id}),
        ("M-04", "system", "change.assess", "change", changes[0].code, {"affected_orders": 7, "elapsed_minutes": 12.6}),
        ("M-03", "system", "kit.check", "order", "MO-2026-0031", {"checkpoint": "pre_start", "status": "缺项"}),
        ("A-00", "system", "data.gate.check", "quality", "L0", {"overall": 94.8, "passed": True}),
        ("系统管理员 · 赵磊", "admin", "settings.update", "settings", "weights", {"delivery": 0.4, "bottleneck": 0.25}),
        ("审计服务", "system", "audit.verify", "audit", "CHAIN", {"total": 0, "ok": True}),
        ("C-01", "system", "agent.run", "agent_run", "AR-20261001-C01-0001", {"scenario": "full", "simulated_minutes": 108.4}),
        ("M-04", "system", "agent.run", "agent_run", "AR-20261003-M04-0003", {"scenario": "change", "simulated_minutes": 12.6}),
        ("M-03", "system", "agent.run", "agent_run", "AR-20261005-M03-0005", {"scenario": "kit", "simulated_minutes": 3.2}),
        ("A-02", "system", "agent.run", "agent_run", "AR-20261006-A02-0006", {"scenario": "local", "simulated_minutes": 27.4}),
        ("WMS", "system", "data.quality.alert", "source", "WMS", {"latency_ms": 840, "quality": 88.6}),
        ("生产指挥部", "commander", "alert.ack", "alert", "AL-2026-003", {"comment": "已安排终审"}),
        ("计划员 · 李静", "planner", "plan.reject", "plan", "HIST-2026-006", {"reason": "需优先保障 P0 交付"}),
        ("工艺员 · 周敏", "engineer", "ecn.assess", "change", "ECN-2026-007", {"in_process_orders": 6, "breakpoint": 4}),
    ]
    for actor, role, action, target_type, target_id, detail in audit_events:
        append_audit(db, actor, role, action, target_type, target_id, detail=detail, clearance="内部")
    db.flush()

    return {
        "users": len(users),
        "products": len(products),
        "orders": len(orders),
        "operations": total_ops,
        "resources": len(resources),
        "plans": db.query(Plan).count(),
        "rules": db.query(Rule).count(),
        "changes": len(changes),
        "audit_logs": db.query(AuditLog).count(),
    }


def _create_initial_pending_batch(db: Session, planner: User) -> list[Plan]:
    from .services.agents import AGENTS  # noqa: F401  keep import graph consistent

    from .services.scheduler import create_plan_batch

    plans = create_plan_batch(db, planner, plan_type="full", scenarios=("A", "B", "C"))
    return plans
