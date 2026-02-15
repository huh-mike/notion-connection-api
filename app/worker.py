"""Background worker entrypoint: BLPOP from queue, run pipeline, write results."""

import logging
import os
import signal
import sys

# Load .env for local development before importing app modules
from pathlib import Path
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

from app.config import JOB_TTL_SECONDS, REDIS_URL
from app.pipeline import run_pipeline
from app.redis_queue import blpop_job, get_sync_redis, set_job_status_sync
from app.utils import utc_now_iso8601

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

_shutdown = False


def _handle_signal(signum: int, frame) -> None:
    global _shutdown
    logger.info("Received signal %s, shutting down gracefully", signum)
    _shutdown = True


def main() -> None:
    """Long-running loop: BLPOP queue, run pipeline, update Redis job status."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    redis = get_sync_redis(REDIS_URL)
    logger.info("Worker started, consuming from queue:jobs")

    while not _shutdown:
        result = blpop_job(redis, timeout=30)
        if result is None:
            continue

        job_id, payload = result
        logger.info("Processing job %s", job_id)

        # Update status to running
        running_status = {
            "status": "running",
            "started_at": utc_now_iso8601(),
            "payload": payload,
        }
        set_job_status_sync(redis, job_id, running_status, ttl=JOB_TTL_SECONDS)

        try:
            run_pipeline(REDIS_URL, job_id, payload)
        except Exception as e:
            logger.exception("Job %s failed: %s", job_id, e)
            failed_status = {
                "status": "failed",
                "finished_at": utc_now_iso8601(),
                "error": str(e),
            }
            set_job_status_sync(redis, job_id, failed_status, ttl=JOB_TTL_SECONDS)

    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    main()
