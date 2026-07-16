"""Static contract for the single-image Camoufox fallback runtime."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "aio/runtime/pyproject.toml").read_text(encoding="utf-8")
UV_LOCK = (ROOT / "aio/runtime/uv.lock").read_text(encoding="utf-8")
LOCK = json.loads((ROOT / "aio/camoufox/components.lock.json").read_text(encoding="utf-8"))
WEB_TOOLS = (ROOT / "deploy/docker/aio_web_tools.py").read_text(encoding="utf-8")
UTILS = (ROOT / "deploy/docker/utils.py").read_text(encoding="utf-8")
AUTH = (ROOT / "deploy/docker/auth.py").read_text(encoding="utf-8")
SUPERVISOR = (ROOT / "deploy/docker/supervisord.conf").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/build-ghcr.yml").read_text(encoding="utf-8")
MCP_BRIDGE = (ROOT / "deploy/docker/mcp_bridge.py").read_text(encoding="utf-8")
REST_VERIFY = (ROOT / "tests/docker/verify_aio_rest.py").read_text(encoding="utf-8")
EGRESS_PROXY = (ROOT / "deploy/docker/egress_proxy.py").read_text(encoding="utf-8")


def test_latest_reviewed_camoufox_package_and_browser_are_consumed():
    package = LOCK["python_package"]
    browser = LOCK["browser"]
    assert package["name"] == "cloverlabs-camoufox"
    assert package["version"] == "0.6.0"
    assert f'"cloverlabs-camoufox=={package["version"]}"' in PYPROJECT
    assert f'name = "cloverlabs-camoufox"\nversion = "{package["version"]}"' in UV_LOCK
    assert '"playwright==1.60.0"' in PYPROJECT
    assert '"patchright==1.60.0"' in PYPROJECT
    assert 'name = "playwright"\nversion = "1.60.0"' in UV_LOCK
    assert 'name = "patchright"\nversion = "1.60.0"' in UV_LOCK
    assert f"ARG CAMOUFOX_BROWSER_VERSION={browser['version']}" in DOCKERFILE
    assert f"ARG CAMOUFOX_BROWSER_URL={browser['url']}" in DOCKERFILE
    assert f"ARG CAMOUFOX_BROWSER_SHA256={browser['sha256']}" in DOCKERFILE
    assert 'sha256sum -c -' in DOCKERFILE
    assert "with Camoufox(" in DOCKERFILE
    assert 'page.title() == "camoufox"' in DOCKERFILE


def test_playwright_and_patchright_share_one_browser_revision_set():
    assert 'default_browser_manifest("playwright")' in DOCKERFILE
    assert 'default_browser_manifest("patchright")' in DOCKERFILE
    assert "patchright_manifest == playwright_manifest" in DOCKERFILE
    assert "chromium-1228" not in DOCKERFILE


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
    assert 'CAMOUFOX_WEBGL = ("Intel", "Intel(R) HD Graphics, or similar")' in WEB_TOOLS
    assert '"os": "linux"' in WEB_TOOLS
    assert '"webgl_config": CAMOUFOX_WEBGL' in WEB_TOOLS
    assert 'webgl_config=("Intel", "Intel(R) HD Graphics, or similar")' in DOCKERFILE
    assert "def validate_url_scheme" in UTILS
    assert "validate_url_destination(url)" in UTILS
    assert 'public_host = "localhost" if self.bound_host == "127.0.0.1"' in EGRESS_PROXY


def test_final_image_imports_server_as_runtime_user_during_build():
    final_appuser_block = DOCKERFILE.rsplit("USER appuser", 1)[1]
    assert 'python -c "import server; assert server.app;' in final_appuser_block


def test_aio_auth_dependency_supports_the_config_free_router_call():
    assert "token_dep = get_token_dependency()" in WEB_TOOLS
    assert "def get_token_dependency(config: Optional[Dict] = None)" in AUTH


def test_get_mcp_tools_decode_json_once_for_every_http_method():
    assert "def _response_payload" in MCP_BRIDGE
    assert "return _response_payload(r)" in MCP_BRIDGE
    assert 'return r.text if method == "GET" else r.json()' not in MCP_BRIDGE


def test_rest_contract_isolated_from_mcp_bridge():
    for path in (
        "/md", "/html", "/screenshot", "/pdf", "/execute_js", "/crawl", "/ask",
        "/web/search", "/camoufox/status", "/camoufox/read", "/camoufox/capture",
    ):
        assert path in REST_VERIFY
    assert "failures.append" in REST_VERIFY


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
