"""Notion API client for creating pages."""

import logging
from typing import Any

import httpx

from app.config import (
    NOTION_DATABASE_ID,
    NOTION_DUE_PROP,
    NOTION_INTEGRATION_SECRET,
    NOTION_TITLE_PROP,
    NOTION_VERSION,
)
from app.models import StageAOutput, StageBOutput
from app.utils import retry_sync

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_TIMEOUT = 30.0


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_INTEGRATION_SECRET}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _build_blocks(
    task_content: str,
    summary: str,
    human_todos: list[str],
    deep_research: StageBOutput | None,
) -> list[dict[str, Any]]:
    """Build Notion page children blocks."""
    blocks: list[dict[str, Any]] = [
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": task_content}}]}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": summary}}]}},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Todos"}}]}},
    ]
    for todo in human_todos:
        blocks.append({
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [{"type": "text", "text": {"content": todo}}],
                "checked": False,
            },
        })
    if deep_research:
        blocks.extend([
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Deep Research"}}]}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": deep_research.research_summary}}]}},
            {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "Key takeaways"}}]}},
        ])
        for takeaway in deep_research.key_takeaways:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": takeaway}}]},
            })
        blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "Sources"}}]}})
        for source in deep_research.sources:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": source}}]},
            })
    return blocks


def _build_properties(
    notion_page_title: str,
    task_date: str | None,
) -> dict[str, Any]:
    """Build Notion page properties including optional due date."""
    props: dict[str, Any] = {
        NOTION_TITLE_PROP: {"title": [{"type": "text", "text": {"content": notion_page_title}}]},
    }
    if NOTION_DUE_PROP and task_date:
        props[NOTION_DUE_PROP] = {"date": {"start": task_date}}
    return props


def create_page(
    plan: StageAOutput,
    task_content: str,
    task_date: str | None,
    deep_research: StageBOutput | None = None,
) -> tuple[str, str]:
    """
    Create a Notion page in the configured database.
    Returns (page_id, page_url).
    """
    blocks = _build_blocks(task_content, plan.summary, plan.human_todos, deep_research)
    properties = _build_properties(plan.notion_page_title, task_date)

    body: dict[str, Any] = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
        "children": blocks,
    }

    def _post() -> httpx.Response:
        with httpx.Client(timeout=NOTION_TIMEOUT) as client:
            resp = client.post(
                f"{NOTION_API_BASE}/pages",
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()
            return resp

    response = retry_sync(_post, max_retries=2)
    data = response.json()
    page_id = data.get("id", "")
    page_url = data.get("url", "") or f"https://www.notion.so/{page_id.replace('-', '')}"
    return page_id, page_url
