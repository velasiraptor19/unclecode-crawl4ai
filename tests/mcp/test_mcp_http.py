"""Live Streamable HTTP MCP contract test for the Docker API."""

import asyncio
import os

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    url = os.environ.get("CRAWL4AI_MCP_HTTP_URL", "http://127.0.0.1:11235/mcp/http")
    token = os.environ["CRAWL4AI_API_TOKEN"]
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert names == {"md", "html", "screenshot", "pdf", "execute_js", "crawl", "ask"}
                result = await session.call_tool("md", {"url": "https://example.com"})
                assert not result.isError


if __name__ == "__main__":
    asyncio.run(main())
