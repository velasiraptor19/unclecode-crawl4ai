#!/usr/bin/env python3
"""Resolve and verify immutable AIO component provenance."""

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
VERSION_RELEASE_TAG = re.compile(r"^v?\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?$")
OCI_LABELS = {
    "version": "org.opencontainers.image.version",
    "revision": "org.opencontainers.image.revision",
    "source": "org.opencontainers.image.source",
}
PLATFORM = {"os": "linux", "architecture": "amd64"}
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
ATTESTATION_TYPE = "attestation-manifest"
SCHEMA_VERSION = 2


class ProvenanceError(ValueError):
    pass


def is_sha256(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def is_commit(value):
    return isinstance(value, str) and COMMIT.fullmatch(value) is not None


def is_version_release_tag(value):
    return isinstance(value, str) and VERSION_RELEASE_TAG.fullmatch(value) is not None


def load_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def run_json(command):
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"command returned invalid JSON: {' '.join(command)}") from exc


def inspect_image(reference):
    return run_json([
        "docker", "buildx", "imagetools", "inspect", reference,
        "--format", "{{json .}}",
    ])


def inspect_raw_manifest(reference):
    return subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", reference, "--raw"],
        check=True, capture_output=True,
    ).stdout


def digest_bytes(value):
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def parse_index(raw):
    if not isinstance(raw, bytes) or not raw:
        raise ProvenanceError("registry inspection omitted exact index bytes")
    try:
        index = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError("registry index bytes are not valid UTF-8 JSON") from exc
    require_dict(index, "registry index must be an object")
    if (index.get("schemaVersion") != 2 or index.get("mediaType") not in INDEX_MEDIA_TYPES
            or not isinstance(index.get("manifests"), list)):
        raise ProvenanceError("latest did not resolve to a valid manifest list/index")
    return index


def select_platform_manifest(index):
    manifests = index["manifests"]
    ordinary_digests = set()
    attestations = []
    matches = []
    for descriptor in manifests:
        require_dict(descriptor, "manifest list contains malformed entries")
        digest = descriptor.get("digest", "")
        size = descriptor.get("size")
        if (descriptor.get("mediaType") not in MANIFEST_MEDIA_TYPES
                or not is_sha256(digest)
                or isinstance(size, bool) or not isinstance(size, int) or size < 0):
            raise ProvenanceError("manifest list contains malformed descriptors")
        annotations = descriptor.get("annotations", {})
        if not isinstance(annotations, dict):
            raise ProvenanceError("manifest descriptor annotations must be an object")
        if annotations.get("vnd.docker.reference.type") == ATTESTATION_TYPE:
            reference = annotations.get("vnd.docker.reference.digest", "")
            if descriptor.get("platform") != {"os": "unknown", "architecture": "unknown"} or not is_sha256(reference):
                raise ProvenanceError("manifest list contains malformed attestation descriptor")
            attestations.append(reference)
            continue
        ordinary_digests.add(digest)
        platform = descriptor.get("platform")
        if isinstance(platform, dict) and all(platform.get(key) == value for key, value in PLATFORM.items()):
            matches.append(descriptor)
    if any(reference not in ordinary_digests for reference in attestations):
        raise ProvenanceError("attestation descriptor references an unrelated manifest")
    if len(matches) != 1:
        raise ProvenanceError("expected exactly one valid linux/amd64 manifest")
    return matches[0]


def peel_tag(repository, tag):
    try:
        obj = require_dict(run_json(["gh", "api", f"repos/{repository}/git/ref/tags/{tag}"]).get("object"), "tag omitted object")
        for _ in range(8):
            if obj.get("type") == "commit" and is_commit(obj.get("sha")):
                return obj["sha"]
            if obj.get("type") != "tag" or not is_commit(obj.get("sha")):
                break
            obj = require_dict(run_json(["gh", "api", f"repos/{repository}/git/tags/{obj['sha']}"]).get("object"), "annotated tag omitted object")
    except (KeyError, subprocess.CalledProcessError) as exc:
        raise ProvenanceError(f"tag {tag} is missing or unverifiable") from exc
    raise ProvenanceError(f"tag {tag} could not be peeled to a commit")


