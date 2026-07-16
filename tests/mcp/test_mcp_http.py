"""Live Streamable HTTP MCP contract test for the Docker API."""

import asyncio
import json
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
                assert names == {
                    "md", "html", "screenshot", "pdf", "execute_js", "crawl", "ask",
                    "web_search", "camoufox_status", "camoufox_read", "camoufox_capture",
                }
                result = await session.call_tool("md", {"url": "https://example.com"})
                assert not result.isError
                md_payload = json.loads(result.content[0].text)
                assert "error" not in md_payload and md_payload["success"] is True
                search = await session.call_tool(
                    "web_search",
                    {"query": "Crawl4AI", "max_results": 5},
                )
                assert not search.isError
                search_payload = json.loads(search.content[0].text)
                assert "error" not in search_payload
                assert search_payload["result_count"] > 0
                assert search_payload["results"][0]["url"].startswith(("http://", "https://"))
                status = await session.call_tool("camoufox_status", {})
                assert not status.isError
                status_payload = json.loads(status.content[0].text)
                assert "error" not in status_payload
                assert status_payload["package_version"] == "0.6.0"
                assert status_payload["browser_present"] is True
                read = await session.call_tool(
                    "camoufox_read",
                    {"url": "https://example.com", "max_chars": 5000, "timeout_seconds": 60},
                )
                assert not read.isError
                read_payload = json.loads(read.content[0].text)
                assert "error" not in read_payload
                assert read_payload["success"] is True
                assert read_payload["browser"] == "camoufox"
                assert "Example Domain" in read_payload["text"]
                capture = await session.call_tool(
                    "camoufox_capture",
                    {"url": "https://example.com", "wait_seconds": 0, "timeout_seconds": 60},
                )
                assert not capture.isError
                capture_payload = json.loads(capture.content[0].text)
                assert "error" not in capture_payload
                assert capture_payload["success"] is True
                assert capture_payload["browser"] == "camoufox"
                assert capture_payload["mime"] == "image/png"
                assert capture_payload["size"] > 0


if __name__ == "__main__":
    asyncio.run(main())
