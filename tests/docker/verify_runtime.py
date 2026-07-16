"""Runtime contract checks executed inside a published Crawl4AI image."""

import asyncio
import importlib.util
import os
import re
import tomllib
from collections import defaultdict
from pathlib import Path
from importlib.metadata import distributions, version

import torch
from crawl4ai import AsyncWebCrawler, BrowserConfig
from packaging.requirements import Requirement
from playwright.sync_api import sync_playwright


HOME = Path(os.environ["HOME"])
BROWSER_ROOT = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
RUNTIME_LOCK = Path("/opt/crawl4ai/aio-runtime.uv.lock")


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def verify_locked_environment() -> None:
    lock = tomllib.loads(RUNTIME_LOCK.read_text(encoding="utf-8"))
    locked_versions: dict[str, set[str]] = defaultdict(set)
    runtime_dependencies: set[str] = set()
    for package in lock["package"]:
        name = canonical_name(package["name"])
        locked_versions[name].add(package["version"])
        if name == "crawl4ai-aio-runtime":
            runtime_dependencies = {
                canonical_name(dependency["name"])
                for dependency in package.get("dependencies", ())
            }

    installed = {
        canonical_name(distribution.metadata["Name"]): distribution
        for distribution in distributions()
    }
    unexpected = sorted(set(installed) - set(locked_versions))
    assert not unexpected, f"installed distributions absent from runtime lock: {unexpected}"

    mismatches = []
    for name, distribution in installed.items():
        if distribution.version not in locked_versions[name]:
            mismatches.append(
                f"{name}=={distribution.version} not in {sorted(locked_versions[name])}"
            )
    assert not mismatches, f"installed versions differ from runtime lock: {mismatches}"

    missing_direct = sorted(runtime_dependencies - set(installed))
    assert not missing_direct, f"locked direct runtime dependencies missing: {missing_direct}"

    broken = []
    for name, distribution in installed.items():
        for requirement_text in distribution.requires or ():
            requirement = Requirement(requirement_text)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            dependency_name = canonical_name(requirement.name)
            dependency = installed.get(dependency_name)
            if dependency is None:
                broken.append(f"{name} requires missing {requirement}")
            elif requirement.specifier and dependency.version not in requirement.specifier:
                broken.append(
                    f"{name} requires {requirement}, installed {dependency.version}"
                )
    assert not broken, f"runtime dependency metadata is inconsistent: {broken}"


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
    assert version("Crawl4AI") == "0.9.2"
    verify_locked_environment()
    assert (HOME / ".cache" / "huggingface").is_dir(), "preloaded Hugging Face model missing"
    assert (HOME / "nltk_data").is_dir(), "preloaded NLTK data missing"
    verify_browser_assets()
    verify_cpu_variant()
    verify_browsers()
    asyncio.run(verify_crawl())
    print("runtime contract passed")


if __name__ == "__main__":
    main()
