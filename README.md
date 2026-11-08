# LISA · 黎阳智能排产智能体

面向航空发动机离散制造的**三级智能体（C / M / A）+ 七层底座（L0–L6）**智能排产系统。覆盖订单、有限产能排程、方案审批、扰动影响推演、齐套校验、数据门禁、规则知识、审计追溯与告警闭环，面向内网私有化部署。

- 技术栈：Python 3.12 · FastAPI · SQLAlchemy 2 · SQLite（可切 PostgreSQL）· Vue 3.5 · TypeScript · Vite 7 · ECharts
- 视觉：深色军工科技为主、可切换浅色；PC / 平板 / 手机自适应
- 演示数据：108 个产品、200+ 订单、28 道工序模板、32 个资源、68 条规则、基线排程与历史方案

---

## 系统截图

> 基于 PostgreSQL 运行环境与内置演示数据实拍，桌面端 1440×900，移动端 412×915 视口。

| 指挥驾驶舱（深色） | 智能排产 · 有限产能甘特 |
| :---: | :---: |
| ![指挥驾驶舱](docs/screenshots/dashboard.png) | ![智能排产](docs/screenshots/gantt.png) |
| **方案审批 · A/B 对比** | **齐套检查 · 九要素** |
| ![方案审批](docs/screenshots/plans.png) | ![齐套检查](docs/screenshots/kits.png) |
| **变更影响 · 涟漪推演** | **智能体中心 · C/M/A 编队** |
| ![变更影响](docs/screenshots/changes.png) | ![智能体中心](docs/screenshots/agents.png) |
| **审计追溯 · SHA-256 哈希链** | **驾驶舱 · 浅色主题** |
| ![审计追溯](docs/screenshots/audit.png) | ![浅色主题](docs/screenshots/dashboard-light.png) |

<p align="center">
  <img src="docs/screenshots/mobile-dashboard.png" width="300" alt="移动端 · 指挥驾驶舱" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/screenshots/mobile-orders.png" width="300" alt="移动端 · 订单台账" />
</p>
<p align="center"><sub>移动端自适应 · 指挥驾驶舱 / 订单台账</sub></p>

---

## 1. 功能地图

| 模块 | 能力 |
| --- | --- |
| 指挥驾驶舱 | 8 项 KPI、基线方案、域负荷、资源负荷、L0 质量门禁、齐套率、告警、审批、风险订单、审计尾部 |
| 智能排产（甘特） | 基线 / 候选方案切换、冻结窗口、当前时间线、域/优先级/搜索筛选、缩放、列表与甘特双视图、工序详情 |
| 方案审批 | A/B/C 多目标方案对比、14 项硬约束核验、软约束提示、变更差异、PROV-O 血缘、电子签名签发 / 驳回、人机反馈 |
| 智能体中心 | C/M/A 三级智能体目录、运行历史、ReAct 步骤回放、夜间全量重排 / 齐套 / 局部重排 / 变更重排；**入队 + 后台工人执行**，页面显示进度、可取消排队任务 |
| 变更影响 | 扰动事件登记、涟漪影响推演、受影响订单、A/B 重排方案、SLA 倒计时、关闭事件 |
| 齐套检查 | 排产前 / 排产后 / 开工前三个时点、九要素快照、缺口责任归口、开工前硬阻断、时点历史 |
| 订单台账 | 订单汇总、状态/优先级/搜索筛选、基线排程、逾期与齐套风险、工序路线与齐套快照 |
| 数据基座 | 五维质量门禁（完整性/及时性/一致性/准确性/唯一性）、数据源接入、四区间数据覆盖、标注工程 |
| 知识规则 | 68 条规则、HC-01~14 硬约束、SC-01~13 软约束、专识条目、本地 RAG 检索与溯源 |
| 审计追溯 | SHA-256 哈希链、链完整性校验、操作分布、审计明细、CSV 导出 |
| 告警中心 | 致命/严重/警告/提示分级、级别与状态筛选、单条 / 批量确认 |
| 系统设置 | 冻结窗口、班次、审批与求解超时、多目标权重、场景预设、写保护开关、ABAC 矩阵、用户、密级模型、厂区读取范围、备份与恢复、系统信息与导出 |

## 2. 快速启动

### 方式一：Docker（推荐）

```bash
cp .env.example .env
# 编辑 .env：设置 JWT_SECRET，并按需设置初始账号密码
docker compose up -d --build
# 打开 http://localhost:8000
```

数据持久化在 `lisa-data` 卷（容器内 `/app/data`）。升级：

```bash
docker compose build --no-cache
docker compose up -d
```

