import base64
import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("provenance", ROOT / "scripts/aio_provenance.py")
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
FIX = Path(__file__).parent / "fixtures"


class Tests(unittest.TestCase):
    def raw_index(self):
        return (FIX / "imagetools-index.json").read_bytes()

    def component(self):
        return {
            "name": "tool",
            "image": "registry.example/tool:latest",
            "platform": p.PLATFORM,
            "source": {
                "repository": "example/tool",
                "url": "https://github.com/example/tool",
                "release_tag_from_oci_version": "v{version}",
                "reviewed_fallback": {
                    "version": "1.2.3",
                    "release_tag": "v1.2.3",
                    "reviewed_index_digest": p.digest_bytes(self.raw_index()),
                    "reviewed_platform_digest": "sha256:" + "b" * 64,
                    "release_commit": "e" * 40,
                    "published_source_commit": "d" * 40,
                    "review_reason": "Reviewed because labels are absent.",
                },
            },
        }

    def spec(self, state="ready"):
        return {"schema_version": 1, "lock_state": state, "components": [self.component()]}

    def inspect(self, _reference):
        return json.loads((FIX / "imagetools-platform.json").read_text())

    def evidence(self, repository, tag, commit):
        return {
            "repository": repository,
            "release_tag": tag,
            "release_commit": "e" * 40,
            "published_source_commit": commit,
            "is_rebuild": commit != "e" * 40,
        }

    def item(self, component=None, inspector=None, raw=None, evidence=None):
        return p.resolve_component(
            component or self.component(),
            inspector or self.inspect,
            evidence or self.evidence,
            lambda _reference: raw if raw is not None else self.raw_index(),
        )

    def fallback_inspector(self, labels=None):
        def inspect(reference):
            data = self.inspect(reference)
            data["image"]["config"]["Labels"] = labels or {}
            return data
        return inspect

    def ready_lock(self, fallback=False):
        inspector = self.fallback_inspector() if fallback else self.inspect
        return {"schema_version": 1, "status": "ready", "components": [self.item(inspector=inspector)]}

    def test_oci_path_and_valid_attestations_select_single_platform(self):
        item = self.item()
        self.assertEqual(item["evidence"]["method"], "oci-labels")
        self.assertEqual(p.digest_bytes(base64.b64decode(item["index_manifest_base64"])), item["index_digest"])
        p.verify(self.spec(), self.ready_lock())

    def test_fallback_records_missing_labels_and_rebuild(self):
        item = self.item(inspector=self.fallback_inspector())
        self.assertEqual(item["evidence"]["method"], "reviewed-release-fallback")
        self.assertEqual(len(item["evidence"]["missing_oci_labels"]), 3)
        self.assertTrue(item["evidence"]["release"]["is_rebuild"])
        p.verify(self.spec(), {"schema_version": 1, "status": "ready", "components": [item]})

    def test_stale_or_substituted_latest_rejected_by_fallback(self):
        component = self.component()
        component["source"]["reviewed_fallback"]["reviewed_index_digest"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(p.ProvenanceError, "differs from reviewed fallback digests"):
            self.item(component=component, inspector=self.fallback_inspector())

        changed_raw = self.raw_index() + b" "
        with self.assertRaisesRegex(p.ProvenanceError, "differs from reviewed fallback digests"):
            self.item(inspector=self.fallback_inspector(), raw=changed_raw)

        lock = self.ready_lock(fallback=True)
        spec = self.spec()
        spec["components"][0]["source"]["reviewed_fallback"]["reviewed_index_digest"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(p.ProvenanceError, "fallback differs"):
            p.verify(spec, lock)

    def test_partial_labels_must_be_valid_and_non_conflicting(self):
        matching = {"org.opencontainers.image.version": "1.2.3"}
        item = self.item(inspector=self.fallback_inspector(matching))
        self.assertEqual(item["evidence"]["method"], "reviewed-release-fallback")

        conflicts = (
            {"org.opencontainers.image.version": "9.9.9"},
            {"org.opencontainers.image.revision": "c" * 40},
            {"org.opencontainers.image.source": "https://github.com/other/tool"},
        )
        for labels in conflicts:
            with self.subTest(labels=labels), self.assertRaises(p.ProvenanceError):
                self.item(inspector=self.fallback_inspector(labels))
        with self.assertRaisesRegex(p.ProvenanceError, "invalid present OCI revision"):
            self.item(inspector=self.fallback_inspector({"org.opencontainers.image.revision": ""}))

        lock = self.ready_lock(fallback=True)
        evidence = lock["components"][0]["evidence"]
        evidence["oci"]["version"] = "9.9.9"
        evidence["missing_oci_labels"] = [p.OCI_LABELS["revision"], p.OCI_LABELS["source"]]
        with self.assertRaisesRegex(p.ProvenanceError, "fallback differs"):
            p.verify(self.spec(), lock)

    def test_offline_rejects_unrelated_digest_and_tampered_manifest_evidence(self):
        lock = self.ready_lock()
        lock["components"][0]["platform_digest"] = "sha256:" + "c" * 64
        with self.assertRaisesRegex(p.ProvenanceError, "not a member"):
            p.verify(self.spec(), lock)

        lock = self.ready_lock()
        raw = base64.b64decode(lock["components"][0]["index_manifest_base64"])
        lock["components"][0]["index_manifest_base64"] = base64.b64encode(raw + b" ").decode()
        with self.assertRaisesRegex(p.ProvenanceError, "does not match manifest evidence"):
            p.verify(self.spec(), lock)

    def test_forged_release_and_rebuild_commits_rejected_offline_and_online(self):
        lock = self.ready_lock(fallback=True)
        release = lock["components"][0]["evidence"]["release"]
        release["release_commit"] = "c" * 40
        release["is_rebuild"] = True
        with self.assertRaisesRegex(p.ProvenanceError, "fallback differs"):
            p.verify(self.spec(), lock)

        lock = self.ready_lock(fallback=True)
        release = lock["components"][0]["evidence"]["release"]
        release["published_source_commit"] = "c" * 40
        release["is_rebuild"] = True
        with self.assertRaisesRegex(p.ProvenanceError, "fallback differs"):
            p.verify(self.spec(), lock)

        def forged(repository, tag, commit):
            evidence = self.evidence(repository, tag, commit)
            evidence["release_commit"] = "c" * 40
            return evidence
        with self.assertRaisesRegex(p.ProvenanceError, "reviewed fallback commits"):
            self.item(inspector=self.fallback_inspector(), evidence=forged)

    def test_source_url_mismatch_rejected_online_and_offline(self):
        component = self.component()
        component["source"]["url"] = "https://github.com/other/tool"
        with self.assertRaisesRegex(p.ProvenanceError, "revision/source"):
            self.item(component=component)
        lock = self.ready_lock()
        lock["components"][0]["evidence"]["oci"]["source"] = "https://github.com/other/tool"
        with self.assertRaisesRegex(p.ProvenanceError, "source mismatch"):
            p.verify(self.spec(), lock)

    def test_branch_and_floating_release_identities_rejected(self):
        for tag in ("main", "master", "latest", "stable", "vlatest", "refs/heads/main"):
            spec = self.spec()
            fallback = spec["components"][0]["source"]["reviewed_fallback"]
            fallback["release_tag"] = tag
            spec["components"][0]["source"]["release_tag_from_oci_version"] = tag
            with self.subTest(boundary="spec", tag=tag), self.assertRaisesRegex(
                    p.ProvenanceError, "invalid reviewed fallback"):
                p.validate_spec(spec)

            with self.subTest(boundary="resolver", tag=tag), mock.patch.object(p, "run_json") as run:
                with self.assertRaisesRegex(p.ProvenanceError, "exact version tag"):
                    p.resolve_release_evidence("example/tool", tag, "d" * 40)
                run.assert_not_called()

        spec = self.spec()
        spec["components"].append(copy.deepcopy(spec["components"][0]))
        with self.assertRaisesRegex(p.ProvenanceError, "duplicate spec"):
            p.validate_spec(spec)
        lock = self.ready_lock()
        lock["components"].append(copy.deepcopy(lock["components"][0]))
        with self.assertRaisesRegex(p.ProvenanceError, "duplicate lock"):
            p.verify(self.spec(), lock)

    def test_malformed_entries_manifests_and_duplicate_platform_rejected(self):
        spec = self.spec()
        spec["extra"] = 1
        with self.assertRaisesRegex(p.ProvenanceError, "malformed spec"):
            p.validate_spec(spec)

        malformed = json.loads(self.raw_index())
        malformed["manifests"] = [None]
        with self.assertRaisesRegex(p.ProvenanceError, "malformed entries"):
            self.item(raw=json.dumps(malformed).encode())

        duplicate = json.loads(self.raw_index())
        duplicate["manifests"].append(copy.deepcopy(duplicate["manifests"][0]))
        with self.assertRaisesRegex(p.ProvenanceError, "exactly one"):
            self.item(raw=json.dumps(duplicate).encode())

    def test_bootstrap_vs_ready_contract_and_invariants(self):
        bootstrap = {"schema_version": 1, "status": "bootstrap", "components": []}
        p.verify(self.spec("bootstrap"), bootstrap, require_ready=False)
        with self.assertRaisesRegex(p.ProvenanceError, "non-buildable"):
            p.verify(self.spec("bootstrap"), bootstrap)
        lock = self.ready_lock()
        lock["components"][0]["evidence"]["release"]["is_rebuild"] = False
        with self.assertRaisesRegex(p.ProvenanceError, "rebuild flag"):
            p.verify(self.spec(), lock)

    def test_annotated_tag_and_missing_release(self):
        release = json.loads((FIX / "gh-release.json").read_text())
        ref = json.loads((FIX / "gh-tag-ref.json").read_text())
        annotated = {"object": {"sha": "d" * 40, "type": "commit"}}
        commit = {"sha": "d" * 40}
        with mock.patch.object(p, "run_json", side_effect=[release, release, ref, annotated, commit]):
            result = p.resolve_release_evidence("example/tool", "v1.2.3", "d" * 40)
            self.assertEqual(result["release_commit"], "d" * 40)
        with mock.patch.object(p, "run_json", side_effect=subprocess.CalledProcessError(1, ["gh"])):
            with self.assertRaisesRegex(p.ProvenanceError, "missing or unverifiable"):
                p.resolve_release_evidence("example/tool", "v1.2.3", "d" * 40)

    def test_github_latest_release_mismatch_fails_before_tag_resolution(self):
        latest = {"tag_name": "v1.2.4"}
        with mock.patch.object(p, "run_json", return_value=latest) as run:
            with self.assertRaisesRegex(p.ProvenanceError, "not the official latest release"):
                p.resolve_release_evidence("example/tool", "v1.2.3", "d" * 40)
            run.assert_called_once_with(["gh", "api", "repos/example/tool/releases/latest"])


if __name__ == "__main__":
    unittest.main()
