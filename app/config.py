"""Environment loading and configuration constants."""

import os
from pathlib import Path

# Load .env for local development only (Render injects env vars)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

# Security
API_KEY: str = os.getenv("API_KEY", "")

# Notion
NOTION_INTEGRATION_SECRET: str = os.getenv("NOTION_INTEGRATION_SECRET", "")
NOTION_DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")
NOTION_TITLE_PROP: str = os.getenv("NOTION_TITLE_PROP", "Name")
NOTION_DUE_PROP: str | None = os.getenv("NOTION_DUE_PROP") or None
NOTION_VERSION: str = os.getenv("NOTION_VERSION", "2022-06-28")

# OpenAI
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_PROJECT_ID: str = os.getenv("OPENAI_PROJECT_ID", "")
MODEL_PLAN: str = os.getenv("MODEL_PLAN", "gpt-4o-mini")
MODEL_RESEARCH: str = os.getenv("MODEL_RESEARCH", "gpt-4o")

# Redis
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_TTL_SECONDS: int = int(os.getenv("JOB_TTL_SECONDS", "21600"))

# Queue
QUEUE_JOBS_KEY: str = "queue:jobs"
JOB_KEY_PREFIX: str = "job:"
