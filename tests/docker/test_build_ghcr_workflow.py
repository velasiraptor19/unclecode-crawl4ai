"""Static release-safety contract for the AIO GHCR workflow."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "build-ghcr.yml"
WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")


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
    assert 'imagetools inspect "${tag}" --raw | sha256sum' in WORKFLOW
    assert 'test "${promoted_digest}" = "${CANDIDATE_DIGEST}"' in WORKFLOW


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