def resolve_release_evidence(repository, tag, published_commit):
    if not is_version_release_tag(tag):
        raise ProvenanceError("release identity must be an exact version tag, not a branch or floating alias")
    try:
        latest = run_json(["gh", "api", f"repos/{repository}/releases/latest"])
        if latest.get("tag_name") != tag:
            raise ProvenanceError(f"{tag} is not the official latest release")
        release = run_json(["gh", "api", f"repos/{repository}/releases/tags/{tag}"])
        release_commit = peel_tag(repository, tag)
        commit = run_json(["gh", "api", f"repos/{repository}/commits/{published_commit}"])
    except subprocess.CalledProcessError as exc:
        raise ProvenanceError(f"official release {tag} is missing or unverifiable") from exc
    if release.get("tag_name") != tag:
        raise ProvenanceError(f"{tag} is not the official latest release")
    if commit.get("sha") != published_commit:
        raise ProvenanceError("published source commit is unverifiable")
    return {"method": "github-release", "repository": repository, "release_tag": tag, "release_commit": release_commit,
            "published_source_commit": published_commit,
            "is_rebuild": published_commit != release_commit}


def resolve_commit_evidence(repository, published_commit):
    if not is_commit(published_commit):
        raise ProvenanceError("published source revision must be an exact commit")
    try:
        commit = run_json(["gh", "api", f"repos/{repository}/commits/{published_commit}"])
    except subprocess.CalledProcessError as exc:
        raise ProvenanceError("published source commit is missing or unverifiable") from exc
    if commit.get("sha") != published_commit:
        raise ProvenanceError("published source commit is unverifiable")
    return {"method": "github-commit", "repository": repository,
            "published_source_commit": published_commit}


def require_dict(value, message):
    if not isinstance(value, dict):
        raise ProvenanceError(message)
    return value


def exact_keys(value, keys, message):
    require_dict(value, message)
    if set(value) != set(keys):
        raise ProvenanceError(f"{message}; unexpected or missing fields")


def normalized_url(value):
    return value.removesuffix(".git").rstrip("/") if isinstance(value, str) else ""


def validate_spec(spec):
    exact_keys(spec, ("schema_version", "lock_state", "components"), "malformed spec")
    if spec["schema_version"] != SCHEMA_VERSION or spec["lock_state"] not in {"bootstrap", "ready"} or not isinstance(spec["components"], list):
        raise ProvenanceError(f"spec requires schema_version {SCHEMA_VERSION}, bootstrap/ready lock_state, and components array")
    names = set()
    for component in spec["components"]:
        exact_keys(component, ("name", "image", "platform", "source"), "malformed component")
        name, image = component.get("name"), component.get("image")
        if not isinstance(name, str) or not name:
            raise ProvenanceError("component names must be non-empty")
        if name in names:
            raise ProvenanceError(f"duplicate spec component: {name}")
        names.add(name)
        if not isinstance(image, str) or not image.endswith(":latest"):
            raise ProvenanceError(f"{name}: image must be a published :latest reference")
        platform = require_dict(component.get("platform"), f"{name}: platform is required")
        if platform != PLATFORM:
            raise ProvenanceError(f"{name}: Phase 0 requires linux/amd64")
        source = require_dict(component.get("source"), f"{name}: source is required")
        exact_keys(source, ("repository", "url", "verification"), f"{name}: malformed source")
        for field in ("repository", "url"):
            if not isinstance(source.get(field), str) or not source[field]:
                raise ProvenanceError(f"{name}: source.{field} is required")
        if normalized_url(source["url"]) != f"https://github.com/{source['repository']}":
            raise ProvenanceError(f"{name}: source URL mismatch with repository")
        verification = require_dict(source["verification"], f"{name}: source verification is required")
        method = verification.get("method")
        if method == "github-commit":
            exact_keys(verification, ("method",), f"{name}: malformed commit verification")
            continue
        if method != "github-release":
            raise ProvenanceError(f"{name}: unknown source verification method")
        exact_keys(verification, ("method", "release_tag_from_oci_version", "reviewed_fallback"),
                   f"{name}: malformed release verification")
        if not isinstance(verification["release_tag_from_oci_version"], str) or not verification["release_tag_from_oci_version"]:
            raise ProvenanceError(f"{name}: release tag mapping is required")
        fallback = verification["reviewed_fallback"]
        exact_keys(fallback, ("version", "release_tag", "reviewed_index_digest", "reviewed_platform_digest",
                              "release_commit", "published_source_commit", "review_reason"), f"{name}: malformed fallback")
        if (not isinstance(fallback["version"], str) or not fallback["version"]
                or not isinstance(fallback["release_tag"], str) or not fallback["release_tag"]
                or not is_version_release_tag(fallback["release_tag"])
                or not is_sha256(fallback["reviewed_index_digest"])
                or not is_sha256(fallback["reviewed_platform_digest"])
                or not is_commit(fallback["release_commit"])
                or not is_commit(fallback["published_source_commit"])):
            raise ProvenanceError(f"{name}: invalid reviewed fallback")
        if fallback["release_tag"] != verification["release_tag_from_oci_version"].format(version=fallback["version"]):
            raise ProvenanceError(f"{name}: inconsistent fallback release mapping")
        if not isinstance(fallback["review_reason"], str) or not fallback["review_reason"]:
            raise ProvenanceError(f"{name}: fallback requires review_reason")