### 方式二：Windows 一键脚本

```bat
start.bat
```

脚本会自动创建虚拟环境、安装依赖、构建前端并启动 `http://127.0.0.1:8000`。

### 方式三：Linux / macOS

```bash
export JWT_SECRET="$(openssl rand -hex 32)"
./start.sh
```

### 方式四：前后端分离开发

```bash
# 终端 1
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 终端 2
cd frontend
npm install
npm run dev        # http://localhost:5173，/api 代理到 8000
```

## 3. 初始账号

| 账号 | 初始密码 | 角色 |
| --- | --- | --- |
| `admin` | `admin123` | 系统管理员 |
| `commander` | `commander123` | 生产指挥部（终审） |
| `planner` | `planner123` | 计划员 |
| `dispatcher` | `dispatcher123` | 调度员 |
| `engineer` | `engineer123` | 工艺员 |
| `expert` | `expert123` | 领域专家 |

> 生产部署时通过 `LISA_PASSWORD_*` 环境变量覆盖初始密码，并在首次初始化前设置；数据库初始化后修改环境变量不会重置既有账号。建议接入内网统一身份认证。

## 4. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `JWT_SECRET` | 内置开发密钥 | **生产必填**，JWT HS256 签名密钥 |
| `LISA_ENV` | `production` | 运行环境标识 |
| `LISA_DATA_DIR` | `backend/data` | SQLite 数据目录 |
| `DATABASE_URL` | SQLite 文件 | PostgreSQL 示例：`postgresql+psycopg2://user:password@localhost:5433/lisa`（驱动已内置） |
| `LISA_SEED` | `1` | 空库启动时自动初始化演示数据 |
| `LISA_TZ_OFFSET` | `8` | 时间基准时区 |
| `JWT_TTL_HOURS` | `12` | 会话有效期 |
| `CORS_ORIGINS` | 本地开发地址 | 同源部署时无需调整 |
| `LISA_PORT` | `8000` | 容器映射端口 |
| `LISA_PASSWORD_<USER>` | 内置演示密码 | 首次初始化时的账号密码覆盖 |
| `LISA_ADAPTER_POLL_SECONDS` | `60` | 适配器进程内轮询间隔；`0` 表示交给外部定时任务跑 `python -m app.management adapters` |
| `LISA_ERP_TOKEN` / `LISA_MES_DSN` | 空 | 齐套外部数据源凭据；界面与设置里只写变量名，值不落库不进日志 |
| `LISA_LLM_API_KEY` | 空 | 内网模型凭据；未配置时编排自动降级为确定性模式，排产链路不受影响 |
| `LISA_ANCHOR_SECRET` | 空 | 审计链库外锚点的 HMAC 密钥；留空则锚定接口明确拒绝 |
| `LISA_JOB_WORKER` | `1` | 是否在进程内起任务工人；多副本时只留一个 `1`，其余置 `0` |
| `LISA_JOB_POLL_SECONDS` | `1.5` | 工人领任务轮询间隔 |
| `LISA_WORKER_ID` | 主机名:进程号 | 排障用标识，写进被领取的任务 |
| `LISA_BACKUP_DIR` | `backend/data/backups` | 整库快照落地目录（容器里在 `lisa-data` 卷上） |
| `LISA_BACKUP_KEEP` | `14` | 快照保留份数，超出按时间从旧到新清理 |

以上变量可写入项目根目录 `.env`（启动时自动加载，已在 `.gitignore` 中排除），系统环境变量优先级更高。

### 切换到 PostgreSQL

1. 创建数据库：`CREATE DATABASE lisa;`
2. 在根目录 `.env` 中配置 `DATABASE_URL=postgresql+psycopg2://postgres:<password>@localhost:5433/lisa`
3. 空库首次启动会自动建表并写入种子数据；`LISA_SEED=0` 可关闭初始化。
4. 需要重建演示数据时，先备份并清空目标库的 `public` schema，再以 `LISA_SEED=1` 重启。

## 5. 安全与合规

- **写保护网关**：LLM / 求解器禁止直写 APS / MES，必须携带方案 ID、审批人与电子签名；未审批写入 100% 拦截并落审计。
- **ABAC**：6 类角色权限矩阵，前后端双重校验，越权请求拒绝并记录。
- **双读取范围**：密级与厂区两条过滤叠加（不是二选一），一律 fail-closed——认不出来的属性按最低权限处理；被挡掉的行数如实回传「N 张因读取范围未显示」，看不见不等于不存在。
- **电子签名**：PBKDF2-SHA256 密码校验 + 签发摘要，审批 15 分钟超时自动升级。
- **审计哈希链**：SHA-256 `prev_hash → hash` 只追加链，支持完整性校验与 CSV 导出，留存策略可配置。
- **数据不出内网**：无公网依赖；传输使用内网 HTTPS / mTLS（由 nginx 终止 TLS）；敏感字段不可逆脱敏。
- **不可变追溯**：方案 PROV-O 血缘、规则版本、知识 `source_ref / trace_version`，支撑军工审计。

