"""Static contract for the single-image Camoufox fallback runtime."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "aio/runtime/pyproject.toml").read_text(encoding="utf-8")
UV_LOCK = (ROOT / "aio/runtime/uv.lock").read_text(encoding="utf-8")
LOCK = json.loads((ROOT / "aio/camoufox/components.lock.json").read_text(encoding="utf-8"))
WEB_TOOLS = (ROOT / "deploy/docker/aio_web_tools.py").read_text(encoding="utf-8")
SUPERVISOR = (ROOT / "deploy/docker/supervisord.conf").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/build-ghcr.yml").read_text(encoding="utf-8")


def test_latest_reviewed_camoufox_package_and_browser_are_consumed():
    package = LOCK["python_package"]
    browser = LOCK["browser"]
    assert package["name"] == "cloverlabs-camoufox"
    assert package["version"] == "0.6.0"
    assert f'"cloverlabs-camoufox=={package["version"]}"' in PYPROJECT
    assert f'name = "cloverlabs-camoufox"\nversion = "{package["version"]}"' in UV_LOCK
    assert 'name = "playwright"\nversion = "1.61.0"' in UV_LOCK
    assert f"ARG CAMOUFOX_BROWSER_VERSION={browser['version']}" in DOCKERFILE
    assert f"ARG CAMOUFOX_BROWSER_URL={browser['url']}" in DOCKERFILE
    assert f"ARG CAMOUFOX_BROWSER_SHA256={browser['sha256']}" in DOCKERFILE
    assert 'sha256sum -c -' in DOCKERFILE
    assert "with Camoufox(" in DOCKERFILE
    assert 'page.title() == "camoufox"' in DOCKERFILE


def test_camoufox_payload_is_installed_once_as_appuser():
    appuser_block = DOCKERFILE.split("USER appuser", 1)[1].split("USER root", 1)[0]
    assert "CAMOUFOX_CACHE_DIR}/browsers/official" in appuser_block
    assert "/root/.cache/camoufox" not in DOCKERFILE
    assert "camoufox_path(download_if_missing=False)" in appuser_block


def test_visible_camoufox_session_and_novnc_run_non_root():
    for program in ("xvfb", "fluxbox", "x11vnc", "novnc"):
        block = SUPERVISOR.split(f"[program:{program}]", 1)[1].split("[program:", 1)[0]
        assert "user=appuser" in block
    assert '"6080:6080"' in COMPOSE
    assert "localhost:6080/vnc.html" in COMPOSE
    assert "EXPOSE 11235 8080 6080" in DOCKERFILE


def test_agent_tool_surface_contains_search_and_camoufox_fallbacks():
    for tool in ("web_search", "camoufox_status", "camoufox_read", "camoufox_capture"):
        assert f'@mcp_tool("{tool}")' in WEB_TOOLS
    assert "get_egress_proxy()" in WEB_TOOLS
    assert '"proxy": {"server": proxy_url}' in WEB_TOOLS
    assert "CAMOUFOX_SEM" in WEB_TOOLS


def test_workflow_gates_and_labels_camoufox_provenance():
    assert "aio/camoufox/**" in WORKFLOW
    assert "scripts/aio-camoufox-verify --online" in WORKFLOW
    assert "GITHUB_TOKEN: ${{ github.token }}" in WORKFLOW
    assert "AIO_CAMOUFOX_PACKAGE_VERSION=" in WORKFLOW
    assert "AIO_CAMOUFOX_BROWSER_VERSION=" in WORKFLOW
    assert "AIO_CAMOUFOX_BROWSER_SHA256=" in WORKFLOW


def test_camoufox_verifier_does_not_require_gh_login():
    verifier = (ROOT / "scripts/aio-camoufox-verify").read_text(encoding="utf-8")
    assert "https://api.github.com/" in verifier
    assert '["gh", "api"' not in verifier
