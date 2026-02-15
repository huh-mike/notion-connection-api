"""Pydantic models for request/response and pipeline stages."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --- Input (iPhone Shortcuts) ---


class CapturePayload(BaseModel):
    """Input payload from iPhone Shortcuts or API clients."""

    model_config = ConfigDict(str_strip_whitespace=True)

    task_name: str
    client_time: datetime
    task_content: str
    source: str = "shortcut"
    task_date: datetime | None = None


# --- Stage A (planning) ---


class StageAOutput(BaseModel):
    """Strict JSON schema for Stage A planning output."""

    need_deep_research: bool
    deep_research_prompt: str | None = None
    research_todos: list[str] = Field(default_factory=list)
    human_todos: list[str] = Field(default_factory=list)
    notion_page_title: str
    summary: str
    tags: list[str] = Field(default_factory=list)


# --- Stage B (deep research) ---


class StageBOutput(BaseModel):
    """Structured output for Stage B deep research."""

    research_summary: str
    key_takeaways: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# --- Job status (Redis) ---


class JobQueued(BaseModel):
    """Job status when queued."""

    status: str = "queued"
    created_at: str  # ISO8601
    payload: dict[str, Any]


class JobRunning(BaseModel):
    """Job status when running."""

    status: str = "running"
    started_at: str  # ISO8601
    payload: dict[str, Any]


class JobSucceeded(BaseModel):
    """Job status when succeeded."""

    status: str = "succeeded"
    finished_at: str  # ISO8601
    notion: dict[str, str]  # page_id, page_url
    plan: dict[str, Any]  # StageAOutput
    deep_research: dict[str, Any] | None = None  # StageBOutput or null


class JobFailed(BaseModel):
    """Job status when failed."""

    status: str = "failed"
    finished_at: str  # ISO8601
    error: str


# --- API responses ---


class HealthResponse(BaseModel):
    """GET /health response."""

    ok: bool = True


class CaptureAsyncResponse(BaseModel):
    """POST /capture_async response."""

    ok: bool = True
    job_id: str
    status_url: str


class JobNotFoundResponse(BaseModel):
    """GET /jobs/{job_id} when not found."""

    ok: bool = False
    error: str = "Job not found or expired"
