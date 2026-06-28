"""
Thin client for calling notion-mcp over the MCP streamable-HTTP transport.
Keeps Notion auth (API key) in notion-mcp; mtg-agent only needs the server URL.
"""

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def update_deck_page(url: str, page_id: str, name: str, title: str) -> None:
    # Only sync Title from Moxfield; Name is managed manually in Notion
    # (Notion names often have manual suffixes like "✔️" that we don't want to overwrite)
    if not title:
        return

    properties: dict = {
        "Title": {"rich_text": [{"text": {"content": title}}]},
    }

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool(
                "notion_update_page_properties",
                {"page_id": page_id, "properties": properties},
            )


async def fetch_deck_page(url: str, page_id: str) -> dict | None:
    """Fetch a Notion deck page and return its properties and metadata."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("notion_get_page", {"page_id": page_id})
            for block in result.content:
                if hasattr(block, "text"):
                    import json
                    try:
                        return json.loads(block.text)
                    except (json.JSONDecodeError, TypeError):
                        return {"raw": block.text}
            return None
