from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=3, max_length=128)


class RunScenarioRequest(BaseModel):
    scenario: str = Field(default="full")
    change_id: int | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ApproveRequest(BaseModel):
    plan_id: int
    action: str = Field(pattern="^(approve|reject)$")
    comment: str = ""
    password: str = Field(min_length=3)


class ChangeCreateRequest(BaseModel):
    type: str
    title: str = Field(min_length=2, max_length=160)
    detail: str = ""
    severity: str = "warning"
    payload: dict[str, Any] = Field(default_factory=dict)


class KitCheckRequest(BaseModel):
    order_id: int
    checkpoint: str = "pre_start"


class AcknowledgeRequest(BaseModel):
    alert_ids: list[int] = Field(default_factory=list)


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class PlanCreateRequest(BaseModel):
    scenario: str = "A"
    change_id: int | None = None
    name: str | None = None


class FeedbackRequest(BaseModel):
    plan_id: int
    accepted: bool
    note: str = ""
