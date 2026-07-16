"""Agent-facing search and Camoufox fallback tools for the AIO image."""

from __future__ import annotations

import asyncio
import os
from importlib.metadata import version
from pathlib import Path
from typing import Dict, List

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_token_dependency
from egress_broker import get_egress_proxy
from mcp_bridge import mcp_tool
from utils import validate_url_scheme


router = APIRouter(tags=["aio-web"])
token_dep = get_token_dependency()
CAMOUFOX_SEM = asyncio.Semaphore(int(os.environ.get("CAMOUFOX_MAX_CONCURRENCY", "1")))
CAMOUFOX_WEBGL = ("Intel", "Intel(R) HD Graphics, or similar")


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    engines: List[str] = Field(default_factory=list, max_length=10)
    language: str = Field(default="all", min_length=2, max_length=20)
    max_results: int = Field(default=10, ge=1, le=20)


class CamoufoxReadRequest(BaseModel):
    url: str
    max_chars: int = Field(default=30000, ge=1000, le=100000)
    timeout_seconds: int = Field(default=60, ge=5, le=180)


class CamoufoxCaptureRequest(BaseModel):
    url: str
    full_page: bool = True
    wait_seconds: float = Field(default=2.0, ge=0, le=20)
    timeout_seconds: int = Field(default=60, ge=5, le=180)


def _camoufox_launch_options() -> dict:
    proxy_url = get_egress_proxy()
    if not proxy_url:
        raise HTTPException(503, "Camoufox egress proxy is not ready")
    from camoufox.addons import DefaultAddons

    return {
        "headless": False,
        "virtual_display": os.environ.get("DISPLAY", ":99"),
        "os": "linux",
        "fingerprint_preset": True,
        "webgl_config": CAMOUFOX_WEBGL,
        "exclude_addons": list(DefaultAddons),
        "proxy": {"server": proxy_url},
    }


async def _open_camoufox(url: str, timeout_seconds: int):
    validate_url_scheme(url)
    from camoufox.async_api import AsyncCamoufox

    browser_manager = AsyncCamoufox(**_camoufox_launch_options())
    browser = await browser_manager.__aenter__()
    try:
        page = await browser.new_page()
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=timeout_seconds * 1000,
        )
        return browser_manager, page
    except Exception:
        await browser_manager.__aexit__(None, None, None)
        raise


@router.post("/web/search")
@mcp_tool("web_search")
async def web_search(body: WebSearchRequest, _td: Dict = Depends(token_dep)):
    """Search the web through the image's local SearXNG JSON API."""
    params = {
        "q": body.query,
        "format": "json",
        "language": body.language,
    }
    if body.engines:
        params["engines"] = ",".join(body.engines)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get("http://127.0.0.1:8080/search", params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"SearXNG search failed: {exc}") from exc

    results = []
    for item in payload.get("results", [])[: body.max_results]:
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("content"),
            "engine": item.get("engine"),
            "engines": item.get("engines", []),
            "score": item.get("score"),
        })
    return {
        "query": body.query,
        "results": results,
        "result_count": len(results),
        "unresponsive_engines": payload.get("unresponsive_engines", []),
    }


@router.get("/camoufox/status")
@mcp_tool("camoufox_status")
async def camoufox_status(_td: Dict = Depends(token_dep)):
    """Report the pinned Camoufox package and active browser runtime."""
    from camoufox.pkgman import camoufox_path, installed_verstr

    browser_path = Path(camoufox_path(download_if_missing=False))
    return {
        "package": "cloverlabs-camoufox",
        "package_version": version("cloverlabs-camoufox"),
        "browser_version": installed_verstr(),
        "browser_path": str(browser_path),
        "browser_present": browser_path.is_dir(),
        "display": os.environ.get("DISPLAY", ":99"),
        "novnc_port": 6080,
    }


@router.post("/camoufox/read")
@mcp_tool("camoufox_read")
async def camoufox_read(body: CamoufoxReadRequest, _td: Dict = Depends(token_dep)):
    """Read a difficult page using the explicit Camoufox browser fallback."""
    async with CAMOUFOX_SEM:
        manager = None
        try:
            async with asyncio.timeout(body.timeout_seconds + 10):
                manager, page = await _open_camoufox(body.url, body.timeout_seconds)
                title = await page.title()
                final_url = page.url
                text = await page.locator("body").inner_text(timeout=body.timeout_seconds * 1000)
                return {
                    "success": True,
                    "url": final_url,
                    "title": title,
                    "text": text[: body.max_chars],
                    "truncated": len(text) > body.max_chars,
                    "browser": "camoufox",
                }
        except TimeoutError as exc:
            raise HTTPException(504, "Camoufox request timed out") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"Camoufox read failed: {exc}") from exc
        finally:
            if manager is not None:
                await manager.__aexit__(None, None, None)


@router.post("/camoufox/capture")
@mcp_tool("camoufox_capture")
async def camoufox_capture(body: CamoufoxCaptureRequest, _td: Dict = Depends(token_dep)):
    """Capture a page with Camoufox and store the PNG in the artifact store."""
    async with CAMOUFOX_SEM:
        manager = None
        try:
            async with asyncio.timeout(body.timeout_seconds + body.wait_seconds + 10):
                manager, page = await _open_camoufox(body.url, body.timeout_seconds)
                if body.wait_seconds:
                    await asyncio.sleep(body.wait_seconds)
                png = await page.screenshot(full_page=body.full_page)
                from artifacts import write_artifact

                artifact = write_artifact("png", png)
                return {
                    "success": True,
                    "url": page.url,
                    "title": await page.title(),
                    "browser": "camoufox",
                    "artifact_id": artifact["artifact_id"],
                    "artifact_url": f"/artifacts/{artifact['artifact_id']}",
                    "mime": artifact["mime"],
                    "size": artifact["size"],
                }
        except TimeoutError as exc:
            raise HTTPException(504, "Camoufox capture timed out") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"Camoufox capture failed: {exc}") from exc
        finally:
            if manager is not None:
                await manager.__aexit__(None, None, None)
