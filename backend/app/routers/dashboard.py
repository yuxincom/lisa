from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import User
from ..services.impact import refresh_escalations
from ..services.metrics import dashboard_overview

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(require("dashboard:read"))):
    escalated = refresh_escalations(db)
    if escalated:
        from ..services.audit import log_user_action

        log_user_action(db, user, "approval.escalate", "approval", "batch", detail={"escalated": escalated})
    data = dashboard_overview(db)
    if escalated:
        db.commit()
    data["escalated_now"] = escalated
    return data
