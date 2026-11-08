from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION, CORS_ORIGINS, ENVIRONMENT, JWT_SECRET, SEED_ON_START
from .database import Base, SessionLocal, engine
from .migrate import sync_new_columns
from .models import User
from .routers import agents, alerts, audit, auth, changes, dashboard, data, jobs, kits, knowledge, mcp, orders, plans, system
from .seed import seed_if_empty
from .services import jobs as job_queue
from .services import job_tasks  # noqa: F401 - import 即登记后台任务处理器
from .services.adapters import run_due, source_configs
from .services.calendar import CalendarConfigError, configure_calendar
from .services.clearance import ClearanceError
from .services.impact import relabel_disturbance_clearance
from .services.settings import all_settings

ADAPTER_POLL_SECONDS = int(os.getenv("LISA_ADAPTER_POLL_SECONDS", "60"))
JOB_POLL_SECONDS = float(os.getenv("LISA_JOB_POLL_SECONDS", "1.5"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("lisa")

# Windows registry can map .js to text/plain; browsers reject module scripts with that MIME.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/webp", ".webp")


def _poll_adapters_once() -> dict | None:
    """到点的适配器同步跑在工作线程里：DB 会话不跨线程，也绝不阻塞事件循环。"""
    with SessionLocal() as db:
        actor = db.query(User).filter(User.role == "admin").order_by(User.id).first()
        if actor is None or not source_configs(db):
            return None
        return run_due(db, actor)


async def _adapter_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=ADAPTER_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            break
        try:
            summary = await asyncio.to_thread(_poll_adapters_once)
        except Exception:  # noqa: BLE001 - 轮询失败不能带崩服务
            logger.exception("适配器轮询失败")
            continue
        if summary and summary.get("ran"):
            logger.info(
                "适配器同步：%d 个通道，失败 %d 个",
                len(summary["ran"]), sum(1 for item in summary["ran"] if item.get("error")),
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    added = sync_new_columns()
    if added:
        logger.info("Schema 补齐新增列: %s", ", ".join(added))
    with SessionLocal() as db:
        try:
            calendar = configure_calendar(all_settings(db))
        except CalendarConfigError as exc:
            calendar = configure_calendar(None)
            logger.error("日历配置非法，已退回默认班次（请修正 settings.calendar）：%s", exc)
    logger.info(
        "工作日历生效：%s / 每周生产日 %s / 节假日 %d 天",
        "、".join(f"{s.name} {s.start // 60:02d}:{s.start % 60:02d}-{s.end // 60:02d}:{s.end % 60:02d}" for s in calendar.shifts),
        ",".join(str(d) for d in sorted(calendar.workdays)),
        len(calendar.holidays),
    )
    if SEED_ON_START:
        result = seed_if_empty()
        if result.get("seeded"):
            logger.info("Seed completed: %s", result)
        else:
            logger.info("Database already initialized: %s", result.get("reason"))
    if ENVIRONMENT == "production" and JWT_SECRET == "lisa-aecc-liyang-internal-secret-2026":
        logger.warning("JWT_SECRET is still the built-in default. Set a unique secret before exposing LISA.")
    with SessionLocal() as db:
        try:
            relabelled = relabel_disturbance_clearance(db)
            db.commit()
            if relabelled["relabelled"]:
                logger.info("扰动事件密级按受影响工单重标：%d/%d 条", relabelled["relabelled"], relabelled["total"])
        except ClearanceError as exc:
            db.rollback()
            logger.error("密级等级表非法，未重算事件密级（请修正 settings.clearance）：%s", exc)
    logger.info("%s v%s starting in %s", APP_NAME, APP_VERSION, ENVIRONMENT)
    worker_started = False
    if ENVIRONMENT != "test" and job_queue.worker_enabled():
        worker_started = job_queue.start_worker(JOB_POLL_SECONDS)
        logger.info(
            "后台任务 worker：%s（%s）轮询 %.1fs，已登记任务 %s",
            "已启动" if worker_started else "已在运行", job_queue.worker_id(), JOB_POLL_SECONDS,
            "、".join(job_queue.registered_kinds()) or "无",
        )
    elif ENVIRONMENT != "test":
        logger.warning("后台任务 worker 未启动（LISA_JOB_WORKER=0）：排产任务会留在 queued 不被执行")
    stop = asyncio.Event()
    poller = None
    if ENVIRONMENT != "test":
        poller = asyncio.create_task(_adapter_loop(stop))
    try:
        yield
    finally:
        stop.set()
        if worker_started:
            job_queue.stop_worker()
        if poller:
            poller.cancel()
            try:
                await poller
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - 关闭期异常不再上报
                pass


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Liyang Intelligent Scheduling Agent — 三级智能体 + 七层底座的军工智能排产系统",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-LISA-Version"] = APP_VERSION
    return response


for module in (auth, dashboard, plans, agents, changes, kits, data, knowledge, mcp, audit, alerts, orders, system, jobs):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "environment": ENVIRONMENT}


@app.get("/api")
def api_root():
    return {"name": APP_NAME, "version": APP_VERSION, "docs": "/api/docs"}


dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if dist_dir.exists():
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        candidate = dist_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = dist_dir / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(status_code=404, content={"detail": "Frontend not built"})
else:

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "name": APP_NAME,
            "version": APP_VERSION,
            "message": "Frontend dist not found. Run `npm run build` in frontend/, or use Vite dev server.",
            "docs": "/api/docs",
        }
