from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_NAME, APP_VERSION, CORS_ORIGINS, ENVIRONMENT, JWT_SECRET, SEED_ON_START
from .database import Base, engine
from .routers import agents, alerts, audit, auth, changes, dashboard, data, kits, knowledge, orders, plans, system
from .seed import seed_if_empty

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    if SEED_ON_START:
        result = seed_if_empty()
        if result.get("seeded"):
            logger.info("Seed completed: %s", result)
        else:
            logger.info("Database already initialized: %s", result.get("reason"))
    if ENVIRONMENT == "production" and JWT_SECRET == "lisa-aecc-liyang-internal-secret-2026":
        logger.warning("JWT_SECRET is still the built-in default. Set a unique secret before exposing LISA.")
    logger.info("%s v%s starting in %s", APP_NAME, APP_VERSION, ENVIRONMENT)
    yield


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


for module in (auth, dashboard, plans, agents, changes, kits, data, knowledge, audit, alerts, orders, system):
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
