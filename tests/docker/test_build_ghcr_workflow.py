"""Static release-safety contract for the AIO GHCR workflow."""

import re
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "build-ghcr.yml"
WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
RUNTIME_PROJECT = (ROOT / "aio" / "runtime" / "pyproject.toml").read_text(encoding="utf-8")
RUNTIME_LOCK = tomllib.loads(
    (ROOT / "aio" / "runtime" / "uv.lock").read_text(encoding="utf-8")
)
RUNTIME_VERIFY = (ROOT / "tests" / "docker" / "verify_runtime.py").read_text(
    encoding="utf-8"
)


def _position(text: str) -> int:
    position = WORKFLOW.find(text)
    assert position >= 0, f"missing workflow contract: {text}"
    return position


def test_workflow_is_valid_yaml():
    assert yaml.safe_load(WORKFLOW)["jobs"]


def test_current_release_ref_and_variant_fail_closed():
    assert "refs/heads/aio-published-v0.9.2-provenance" in WORKFLOW
    assert '"${INSTALL_TYPE}" != "all"' in WORKFLOW
    assert '"${ENABLE_GPU}" != "false"' in WORKFLOW
    assert "PRELOAD_MODELS=true" in WORKFLOW
    assert "gpu-preload" not in WORKFLOW


def test_offline_provenance_gate_precedes_build_and_is_triggered():
    gate = _position("scripts/aio-provenance-verify")
    build = _position("Build and push non-release candidate")
    assert gate < build
    for path in (
        "aio/provenance/**",
        "scripts/aio-provenance-*",
        "scripts/aio_provenance.py",
        "tests/aio_provenance/**",
    ):
        assert path in WORKFLOW


def test_candidate_is_tested_before_exact_digest_promotion():
    candidate = _position("Build and push non-release candidate")
    tests = _position("Run smoke, runtime, MCP, and browser tests against candidate digest")
    promotion = _position("Promote exact tested digest to final tags")
    assert candidate < tests < promotion
    assert "candidate-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-all-cpu-preload" in WORKFLOW
    assert '"${{ steps.tags.outputs.candidate }}@${{ steps.build.outputs.digest }}"' in WORKFLOW
    assert 'source_ref="${CANDIDATE_IMAGE}@${CANDIDATE_DIGEST}"' in WORKFLOW
    assert (
        'docker buildx imagetools create --prefer-index=false '
        '"${promotion_args[@]}" "${source_ref}"'
    ) in WORKFLOW
    assert 'promoted_digest="$(digest_from_inspection "${tag}" "${inspection}")"' in WORKFLOW
    assert 'test "${promoted_digest}" = "${CANDIDATE_DIGEST}"' in WORKFLOW


def test_release_build_pulls_bases_without_external_cache():
    build_block = WORKFLOW.split("      - name: Build and push non-release candidate", maxsplit=1)[1]
    build_block = build_block.split("      - name: Run smoke", maxsplit=1)[0]
    assert "pull: true" in build_block
    assert "cache-from:" not in build_block
    assert "cache-to:" not in build_block


def test_concurrent_and_stale_runs_cannot_promote_aliases():
    parsed = yaml.safe_load(WORKFLOW)
    assert parsed["concurrency"]["cancel-in-progress"] is True
    assert "${{ github.ref }}" in parsed["concurrency"]["group"]

    promotion = WORKFLOW.split("      - name: Promote exact tested digest", maxsplit=1)[1]
    assert 'git ls-remote --exit-code --refs origin "${GITHUB_REF}"' in promotion
    assert '"${remote_sha}" != "${GITHUB_SHA}"' in promotion
    assert promotion.count("require_current_branch_tip") >= 3  # definition plus two calls
    assert re.search(
        r"require_current_branch_tip\n\s+docker buildx imagetools create",
        promotion,
    ), "branch tip must be re-read immediately before aliases move"


