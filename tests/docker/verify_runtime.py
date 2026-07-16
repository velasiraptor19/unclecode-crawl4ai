"""Runtime contract checks executed inside a published Crawl4AI image."""

import asyncio
import importlib.util
import json
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
    locked_names: set[str] = set()
    locked_versions: dict[str, set[str]] = defaultdict(set)
    versionless_sources: set[str] = set()
    runtime_dependencies: set[str] = set()
    for package in lock["package"]:
        name = canonical_name(package["name"])
        locked_names.add(name)
        package_version = package.get("version")
        if package_version is not None:
            locked_versions[name].add(package_version)
        else:
            assert "directory" in package.get("source", {}), (
                f"versionless lock package is not a local source: {name}"
            )
            versionless_sources.add(name)
        if name == "crawl4ai-aio-runtime":
            runtime_dependencies = {
                canonical_name(dependency["name"])
                for dependency in package.get("dependencies", ())
            }
    assert versionless_sources == {"crawl4ai"}, (
        f"unexpected versionless local lock packages: {sorted(versionless_sources)}"
    )

    installed = {
        canonical_name(distribution.metadata["Name"]): distribution
        for distribution in distributions()
    }
    unexpected = sorted(set(installed) - locked_names)
    assert not unexpected, f"installed distributions absent from runtime lock: {unexpected}"

    mismatches = []
    for name, distribution in installed.items():
        if name in locked_versions and distribution.version not in locked_versions[name]:
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


def default_browser_manifest(package_name: str) -> dict[str, str]:
    spec = importlib.util.find_spec(package_name)
    assert spec and spec.submodule_search_locations, f"cannot locate {package_name} package"
    package_root = Path(next(iter(spec.submodule_search_locations)))
    manifest = json.loads(
        (package_root / "driver" / "package" / "browsers.json").read_text(encoding="utf-8")
    )
    return {
        browser["name"]: str(browser["revision"])
        for browser in manifest["browsers"]
        if browser.get("installByDefault")
    }


def verify_browser_assets() -> None:
    playwright_manifest = default_browser_manifest("playwright")
    patchright_manifest = default_browser_manifest("patchright")
    assert patchright_manifest == playwright_manifest, (
        f"Playwright/Patchright browser revisions differ: "
        f"{playwright_manifest} != {patchright_manifest}"
    )
    expected = {
        f"{name.replace('-', '_')}-{revision}"
        for name, revision in playwright_manifest.items()
    }
    prefixes = tuple(f"{name.replace('-', '_')}-" for name in playwright_manifest)
    installed = {
        path.name
        for path in BROWSER_ROOT.iterdir()
        if path.is_dir() and path.name.startswith(prefixes)
    }
    assert installed == expected, f"unexpected Playwright asset set: {sorted(installed)}"


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
