import os
from typing import Any

import httpx

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers() -> dict[str, str]:
    token = os.getenv("NOTION_API_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


async def update_deck_page(notion_id: str, name: str, title: str) -> None:
    """Update the Name (title) and Title (text) properties on a Notion deck page."""
    payload: dict[str, Any] = {
        "properties": {
            "Name": {
                "title": [{"text": {"content": name}}]
            },
        }
    }
    if title:
        payload["properties"]["Title"] = {
            "rich_text": [{"text": {"content": title}}]
        }

    async with httpx.AsyncClient(headers=_headers(), timeout=10.0) as client:
        response = await client.patch(
            f"{NOTION_API}/pages/{notion_id}",
            json=payload,
        )
        response.raise_for_status()