def test_existing_release_and_source_tags_fail_closed_on_digest_collision():
    tags = WORKFLOW.split("      - name: Compute candidate and final tags", maxsplit=1)[1]
    tags = tags.split("      - name: Build and push", maxsplit=1)[0]
    protected = tags.split('echo "protected_tags<<EOF"', maxsplit=1)[1].split(
        'echo "EOF"', maxsplit=1
    )[0]
    protected_lines = {line.strip() for line in protected.splitlines()}
    assert ":v${C4AI_VERSION}-all-cpu-preload" in protected
    assert ":sha-${GITHUB_SHA}-all-cpu-preload" in protected
    for mutable in (
        'echo "${image}:latest"',
        'echo "${image}:all"',
        'echo "${image}:all-cpu-preload"',
    ):
        assert mutable not in protected_lines

    promotion = WORKFLOW.split("      - name: Promote exact tested digest", maxsplit=1)[1]
    collision = _position('"${existing_digest}" != "${CANDIDATE_DIGEST}"')
    create = _position("docker buildx imagetools create")
    assert collision < create
    assert 'done <<< "${PROTECTED_TAGS}"' in promotion
    assert "Refusing to replace protected tag" in promotion
    assert "inspect_status" in promotion
    assert "manifest unknown|no such manifest|404 Not Found" in promotion
    assert "Refusing promotion after unexpected registry error" in promotion


def test_final_tags_are_only_attached_by_promotion():
    build_block, promotion_block = WORKFLOW.split(
        "      - name: Promote exact tested digest to final tags", maxsplit=1
    )
    build_action = build_block.split("      - name: Build and push non-release candidate", maxsplit=1)[1]
    assert "tags: ${{ steps.tags.outputs.candidate }}" in build_action
    assert "final_tags" not in build_action
    assert "imagetools create" in promotion_block


def test_package_write_actions_are_sha_pinned_and_annotated():
    assert "packages: write" in WORKFLOW
    uses = re.findall(r"^\s*uses:\s*([^\s#]+)(?:\s+#\s*(v\S+))?", WORKFLOW, re.MULTILINE)
    assert uses
    for reference, release in uses:
        action, separator, revision = reference.rpartition("@")
        assert action and separator
        assert re.fullmatch(r"[0-9a-f]{40}", revision), reference
        assert re.fullmatch(r"v\d+(?:\.\d+){0,2}", release), reference


def test_locked_evidence_is_added_to_labels_and_summary():
    assert "AIO_PROVENANCE_INDEX_DIGEST=${{ steps.provenance.outputs.index_digest }}" in WORKFLOW
    assert "AIO_PROVENANCE_RELEASE_COMMIT=${{ steps.provenance.outputs.release_commit }}" in WORKFLOW
    assert "Locked upstream index" in WORKFLOW
    assert "Locked release commit" in WORKFLOW


def test_aio_runtime_is_installed_from_cpu_only_frozen_lock():
    assert "aio/runtime/**" in WORKFLOW
    assert "uv sync --project /tmp/project/aio/runtime --frozen" in DOCKERFILE
    assert "pip install --no-cache-dir -r" not in DOCKERFILE
    assert 'pip install --no-cache-dir "/tmp/project' not in DOCKERFILE
    assert 'url = "https://download.pytorch.org/whl/cpu"' in RUNTIME_PROJECT
    for dependency in (
        '"torch==2.13.0+cpu"',
        '"torchvision==0.28.0+cpu"',
        '"torchaudio==2.11.0+cpu"',
    ):
        assert dependency in RUNTIME_PROJECT
    locked_names = {package["name"] for package in RUNTIME_LOCK["package"]}
    assert {"torch", "torchvision", "torchaudio"} <= locked_names
    assert not any(
        name == "triton" or name.startswith("nvidia-") or "cuda" in name
        for name in locked_names
    )


def test_runtime_smoke_compares_installed_distributions_to_shipped_lock():
    assert "aio/runtime/uv.lock /opt/crawl4ai/aio-runtime.uv.lock" in DOCKERFILE
    assert "verify_locked_environment()" in RUNTIME_VERIFY
    assert "installed distributions absent from runtime lock" in RUNTIME_VERIFY
    assert "installed versions differ from runtime lock" in RUNTIME_VERIFY
    assert "locked direct runtime dependencies missing" in RUNTIME_VERIFY


def test_cleanup_removes_uv_and_caches_but_retains_os_toolkit():
    assert "python -m pip uninstall -y uv" in DOCKERFILE
    assert "rm -rf /tmp/* /var/tmp/*" in DOCKERFILE
    assert "apt-get purge" not in DOCKERFILE
    for package in (
        "build-essential",
        "wget",
        "git",
        "cmake",
        "pkg-config",
        "python3-dev",
        "libjpeg-dev",
        "gnupg",
    ):
        assert package in DOCKERFILE
