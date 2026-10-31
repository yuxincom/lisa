from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import has_permission
from .database import get_db
from .models import User
from .security import decode_token


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED", "message": "未登录或会话已过期"})
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail={"code": "AUTH_INVALID", "message": "凭证无效或已过期"})
    user = db.query(User).filter(User.username == payload["sub"], User.active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=401, detail={"code": "AUTH_USER_GONE", "message": "账号不可用"})
    return user


def require(permission: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(
                status_code=403,
                detail={"code": "ABAC_DENIED", "message": "ABAC 策略拒绝：当前角色无权执行该操作"},
            )
        return user

    return checker
