"""Live Streamable HTTP MCP contract test for the Docker API."""

import asyncio
import json
import os

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


def payload(result) -> dict:
    assert not result.isError, result
    assert result.content and result.content[0].type == "text", result
    decoded = json.loads(result.content[0].text)
    assert isinstance(decoded, dict), f"MCP tool returned {type(decoded).__name__}, expected object"
    return decoded


async def main() -> None:
    url = os.environ.get("CRAWL4AI_MCP_HTTP_URL", "http://127.0.0.1:11235/mcp/http")
    token = os.environ["CRAWL4AI_API_TOKEN"]
    passed = []
    failures = []

    async def check(name, operation):
        try:
            await operation()
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        else:
            passed.append(name)
            print(f"[PASS] {name}")

    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def tool_discovery():
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    assert names == {
                        "md", "html", "screenshot", "pdf", "execute_js", "crawl", "ask",
                        "web_search", "camoufox_status", "camoufox_read", "camoufox_capture",
                    }

                async def md():
                    data = payload(await session.call_tool(
                        "md", {"url": "https://example.com", "f": "raw"}
                    ))
                    assert "error" not in data and data["success"] is True
                    assert "Example Domain" in data["markdown"]

                async def html():
                    data = payload(await session.call_tool("html", {"url": "https://example.com"}))
                    assert "error" not in data and data["success"] is True
                    assert "Example Domain" in data["html"]

                async def screenshot():
                    data = payload(await session.call_tool(
                        "screenshot",
                        {"url": "https://example.com", "screenshot_wait_for": 0},
                    ))
                    assert data["success"] is True and data["mime"] == "image/png"
                    assert data["artifact_id"] and data["size"] > 0

                async def pdf():
                    data = payload(await session.call_tool("pdf", {"url": "https://example.com"}))
                    assert data["success"] is True and data["mime"] == "application/pdf"
                    assert data["artifact_id"] and data["size"] > 0

                async def execute_js_policy():
                    data = payload(await session.call_tool(
                        "execute_js",
                        {"url": "https://example.com", "scripts": ["() => document.title"]},
                    ))
                    assert data.get("error") == 403, data

                async def crawl():
                    data = payload(await session.call_tool(
                        "crawl",
                        {"urls": ["https://example.com"], "browser_config": {}, "crawler_config": {}},
                    ))
                    assert "error" not in data and data["results"][0]["success"] is True

                async def ask():
                    data = payload(await session.call_tool(
                        "ask",
                        {"context_type": "doc", "query": "AsyncWebCrawler", "max_results": 3},
                    ))
                    assert "error" not in data and data.get("doc_results")

                async def web_search():
                    data = payload(await session.call_tool(
                        "web_search", {"query": "Crawl4AI", "max_results": 5}
                    ))
                    assert "error" not in data and data["result_count"] > 0
                    assert data["results"][0]["url"].startswith(("http://", "https://"))

                async def camoufox_status():
                    data = payload(await session.call_tool("camoufox_status", {}))
                    assert "error" not in data
                    assert data["package_version"] == "0.6.0"
                    assert data["browser_present"] is True

                async def camoufox_read():
                    data = payload(await session.call_tool(
                        "camoufox_read",
                        {"url": "https://example.com", "max_chars": 5000, "timeout_seconds": 60},
                    ))
                    assert "error" not in data and data["success"] is True
                    assert data["browser"] == "camoufox" and "Example Domain" in data["text"]

                async def camoufox_capture():
                    data = payload(await session.call_tool(
                        "camoufox_capture",
                        {"url": "https://example.com", "wait_seconds": 0, "timeout_seconds": 60},
                    ))
                    assert "error" not in data and data["success"] is True
                    assert data["browser"] == "camoufox" and data["mime"] == "image/png"
                    assert data["size"] > 0

                cases = (
                    ("tool_discovery", tool_discovery),
                    ("md", md),
                    ("html", html),
                    ("screenshot", screenshot),
                    ("pdf", pdf),
                    ("execute_js_default_policy", execute_js_policy),
                    ("crawl", crawl),
                    ("ask", ask),
                    ("web_search", web_search),
                    ("camoufox_status", camoufox_status),
                    ("camoufox_read", camoufox_read),
                    ("camoufox_capture", camoufox_capture),
                )
                for name, operation in cases:
                    await check(name, operation)

    print(f"MCP contract summary: {len(passed)} passed, {len(failures)} failed")
    if failures:
        raise AssertionError("MCP contract failures:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    asyncio.run(main())
