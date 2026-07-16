"""Contracts for collecting candidate verification and digest-only retests."""

import ast
import json
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


def test_workflows_are_valid_yaml():
    assert yaml.safe_load(BUILD_WORKFLOW)["jobs"]
    assert yaml.safe_load(VERIFY_WORKFLOW)["jobs"]


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
    ):
        assert f'run_check "{check}"' in SMOKE
    assert "write_report" in SMOKE
    assert "failure_count > 0" in SMOKE
    assert 'tee "${artifact_dir}/${name}.log"' in SMOKE


def test_build_runtime_checks_are_collecting_too():
    assert 'check("playwright_assets", verify_assets)' in DOCKERFILE
    assert 'check(f"playwright_{name}"' in DOCKERFILE
    assert 'check("patchright_chromium", verify_patchright)' in DOCKERFILE
    assert 'check("camoufox", verify_camoufox)' in DOCKERFILE
    assert 'raise AssertionError("build runtime failures:' in DOCKERFILE


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
