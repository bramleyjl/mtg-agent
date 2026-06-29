"""
Thin client for calling notion-mcp over the MCP streamable-HTTP transport.
Keeps Notion auth (API key) in notion-mcp; mtg-agent only needs the server URL.
"""

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def update_page_properties(url: str, page_id: str, properties: dict) -> None:
    """Update arbitrary properties on a Notion page using Notion API property format."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "notion_update_page_properties",
                {"page_id": page_id, "properties": properties},
            )
            if result.isError:
                msg = next((b.text for b in result.content if hasattr(b, "text")), "unknown error")
                raise RuntimeError(f"notion_update_page_properties failed: {msg}")


async def update_deck_page(url: str, page_id: str, name: str, title: str) -> None:
    # Only sync Title from Moxfield; Name is managed manually in Notion
    # (Notion names often have manual suffixes like "✔️" that we don't want to overwrite)
    if not title:
        return
    await update_page_properties(url, page_id, {
        "Title": {"rich_text": [{"text": {"content": title}}]},
    })


async def fetch_page(url: str, page_id: str) -> dict | None:
    """Fetch any Notion page by ID and return the raw Notion API response dict."""
    import json
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("notion_get_page", {"page_id": page_id})
            for block in result.content:
                if hasattr(block, "text"):
                    try:
                        return json.loads(block.text)
                    except (json.JSONDecodeError, TypeError):
                        return None
            return None


# Alias kept for callers that fetched deck pages before this refactor
fetch_deck_page = fetch_page
