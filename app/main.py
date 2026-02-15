"""FastAPI routes for Notion Connection API."""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.config import API_KEY, JOB_TTL_SECONDS, REDIS_URL
from app.models import CapturePayload, CaptureAsyncResponse, JobNotFoundResponse
from app.redis_queue import enqueue_job, get_async_redis, get_job_status, set_job_status
from app.utils import utc_now_iso8601

logger = logging.getLogger(__name__)

# Global Redis client (lazy init)
_redis: Redis | None = None


def get_redis() -> Redis:
    """Get or create async Redis client."""
    global _redis
    if _redis is None:
        from app.redis_queue import get_async_redis
        _redis = get_async_redis(REDIS_URL)
    return _redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan: connect Redis on startup, close on shutdown."""
    get_redis()
    yield
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


app = FastAPI(
    title="Notion Connection API",
    description="Task capture and Notion integration for iPhone Shortcuts",
    lifespan=lifespan,
)


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Validate X-API-Key header. Raises HTTPException 401 if invalid."""
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Basic request logging: method, path, status, duration. Never log secrets."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s %d %.0fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/health")
async def health():
    """Health check."""
    return {"ok": True}


@app.post("/capture_async", response_model=CaptureAsyncResponse)
async def capture_async(
    payload: CapturePayload,
    x_api_key: str | None = Header(default=None),
):
    """
    Enqueue a task for async processing.
    Validates payload, writes initial job status to Redis, enqueues job.
    """
    _require_api_key(x_api_key)
    redis = get_redis()

    job_id = str(uuid.uuid4())
    payload_dict = payload.model_dump(mode="json")

    # Write initial queued status with TTL
    queued_status = {
        "status": "queued",
        "created_at": utc_now_iso8601(),
        "payload": payload_dict,
    }
    await set_job_status(redis, job_id, queued_status, ttl=JOB_TTL_SECONDS)

    # Enqueue job message (job_id + payload)
    await enqueue_job(redis, job_id, payload_dict)

    return CaptureAsyncResponse(
        ok=True,
        job_id=job_id,
        status_url=f"/jobs/{job_id}",
    )


@app.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    x_api_key: str | None = Header(default=None),
):
    """
    Get job status and result from Redis.
    Returns 404 if job not found or expired.
    """
    _require_api_key(x_api_key)
    redis = get_redis()

    job_data = await get_job_status(redis, job_id)
    if job_data is None:
        return JSONResponse(
            status_code=404,
            content=JobNotFoundResponse(ok=False, error="Job not found or expired").model_dump(),
        )
    return job_data


# Optional: sync capture endpoint
@app.post("/capture")
async def capture_sync(
    payload: CapturePayload,
    x_api_key: str | None = Header(default=None),
):
    """
    Sync capture: run Stage A; if need_deep_research, return 409 and instruct
    to use /capture_async. Otherwise run Notion write immediately.
    """
    _require_api_key(x_api_key)

    from app.openai_client import run_stage_a_async
    from app.notion_client import create_page

    task_date_str: str | None = None
    if payload.task_date:
        task_date_str = payload.task_date.isoformat()

    plan = await run_stage_a_async(
        payload.task_name,
        payload.task_content,
        task_date_str,
    )

    if plan.need_deep_research:
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "error": "Task requires deep research. Use POST /capture_async instead.",
                "use_capture_async": True,
            },
        )

    # Run sync Notion create in thread pool
    page_id, page_url = await asyncio.to_thread(
        create_page,
        plan,
        payload.task_content,
        task_date_str,
        None,
    )
    return {
        "ok": True,
        "notion": {"page_id": page_id, "page_url": page_url},
        "plan": plan.model_dump(),
    }
