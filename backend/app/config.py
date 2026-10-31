from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


_load_dotenv(BASE_DIR.parent / ".env")

DATA_DIR = Path(os.getenv("LISA_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'lisa.db').as_posix()}")
JWT_SECRET = os.getenv("JWT_SECRET", "lisa-aecc-liyang-internal-secret-2026")
JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "12"))

APP_NAME = "LISA 黎阳智能排产智能体"
APP_VERSION = "1.0.0"
ENVIRONMENT = os.getenv("LISA_ENV", "production")
SEED_ON_START = os.getenv("LISA_SEED", "1") == "1"

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if origin.strip()
]

# 时间基准：服务器本地时区（生产环境按内网 NTP 校时）
TZ_OFFSET_HOURS = int(os.getenv("LISA_TZ_OFFSET", "8"))

ROLE_LABELS = {
    "admin": "系统管理员",
    "commander": "生产指挥部",
    "planner": "计划员",
    "dispatcher": "调度员",
    "engineer": "工艺员",
    "expert": "领域专家",
}

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["*"],
    "commander": [
        "dashboard:read", "plans:read", "plans:approve", "agents:read", "agents:run",
        "changes:read", "changes:approve", "kits:read", "data:read", "knowledge:read",
        "audit:read", "alerts:read", "alerts:ack", "settings:read", "export:read",
    ],
    "planner": [
        "dashboard:read", "plans:read", "plans:create", "plans:submit", "plans:approve",
        "agents:read", "agents:run", "changes:read", "changes:create", "changes:approve",
        "kits:read", "data:read", "knowledge:read", "audit:read", "alerts:read",
        "alerts:ack", "settings:read", "export:read",
    ],
    "dispatcher": [
        "dashboard:read", "plans:read", "agents:read", "agents:run", "changes:read",
        "changes:create", "kits:read", "data:read", "knowledge:read", "alerts:read",
        "alerts:ack",
    ],
    "engineer": [
        "dashboard:read", "plans:read", "agents:read", "changes:read", "kits:read",
        "data:read", "knowledge:read", "alerts:read",
    ],
    "expert": [
        "dashboard:read", "plans:read", "agents:read", "agents:run", "changes:read",
        "kits:read", "data:read", "knowledge:read", "audit:read", "alerts:read",
    ],
}


def has_permission(role: str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, [])
    return "*" in perms or permission in perms
