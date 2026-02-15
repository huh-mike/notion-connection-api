"""Stage A/B orchestration and merge logic."""

import logging
from typing import Any

from app.config import JOB_TTL_SECONDS
from app.models import StageAOutput, StageBOutput
from app.notion_client import create_page as notion_create_page
from app.openai_client import run_stage_a_sync, run_stage_b_sync
from app.redis_queue import get_sync_redis, set_job_status_sync
from app.utils import utc_now_iso8601

logger = logging.getLogger(__name__)


def run_pipeline(redis_url: str, job_id: str, payload: dict[str, Any]) -> None:
    """
    Execute full pipeline: Stage A -> optional Stage B -> Notion create page.
    Updates Redis job status at each phase. Raises on error (caller saves failed status).
    """
    redis = get_sync_redis(redis_url)
    task_name = payload.get("task_name", "")
    task_content = payload.get("task_content", "")
    task_date_raw = payload.get("task_date")
    task_date_str: str | None = None
    if task_date_raw is not None:
        if hasattr(task_date_raw, "isoformat"):
            task_date_str = task_date_raw.isoformat()
        else:
            task_date_str = str(task_date_raw)

    # Stage A
    plan = run_stage_a_sync(task_name, task_content, task_date_str)
    plan_dict = plan.model_dump()

    # Stage B (optional)
    deep_research: StageBOutput | None = None
    deep_research_dict: dict[str, Any] | None = None
    if plan.need_deep_research and plan.deep_research_prompt:
        deep_research = run_stage_b_sync(plan.deep_research_prompt)
        deep_research_dict = deep_research.model_dump()

    # Notion
    page_id, page_url = notion_create_page(plan, task_content, task_date_str, deep_research)

    # Save succeeded status
    finished_at = utc_now_iso8601()
    result = {
        "status": "succeeded",
        "finished_at": finished_at,
        "notion": {"page_id": page_id, "page_url": page_url},
        "plan": plan_dict,
        "deep_research": deep_research_dict,
    }
    set_job_status_sync(redis, job_id, result, ttl=JOB_TTL_SECONDS)
    logger.info("Job %s succeeded, page_id=%s", job_id, page_id)
