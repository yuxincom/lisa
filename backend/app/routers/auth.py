from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import JWT_TTL_HOURS, ROLE_LABELS, ROLE_PERMISSIONS
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import LoginRequest
from ..security import create_token, verify_password
from ..services.audit import log_user_action
from ..services.serializers import user_to_dict

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username.strip()).first()
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        if user:
            log_user_action(db, user, "auth.login", "user", user.username, result="denied", detail={"reason": "bad credentials"})
            db.commit()
        raise HTTPException(status_code=401, detail={"code": "LOGIN_FAILED", "message": "账号或密码错误"})
    token = create_token(user.id, user.username, user.role, user.name)
    log_user_action(db, user, "auth.login", "user", user.username, detail={"ip": "intranet", "method": "password"})
    db.commit()
    return {
        "token": token,
        "token_type": "Bearer",
        "expires_in_hours": JWT_TTL_HOURS,
        "user": user_to_dict(user),
        "permissions": ROLE_PERMISSIONS.get(user.role, []),
        "role_label": ROLE_LABELS.get(user.role, user.role),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "user": user_to_dict(user),
        "permissions": ROLE_PERMISSIONS.get(user.role, []),
        "role_label": ROLE_LABELS.get(user.role, user.role),
    }


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log_user_action(db, user, "auth.logout", "user", user.username)
    db.commit()
    return {"ok": True}
