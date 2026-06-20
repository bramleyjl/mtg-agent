"""
Thin client for calling notion-mcp over the MCP streamable-HTTP transport.
Keeps Notion auth (API key) in notion-mcp; mtg-agent only needs the server URL.
"""

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def update_deck_page(url: str, page_id: str, name: str, title: str) -> None:
    properties: dict = {
        "Name": {"title": [{"text": {"content": name}}]},
    }
    if title:
        properties["Title"] = {"rich_text": [{"text": {"content": title}}]}

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool(
                "notion_update_page_properties",
                {"page_id": page_id, "properties": properties},
            )


async def fetch_deck_page(url: str, page_id: str) -> str | None:
    """Fetch a Notion deck page and return its rendered content."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("notion-fetch", {"id": page_id})
            for block in result.content:
                if hasattr(block, "text"):
                    return block.text
            return None
