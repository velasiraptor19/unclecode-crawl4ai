"""Runtime contract checks executed inside a published Crawl4AI image."""

import asyncio
import importlib.util
import os
from pathlib import Path

import crawl4ai
import torch
from crawl4ai import AsyncWebCrawler, BrowserConfig
from playwright.sync_api import sync_playwright


HOME = Path(os.environ["HOME"])
BROWSER_ROOT = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])


def verify_browser_assets() -> None:
    expected = ("chromium-", "chromium_headless_shell-", "firefox-", "webkit-", "ffmpeg-")
    installed = tuple(path.name for path in BROWSER_ROOT.iterdir())
    for prefix in expected:
        assert any(name.startswith(prefix) for name in installed), f"missing browser asset: {prefix}"


def verify_browsers() -> None:
    with sync_playwright() as playwright:
        for browser_name in ("chromium", "firefox", "webkit"):
            browser = getattr(playwright, browser_name).launch()
            page = browser.new_page()
            page.set_content(f"<title>{browser_name}</title>")
            assert page.title() == browser_name
            browser.close()


def verify_cpu_variant() -> None:
    assert not torch.cuda.is_available(), "CPU image unexpectedly has an available CUDA device"
    for package in ("nvidia", "triton", "cuda"):
        assert importlib.util.find_spec(package) is None, f"CPU image contains {package}"


async def verify_crawl() -> None:
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(url="https://example.com")
    assert result.success, result.error_message


def main() -> None:
    assert crawl4ai.__version__ == "0.9.1"
    assert (HOME / ".cache" / "huggingface").is_dir(), "preloaded Hugging Face model missing"
    assert (HOME / "nltk_data").is_dir(), "preloaded NLTK data missing"
    verify_browser_assets()
    verify_cpu_variant()
    verify_browsers()
    asyncio.run(verify_crawl())
    print("runtime contract passed")


if __name__ == "__main__":
    main()
