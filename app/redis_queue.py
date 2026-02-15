"""Redis helpers: enqueue jobs, read/write job status, BLPOP consumer."""

import json
import logging
from typing import Any

from redis.asyncio import Redis as AsyncRedis
from redis import Redis as SyncRedis

from app.config import JOB_TTL_SECONDS, JOB_KEY_PREFIX, QUEUE_JOBS_KEY
from app.utils import utc_now_iso8601

logger = logging.getLogger(__name__)


def get_async_redis(url: str) -> AsyncRedis:
    """Create async Redis client for FastAPI."""
    return AsyncRedis.from_url(url, decode_responses=True)


def get_sync_redis(url: str) -> SyncRedis:
    """Create sync Redis client for worker."""
    return SyncRedis.from_url(url, decode_responses=True)


def job_key(job_id: str) -> str:
    """Return Redis key for job status."""
    return f"{JOB_KEY_PREFIX}{job_id}"


# --- Async (Web service) ---


async def enqueue_job(redis: AsyncRedis, job_id: str, payload: dict[str, Any]) -> None:
    """Push job message to queue:jobs. Message is JSON: {job_id, payload}."""
    msg = json.dumps({"job_id": job_id, "payload": payload})
    await redis.rpush(QUEUE_JOBS_KEY, msg)
    logger.info("Enqueued job %s", job_id)


async def set_job_status(redis: AsyncRedis, job_id: str, status_data: dict[str, Any], ttl: int = JOB_TTL_SECONDS) -> None:
    """Write job status to Redis job:{job_id} with TTL."""
    key = job_key(job_id)
    data = json.dumps(status_data)
    await redis.set(key, data, ex=ttl)
    logger.debug("Set job %s status: %s", job_id, status_data.get("status", "unknown"))


async def get_job_status(redis: AsyncRedis, job_id: str) -> dict[str, Any] | None:
    """Read job status from Redis. Returns None if not found or expired."""
    key = job_key(job_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON for job %s", job_id)
        return None


# --- Sync (Worker) ---


def blpop_job(redis: SyncRedis, timeout: int = 30) -> tuple[str, dict[str, Any]] | None:
    """
    Blocking pop from queue:jobs. Returns (job_id, payload) or None on timeout.
    """
    result = redis.blpop(QUEUE_JOBS_KEY, timeout=timeout)
    if result is None:
        return None
    _, msg = result
    try:
        data = json.loads(msg)
        return data["job_id"], data["payload"]
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Invalid queue message: %s", e)
        return None


def set_job_status_sync(redis: SyncRedis, job_id: str, status_data: dict[str, Any], ttl: int = JOB_TTL_SECONDS) -> None:
    """Write job status to Redis (sync)."""
    key = job_key(job_id)
    data = json.dumps(status_data)
    redis.set(key, data, ex=ttl)
    logger.debug("Set job %s status: %s", job_id, status_data.get("status", "unknown"))


def get_job_status_sync(redis: SyncRedis, job_id: str) -> dict[str, Any] | None:
    """Read job status from Redis (sync)."""
    key = job_key(job_id)
    raw = redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON for job %s", job_id)
        return None
