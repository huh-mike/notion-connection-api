"""OpenAI Responses API client for planning and deep research."""

import logging
from typing import Any

from openai import AsyncOpenAI, OpenAI

from app.config import OPENAI_API_KEY, OPENAI_PROJECT_ID, MODEL_PLAN, MODEL_RESEARCH
from app.models import StageAOutput, StageBOutput
from app.utils import extract_json_from_text, retry_async, retry_sync

logger = logging.getLogger(__name__)

# Timeouts (seconds)
PLAN_TIMEOUT = 60.0
RESEARCH_TIMEOUT = 600.0

# Stage A system prompt - enforces strict JSON output
STAGE_A_INSTRUCTIONS = """You are a task planning assistant. Given a task from the user, output a STRICT JSON object only. No markdown, no explanations. Output ONLY valid JSON matching this schema exactly:

{
  "need_deep_research": boolean,
  "deep_research_prompt": string | null,
  "research_todos": string[],
  "human_todos": string[],
  "notion_page_title": string,
  "summary": string,
  "tags": string[]
}

Rules:
- need_deep_research: true only if the task requires web research, external data, or non-obvious facts. false for straightforward execution tasks.
- deep_research_prompt: exactly one detailed research question if need_deep_research is true; otherwise null.
- research_todos: items requiring research before human action.
- human_todos: atomic, checkbox-ready action items for the user.
- notion_page_title: concise title for the Notion page.
- summary: brief task summary.
- tags: optional labels for the page.
Output JSON only."""

REPAIR_PROMPT = """Your previous response was not valid JSON. Please output ONLY a valid JSON object, no other text. Match the schema: need_deep_research, deep_research_prompt, research_todos, human_todos, notion_page_title, summary, tags."""

# Stage B system prompt
STAGE_B_INSTRUCTIONS = """You are a deep research assistant. Given a research prompt, output a STRICT JSON object only:

{
  "research_summary": string,
  "key_takeaways": string[],
  "sources": string[]
}

- research_summary: comprehensive summary of findings.
- key_takeaways: bullet points of main findings.
- sources: URLs or references if available.
Output JSON only."""


def _get_client_async() -> AsyncOpenAI:
    """Create async OpenAI client with project ID if set."""
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_PROJECT_ID:
        kwargs["project"] = OPENAI_PROJECT_ID
    return AsyncOpenAI(**kwargs)


def _extract_output_text(response: Any) -> str:
    """Extract text from Responses API response (output_text or output[].content[].text)."""
    if hasattr(response, "output_text") and response.output_text:
        return str(response.output_text)
    if hasattr(response, "output") and response.output:
        for item in response.output:
            if hasattr(item, "content") and item.content:
                for block in item.content:
                    if hasattr(block, "text") and block.text:
                        return str(block.text)
    return ""


def _get_client_sync() -> OpenAI:
    """Create sync OpenAI client with project ID if set."""
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_PROJECT_ID:
        kwargs["project"] = OPENAI_PROJECT_ID
    return OpenAI(**kwargs)


# --- Async (for optional sync endpoint via run_in_executor if needed) ---


async def run_stage_a_async(task_name: str, task_content: str, task_date: str | None = None) -> StageAOutput:
    """
    Run Stage A (planning) via OpenAI Responses API.
    Returns parsed StageAOutput. Retries once with repair prompt if JSON parse fails.
    """
    user_input = f"Task name: {task_name}\nTask content: {task_content}"
    if task_date:
        user_input += f"\nTask date: {task_date}"

    client = _get_client_async()

    async def _call():
        return await client.responses.create(
            model=MODEL_PLAN,
            instructions=STAGE_A_INSTRUCTIONS,
            input=user_input,
            timeout=PLAN_TIMEOUT,
        )

    response = await retry_async(_call, max_retries=2)
    text = _extract_output_text(response)

    parsed = _parse_stage_a(text)
    if parsed is not None:
        return parsed

    # Retry with repair prompt
    logger.warning("Stage A JSON parse failed, retrying with repair prompt")
    repair_response = await client.responses.create(
        model=MODEL_PLAN,
        instructions=REPAIR_PROMPT,
        input=text or "No output.",
        timeout=PLAN_TIMEOUT,
    )
    repair_text = _extract_output_text(repair_response)
    repair_parsed = _parse_stage_a(repair_text)
    if repair_parsed is not None:
        return repair_parsed

    raise ValueError("Could not parse Stage A output as valid JSON after retry")


def _parse_stage_a(text: str) -> StageAOutput | None:
    """Parse Stage A text into StageAOutput. Returns None on failure."""
    if not text:
        return None
    data = extract_json_from_text(text)
    if data is None:
        return None
    try:
        return StageAOutput.model_validate(data)
    except Exception:
        return None


async def run_stage_b_async(prompt: str) -> StageBOutput:
    """Run Stage B (deep research) via OpenAI Responses API."""
    client = _get_client_async()

    async def _call():
        return await client.responses.create(
            model=MODEL_RESEARCH,
            instructions=STAGE_B_INSTRUCTIONS,
            input=prompt,
            tools=[{"type": "web_search_preview"}],
            timeout=RESEARCH_TIMEOUT,
        )

    response = await retry_async(_call, max_retries=2)
    text = _extract_output_text(response)

    data = extract_json_from_text(text)
    if data is None:
        raise ValueError("Could not parse Stage B output as valid JSON")
    return StageBOutput.model_validate(data)


# --- Sync (for worker) ---


def run_stage_a_sync(task_name: str, task_content: str, task_date: str | None = None) -> StageAOutput:
    """Sync Stage A for worker."""
    user_input = f"Task name: {task_name}\nTask content: {task_content}"
    if task_date:
        user_input += f"\nTask date: {task_date}"

    client = _get_client_sync()

    def _call():
        return client.responses.create(
            model=MODEL_PLAN,
            instructions=STAGE_A_INSTRUCTIONS,
            input=user_input,
            timeout=PLAN_TIMEOUT,
        )

    response = retry_sync(_call, max_retries=2)
    text = _extract_output_text(response)

    parsed = _parse_stage_a(text)
    if parsed is not None:
        return parsed

    logger.warning("Stage A JSON parse failed, retrying with repair prompt")
    repair_response = client.responses.create(
        model=MODEL_PLAN,
        instructions=REPAIR_PROMPT,
        input=text or "No output.",
        timeout=PLAN_TIMEOUT,
    )
    repair_text = _extract_output_text(repair_response)
    repair_parsed = _parse_stage_a(repair_text)
    if repair_parsed is not None:
        return repair_parsed

    raise ValueError("Could not parse Stage A output as valid JSON after retry")


def run_stage_b_sync(prompt: str) -> StageBOutput:
    """Sync Stage B for worker."""
    client = _get_client_sync()

    def _call():
        return client.responses.create(
            model=MODEL_RESEARCH,
            instructions=STAGE_B_INSTRUCTIONS,
            input=prompt,
            tools=[{"type": "web_search_preview"}],
            timeout=RESEARCH_TIMEOUT,
        )

    response = retry_sync(_call, max_retries=2)
    text = _extract_output_text(response)

    data = extract_json_from_text(text)
    if data is None:
        raise ValueError("Could not parse Stage B output as valid JSON")
    return StageBOutput.model_validate(data)
