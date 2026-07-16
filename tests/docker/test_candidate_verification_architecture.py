"""Contracts for collecting candidate verification and digest-only retests."""

import ast
import json
import runpy
from types import SimpleNamespace
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
BUILD_WORKFLOW = (ROOT / ".github/workflows/build-ghcr.yml").read_text(encoding="utf-8")
VERIFY_WORKFLOW = (ROOT / ".github/workflows/verify-ghcr-candidate.yml").read_text(
    encoding="utf-8"
)
SMOKE = (ROOT / "tests/docker/smoke-test.sh").read_text(encoding="utf-8")
MCP_TEST = (ROOT / "tests/mcp/test_mcp_http.py").read_text(encoding="utf-8")
MCP_BRIDGE = (ROOT / "deploy/docker/mcp_bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
JOB = (ROOT / "deploy/docker/job.py").read_text(encoding="utf-8")
SERVER = (ROOT / "deploy/docker/server.py").read_text(encoding="utf-8")
ENTRYPOINT = (ROOT / "deploy/docker/entrypoint.sh").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_workflows_are_valid_yaml():
    assert yaml.safe_load(BUILD_WORKFLOW)["jobs"]
    assert yaml.safe_load(VERIFY_WORKFLOW)["jobs"]


def test_buildkit_and_node_actions_use_the_minimum_required_privilege():
    assert "buildkitd-flags: --oci-worker-gc" in BUILD_WORKFLOW
    assert "--allow-insecure-entitlement" not in BUILD_WORKFLOW
    assert "docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a" in BUILD_WORKFLOW
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in BUILD_WORKFLOW
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in VERIFY_WORKFLOW


def test_smoke_collects_independent_checks_before_failing():
    assert "set -uo pipefail" in SMOKE
    assert "set -euo pipefail" not in SMOKE
    assert 'run_check "container_health"' in SMOKE
    for check in (
        "pip_check",
        "ownership_contract",
        "runtime_contract",
        "searxng_contract",
        "aio_rest_contract",
        "mcp_auth_gate",
        "novnc_contract",
        "mcp_http_contract",
        "runtime_log_contract",
    ):
        assert f'run_check "{check}"' in SMOKE
    assert "write_report" in SMOKE
    assert "failure_count > 0" in SMOKE
    assert 'tee "${artifact_dir}/${name}.log"' in SMOKE
    assert "LeakWarning: When using a proxy" in SMOKE


def test_build_runtime_checks_are_collecting_too():
    assert 'check("playwright_assets", verify_assets)' in DOCKERFILE
    assert 'check(f"playwright_{name}"' in DOCKERFILE
    assert 'check("patchright_chromium", verify_patchright)' in DOCKERFILE
    assert 'check("camoufox", verify_camoufox)' in DOCKERFILE
    assert 'raise AssertionError("build runtime failures:' in DOCKERFILE


def test_browser_contract_rejects_duplicate_playwright_revisions():
    assert 'default_browser_manifest("playwright")' in DOCKERFILE
    assert 'default_browser_manifest("patchright")' in DOCKERFILE
    assert "patchright_manifest == playwright_manifest" in DOCKERFILE
    assert "browser.get(\"installByDefault\")" in DOCKERFILE
    assert "installed == expected" in DOCKERFILE
    assert "chromium-1228" not in DOCKERFILE


def test_aio_packaging_revision_preserves_immutable_release_tags():
    assert "AIO_IMAGE_REVISION: 3" in BUILD_WORKFLOW
    assert "ARG AIO_IMAGE_REVISION=1" in DOCKERFILE
    assert "io.crawl4ai.aio.image-revision=$AIO_IMAGE_REVISION" in DOCKERFILE
    assert ":v${C4AI_VERSION}-r${AIO_IMAGE_REVISION}-aio-web-all-cpu-preload" in BUILD_WORKFLOW
    assert ":v${C4AI_VERSION}-aio-web-all-cpu-preload" not in BUILD_WORKFLOW


def test_server_import_is_free_of_framework_deprecation_warnings():
    assert "regex=" not in SERVER
    assert 'pattern="^(code|doc|all)$"' in SERVER
    assert "schema_: Optional[str] = Field(default=None, alias=\"schema\")" in JOB
    assert "payload.schema_" in JOB
    assert 'if [[ -z "${SECRET_KEY:-}" ]]' in ENTRYPOINT
    assert "export SECRET_KEY" in ENTRYPOINT
    assert "No SECRET_KEY set" in SMOKE


def test_non_root_xvfb_has_a_root_owned_socket_directory():
    assert "install -d -o root -g root -m 1777 /tmp/.X11-unix" in DOCKERFILE
    assert "/tmp/.X11-unix:uid=0,gid=0,mode=1777" in COMPOSE


def test_build_archiver_uses_the_collected_report_and_real_warning_lines(tmp_path):
    write_summary = runpy.run_path(ROOT / "tools/archive_gh_build.py")["write_summary"]
    run = {
        "databaseId": 1,
        "conclusion": "failure",
        "status": "completed",
        "displayTitle": "test",
        "headBranch": "test",
        "headSha": "0" * 40,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:01:00Z",
        "url": "https://example.invalid/run/1",
        "jobs": [{
            "startedAt": "2026-01-01T00:00:00Z",
            "completedAt": "2026-01-01T00:01:00Z",
            "steps": [{"name": "Run smoke tests", "conclusion": "success"}],
        }],
    }
    lines = [
        "python -m nltk.downloader punkt",
        "- Checks: 12",
        "- Failures: 1",
        "| `image_pull` | PASS | 0 |",
        "| `aio_rest_contract` | FAIL | 1 |",
        *[f"| `check_{index}` | PASS | 0 |" for index in range(10)],
    ]
    destination = tmp_path / "summary.md"
    write_summary(run, lines, destination)
    summary = destination.read_text(encoding="utf-8")
    assert "11 passed, 1 failed" in summary
    assert "Model preload `runpy` warnings" not in summary


def test_main_workflow_collects_evidence_then_gates_promotion():
    smoke = BUILD_WORKFLOW.index("Run smoke, runtime, MCP, and browser tests")
    summary = BUILD_WORKFLOW.index("Publish complete candidate verification summary")
    upload = BUILD_WORKFLOW.index("Upload complete candidate verification evidence")
    gate = BUILD_WORKFLOW.index("Require complete candidate verification")
    promotion = BUILD_WORKFLOW.index("Promote exact tested digest")
    assert smoke < summary < upload < gate < promotion
    smoke_block = BUILD_WORKFLOW[smoke:summary]
    assert "continue-on-error: true" in smoke_block
    assert 'test "${{ steps.smoke.outcome }}" = "success"' in BUILD_WORKFLOW[gate:promotion]


def test_existing_candidate_can_be_retested_without_a_build_step():
    assert "workflow_dispatch" in VERIFY_WORKFLOW
    assert "@sha256:[0-9a-f]{64}" in VERIFY_WORKFLOW
    assert "tests/docker/smoke-test.sh" in VERIFY_WORKFLOW
    assert "docker/build-push-action" not in VERIFY_WORKFLOW
    assert "imagetools create" not in VERIFY_WORKFLOW


def test_mcp_json_contract_is_method_independent_and_collecting():
    assert "def _response_payload" in MCP_BRIDGE
    assert "content_type.endswith(\"+json\")" in MCP_BRIDGE
    assert 'return r.text if method == "GET" else r.json()' not in MCP_BRIDGE
    assert "failures.append" in MCP_TEST
    assert "for name, operation in cases" in MCP_TEST
    for tool in (
        "md",
        "html",
        "screenshot",
        "pdf",
        "execute_js",
        "crawl",
        "ask",
        "web_search",
        "camoufox_status",
        "camoufox_read",
        "camoufox_capture",
    ):
        assert f'"{tool}"' in MCP_TEST


def test_mcp_response_payload_decodes_json_once_and_preserves_text():
    tree = ast.parse(MCP_BRIDGE)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_response_payload"
    )
    namespace = {"Any": object, "httpx": SimpleNamespace(Response=object)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "mcp_bridge.py", "exec"), namespace)
    decode = namespace["_response_payload"]

    class Response:
        def __init__(self, body, content_type):
            self.text = body
            self.headers = {"content-type": content_type}

        def json(self):
            return json.loads(self.text)

    assert decode(Response('{"package_version":"0.6.0"}', "application/json; charset=utf-8")) == {
        "package_version": "0.6.0"
    }
    assert decode(Response("plain markdown", "text/plain")) == "plain markdown"