## 6. 目录结构

```
lisa/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口、静态 SPA 托管
│   │   ├── config.py          # 环境变量与角色权限
│   │   ├── models.py          # 数据模型
│   │   ├── seed.py            # 确定性演示数据
│   │   ├── routers/           # auth/dashboard/plans/agents/changes/...
│   │   └── services/          # 有限产能排程、影响推演、齐套、质量、审计
│   └── tests/                 # pytest + TestClient 端到端接口测试
├── frontend/
│   └── src/
│       ├── pages/             # 12 个业务页面
│       ├── components/        # 设计系统组件（无第三方 UI 库）
│       ├── styles/            # tokens.css / base.css（深色 + 浅色）
│       └── api/               # 强类型 API 客户端
├── deploy/                    # nginx TLS 反代、systemd 单元
├── Dockerfile                 # 多阶段构建：前端产物 + Python 运行时
├── docker-compose.yml
├── start.bat / start.sh
└── docs/                      # 需求分析与总体架构文档
```

## 7. 测试与验收

```bash
cd backend
python -m pytest            # 159 个用例：接口端到端 + 排程正确性 + 队列/密级/厂区/备份

cd ../frontend
npm run typecheck
npm run build
```

测试覆盖：登录 / 鉴权、驾驶舱、待审批次与甘特、电子签名与写保护、智能体运行（含入队 drain）、变更全生命周期、
齐套校验、订单、数据门禁、知识检索、审计校验与导出、告警确认、管理员参数与 RBAC、有限产能与工作日历、
14 条硬约束、MCP 只读工具面、密级过滤与库外锚点、任务队列（CAS 抢占 / 心跳恢复 / 取消）、厂区读取范围、
整库快照与恢复（篡改检测、跨库恢复、序列续号）。

## 8. 生产部署

1. 设置唯一 `JWT_SECRET` 与初始账号密码，复制 `.env.example` 为 `.env`。
2. `docker compose up -d --build`，确认健康检查 `GET /api/health` 返回 `ok`。
3. 前置 nginx 终止 TLS（参考 `deploy/nginx.conf`），仅开放内网端口。
4. 首次登录后按组织要求替换账号体系，将 `backend/data`（或 `lisa-data` 卷）纳入备份与只读归档。
5. 监控 `/api/health`、`/api/jobs/health`（队列深度与工人是否静默）、审计链校验结果与告警中心「致命」数量。

### 备份与恢复

```bash
cd backend
python -m app.management backup                 # 整库快照：JSON.gz + .sha256 + .meta.json
python -m app.management backups                # 列出本地快照
python -m app.management verify <文件名>         # 核字节校验和、内容摘要与行数
python -m app.management restore <文件名> --yes  # 停服后整库回滚（不给 HTTP 开口）
```

恢复是破坏性动作：先清空业务表，再按外键依赖顺序写回，PostgreSQL 上顺带重置序列，
最后逐表核对行数并重算审计链，任一步不过整体回滚。「设置 → 系统 → 备份与恢复」里
可以点「立即快照」和「校验」，`verify` 里还会打印当前引擎对应的 `pg_dump` / `sqlite3 .backup` 命令。

### 后台任务

`POST /api/agents/run` 与适配器拉取都是入队执行（HTTP 立即返回 `202`），编排落在 `jobs` 表驱动的工人线程里。
单容器默认自带工人；多副本时把从属节点的 `LISA_JOB_WORKER` 设为 `0`。排队中的任务可在智能体页取消，
正在计算的不硬砍——砍在半路会留下半成品方案。

裸机部署可使用 `deploy/lisa.service`，将项目放置 `/opt/lisa`、环境变量放置 `/etc/lisa/lisa.env`，数据目录指向 `/var/lib/lisa`。

## 9. API

- Swagger：`/api/docs`
- ReDoc：`/api/redoc`
- 健康检查：`/api/health`

除登录与健康检查外，所有接口需 `Authorization: Bearer <token>`。

## 10. 说明

演示数据由固定随机种子生成，重复初始化结果一致。清除演示数据只需删除 `backend/data/lisa.db`（或 `docker compose down -v` 后重启），系统会在空库时自动重建基线方案、待审批次、齐套与审计数据。