def resolve_component(component, inspector=inspect_image, release_evidence_resolver=resolve_release_evidence,
                      raw_reader=inspect_raw_manifest, commit_evidence_resolver=resolve_commit_evidence):
    raw_index = raw_reader(component["image"])
    index = parse_index(raw_index)
    index_digest = digest_bytes(raw_index)
    platform_digest = select_platform_manifest(index)["digest"]
    repository = component["image"].removesuffix(":latest")
    platform = inspector(f"{repository}@{platform_digest}")
    inspected_manifest = require_dict(platform.get("manifest"), "platform inspection omitted manifest")
    if inspected_manifest.get("digest") != platform_digest:
        raise ProvenanceError("platform inspection returned an unrelated manifest")
    image_data = require_dict(platform.get("image"), "platform image omitted image config")
    if image_data.get("os") != "linux" or image_data.get("architecture") != "amd64":
        raise ProvenanceError("platform image config does not match linux/amd64")
    labels = require_dict(require_dict(image_data.get("config"), "platform image omitted config").get("Labels") or {}, "labels must be an object")
    oci = {field: labels.get(label) if label in labels else None for field, label in OCI_LABELS.items()}
    for field, value in oci.items():
        if value is not None and (not isinstance(value, str) or not value):
            raise ProvenanceError(f"invalid present OCI {field} label")
    missing = [OCI_LABELS[field] for field, value in oci.items() if value is None]
    source = component["source"]
    verification = source["verification"]
    fallback = verification.get("reviewed_fallback")
    if oci["source"] is not None and normalized_url(oci["source"]) != normalized_url(source["url"]):
        raise ProvenanceError("invalid OCI revision/source evidence")
    if oci["revision"] is not None and not is_commit(oci["revision"]):
        raise ProvenanceError("invalid OCI revision/source evidence")
    if not missing:
        version, published_commit, method = oci["version"], oci["revision"], "oci-labels"
    else:
        if verification["method"] != "github-release":
            raise ProvenanceError("commit verification requires complete OCI provenance labels")
        expected_partial = {
            "version": fallback["version"],
            "revision": fallback["published_source_commit"],
            "source": source["url"],
        }
        for field, value in oci.items():
            expected_value = expected_partial[field]
            agrees = normalized_url(value) == normalized_url(expected_value) if field == "source" else value == expected_value
            if value is not None and not agrees:
                raise ProvenanceError("partial OCI provenance conflicts with reviewed fallback")
        if index_digest != fallback["reviewed_index_digest"] or platform_digest != fallback["reviewed_platform_digest"]:
            raise ProvenanceError("published latest differs from reviewed fallback digests")
        version, tag, published_commit, method = fallback["version"], fallback["release_tag"], fallback["published_source_commit"], "reviewed-release-fallback"
    if verification["method"] == "github-release":
        tag = verification["release_tag_from_oci_version"].format(version=version)
        source_evidence = release_evidence_resolver(source["repository"], tag, published_commit)
    else:
        source_evidence = commit_evidence_resolver(source["repository"], published_commit)
    if method == "reviewed-release-fallback" and (
            source_evidence.get("release_commit") != fallback["release_commit"]
            or source_evidence.get("published_source_commit") != fallback["published_source_commit"]):
        raise ProvenanceError("release evidence differs from reviewed fallback commits")
    return {
        "name": component["name"], "requested_image": component["image"],
        "resolved_image": f"{repository}@{index_digest}",
        "index_digest": index_digest, "platform": component["platform"],
        "platform_digest": platform_digest,
        "index_manifest_base64": base64.b64encode(raw_index).decode("ascii"),
        "evidence": {"method": method, "version": version, "oci": oci,
                     "missing_oci_labels": missing, "source": source_evidence},
    }


