"""Static contracts for the pinned SearXNG AIO integration."""

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
SUPERVISOR = (ROOT / "deploy/docker/supervisord.conf").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
SMOKE = (ROOT / "tests/docker/smoke-test.sh").read_text(encoding="utf-8")
LOCK = tomllib.loads((ROOT / "aio/runtime/uv.lock").read_text(encoding="utf-8"))
PROVENANCE_LOCK = json.loads(
    (ROOT / "aio/provenance/components.lock.json").read_text(encoding="utf-8")
)


def test_published_source_is_digest_pinned_and_void_venv_is_excluded():
    component = next(item for item in PROVENANCE_LOCK["components"] if item["name"] == "searxng")
    assert f"docker.io/searxng/searxng@{component['platform_digest']}" in DOCKERFILE
    assert "FROM searxng-source AS searxng-sanitized" in DOCKERFILE
    assert "rm -rf /usr/local/searxng/.venv" in DOCKERFILE
    assert "COPY --from=searxng-sanitized" in DOCKERFILE
    assert "COPY --from=searxng-source" not in DOCKERFILE
    assert (
        "python:3.12-slim-bookworm@sha256:"
        "72d3d75f2639ab82b34b29390ad3d6e0827c775befee94edda8e9976818f488d"
    ) in DOCKERFILE


def test_one_locked_python_environment_contains_searxng_server_dependencies():
    packages = {
        package["name"]: package["version"]
        for package in LOCK["package"]
        if "version" in package
    }
    assert packages["granian"] == "2.7.9"
    assert packages["flask"] == "3.1.3"
    assert packages["lxml"] == "6.1.1"
    assert packages["httpx"] == "0.28.1"
    assert "/home/appuser/.venv/bin/granian" in SUPERVISOR
    assert "/usr/local/searxng/.venv/bin" not in SUPERVISOR
    assert "import granian, searx" in DOCKERFILE


def test_searxng_runs_as_appuser_on_lan_port_with_writable_cache():
    block = SUPERVISOR.split("[program:searxng]", 1)[1].split("[program:gunicorn]", 1)[0]
    assert "--host 0.0.0.0 --port 8080" in block
    assert "user=appuser" in block
    assert '"8080:8080"' in COMPOSE
    assert "/var/cache/searxng:uid=999,gid=999,mode=0700" in COMPOSE
    assert "INSTALL_TYPE: ${INSTALL_TYPE:-all}" in COMPOSE
    assert "PRELOAD_MODELS: ${PRELOAD_MODELS:-true}" in COMPOSE
    assert "read_only: false" in COMPOSE


def test_smoke_covers_health_config_real_search_and_duplicate_venv():
    assert "verify_searxng.py" in SMOKE
    verify = (ROOT / "tests/docker/verify_searxng.py").read_text(encoding="utf-8")
    for contract in ("/healthz", "/config", '"format": "json"', '"brave"', '"duckduckgo"'):
        assert contract in verify
    assert 'Path("/usr/local/searxng/.venv")' in verify
    assert "unresponsive_engines" in verify