def verify(spec, lock, require_ready=True):
    validate_spec(spec)
    exact_keys(lock, ("schema_version", "status", "components"), "malformed lock")
    if lock["schema_version"] != SCHEMA_VERSION or lock["status"] not in {"bootstrap", "ready"} or not isinstance(lock["components"], list):
        raise ProvenanceError(f"lock requires schema_version {SCHEMA_VERSION}, bootstrap/ready status, and components array")
    if lock["status"] != spec["lock_state"]:
        raise ProvenanceError("spec and lock state disagree")
    if require_ready and lock["status"] != "ready":
        raise ProvenanceError("bootstrap provenance is explicitly non-buildable")
    expected = {item["name"]: item for item in spec["components"]}
    actual = {}
    for item in lock["components"]:
        require_dict(item, "malformed lock component")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ProvenanceError("malformed lock component name")
        if name in actual:
            raise ProvenanceError(f"duplicate lock component: {name}")
        actual[name] = item
    if lock["status"] == "bootstrap":
        if actual:
            raise ProvenanceError("bootstrap lock must not contain components")
        return
    if set(actual) != set(expected):
        raise ProvenanceError("ready lock components must exactly match spec")
    for name, item in actual.items():
        exact_keys(item, ("name", "requested_image", "resolved_image", "index_digest", "platform", "platform_digest",
                          "index_manifest_base64", "evidence"), f"{name}: malformed lock component")
        component = expected[name]
        repository = component["image"].removesuffix(":latest")
        if item.get("requested_image") != component["image"]:
            raise ProvenanceError(f"{name}: requested image differs from spec")
        for field in ("index_digest", "platform_digest"):
            if not is_sha256(item.get(field)):
                raise ProvenanceError(f"{name}: invalid {field}")
        try:
            raw_index = base64.b64decode(item["index_manifest_base64"], validate=True)
        except (TypeError, ValueError, binascii.Error) as exc:
            raise ProvenanceError(f"{name}: malformed index manifest evidence") from exc
        index = parse_index(raw_index)
        computed_index_digest = digest_bytes(raw_index)
        if item["index_digest"] != computed_index_digest:
            raise ProvenanceError(f"{name}: index digest does not match manifest evidence")
        selected = select_platform_manifest(index)
        if item["platform_digest"] != selected["digest"]:
            raise ProvenanceError(f"{name}: platform digest is not a member of reviewed index")
        if item.get("resolved_image") != f"{repository}@{item['index_digest']}":
            raise ProvenanceError(f"{name}: resolved image is not index-digest pinned")
        if item.get("platform") != component["platform"]:
            raise ProvenanceError(f"{name}: platform differs from spec")
        evidence = require_dict(item["evidence"], f"{name}: evidence missing")
        exact_keys(evidence, ("method", "version", "oci", "missing_oci_labels", "source"), f"{name}: malformed evidence")
        oci = require_dict(evidence["oci"], "malformed OCI evidence")
        source_evidence = require_dict(evidence["source"], "malformed source evidence")
        exact_keys(oci, OCI_LABELS.keys(), "malformed OCI evidence")
        verification = component["source"]["verification"]
        if verification["method"] == "github-release":
            exact_keys(source_evidence, ("method", "repository", "release_tag", "release_commit",
                                        "published_source_commit", "is_rebuild"), "malformed release evidence")
            if source_evidence["method"] != "github-release":
                raise ProvenanceError(f"{name}: source verification method differs from spec")
            tag = verification["release_tag_from_oci_version"].format(version=evidence["version"])
            if not is_version_release_tag(tag) or source_evidence["release_tag"] != tag:
                raise ProvenanceError(f"{name}: invalid release tag")
            if not is_commit(source_evidence["release_commit"]) or not is_commit(source_evidence["published_source_commit"]):
                raise ProvenanceError(f"{name}: malformed source commit")
            if source_evidence["is_rebuild"] is not (source_evidence["published_source_commit"] != source_evidence["release_commit"]):
                raise ProvenanceError(f"{name}: inconsistent rebuild flag")
        else:
            exact_keys(source_evidence, ("method", "repository", "published_source_commit"),
                       "malformed commit evidence")
            if source_evidence["method"] != "github-commit" or not is_commit(source_evidence["published_source_commit"]):
                raise ProvenanceError(f"{name}: malformed commit evidence")
        if source_evidence["repository"] != component["source"]["repository"]:
            raise ProvenanceError(f"{name}: source repository differs from spec")
        for field, value in oci.items():
            if value is not None and (not isinstance(value, str) or not value):
                raise ProvenanceError(f"{name}: invalid present OCI {field} label")
        missing = [label for field, label in OCI_LABELS.items() if oci[field] is None]
        if evidence["missing_oci_labels"] != missing:
            raise ProvenanceError(f"{name}: inconsistent missing OCI labels")
        if evidence["method"] == "oci-labels":
            if missing or normalized_url(oci["source"]) != normalized_url(component["source"]["url"]):
                raise ProvenanceError(f"{name}: OCI source mismatch")
            if oci["version"] != evidence["version"] or oci["revision"] != source_evidence["published_source_commit"]:
                raise ProvenanceError(f"{name}: inconsistent OCI evidence")
        elif evidence["method"] == "reviewed-release-fallback":
            if verification["method"] != "github-release":
                raise ProvenanceError(f"{name}: commit verification cannot use fallback evidence")
            fallback = verification["reviewed_fallback"]
            expected_partial = {"version": fallback["version"], "revision": fallback["published_source_commit"],
                                "source": component["source"]["url"]}
            partial_conflict = any(value is not None and (
                normalized_url(value) != normalized_url(expected_partial[field]) if field == "source"
                else value != expected_partial[field]) for field, value in oci.items())
            if (not missing or partial_conflict or evidence["version"] != fallback["version"]
                    or item["index_digest"] != fallback["reviewed_index_digest"]
                    or item["platform_digest"] != fallback["reviewed_platform_digest"]
                    or source_evidence["release_tag"] != fallback["release_tag"]
                    or source_evidence["release_commit"] != fallback["release_commit"]
                    or source_evidence["published_source_commit"] != fallback["published_source_commit"]):
                raise ProvenanceError(f"{name}: fallback differs from reviewed spec")
        else:
            raise ProvenanceError(f"{name}: unknown evidence method")


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-spec")
    resolve = sub.add_parser("resolve")
    verify_parser = sub.add_parser("verify")
    bootstrap_parser = sub.add_parser("verify-bootstrap")
    for command in (validate, resolve, verify_parser, bootstrap_parser):
        command.add_argument("--spec", required=True)
    resolve.add_argument("--output", required=True)
    verify_parser.add_argument("--lock", required=True)
    bootstrap_parser.add_argument("--lock", required=True)
    args = parser.parse_args(argv)
    try:
        spec = load_json(args.spec)
        validate_spec(spec)
        if args.command == "validate-spec":
            pass
        elif args.command == "resolve":
            lock = {"schema_version": SCHEMA_VERSION, "status": "ready", "components": [resolve_component(c) for c in spec["components"]]}
            verify(spec, lock)
            Path(args.output).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            verify(spec, load_json(args.lock), require_ready=args.command == "verify")
    except (OSError, KeyError, subprocess.CalledProcessError, ProvenanceError, json.JSONDecodeError) as exc:
        print(f"provenance error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
