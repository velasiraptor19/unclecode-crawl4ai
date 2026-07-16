# AIO provenance

Phase 0 records provenance and installs nothing. Published latest always means
the registry `<image>:latest`, never a GitHub default branch. Resolution reads
the manifest index and image configuration only; it does not pull layers.

The spec and lock have an explicit two-state contract:

- `bootstrap`: visible, valid metadata scaffolding, but non-buildable. The lock
  must contain no components and the normal verifier always fails.
- `ready`: every spec component must have a reviewed lock entry and the normal
  offline verifier must pass. AIO builds must invoke this verifier first.

```bash
scripts/aio-provenance-resolve --spec aio/provenance/components.json --output /tmp/components.lock.json
scripts/aio-provenance-verify --spec aio/provenance/components.json --lock /tmp/components.lock.json
```

Resolution pins both the registry index digest and its single `linux/amd64`
platform digest. The lock embeds the exact registry index bytes; the offline
verifier hashes those bytes and derives platform membership from the parsed
index instead of trusting copied digest fields. Valid attestation manifests are
ignored as platforms. Complete OCI
`version`, `revision`, and `source` labels are the strongest evidence path:
source must match the official repository and revision must be an independently
verified immutable commit.

When labels are absent or incomplete, `reviewed_fallback` explicitly supplies
the exact reviewed `latest` index and platform digests, released version,
official latest release tag, peeled release commit, and published source commit.
Every present OCI label must be valid and agree with that evidence; conflicting
partial provenance fails closed. The resolver
verifies the GitHub latest-release endpoint, release endpoint, peeled tag commit,
and published commit independently. It records every missing OCI label and the
`reviewed-release-fallback` method; it never consults `main` or `master`.

`release_commit` is the immutable commit to which the release tag peels.
`published_source_commit` is the immutable source used to publish or rebuild the
registry image. They may differ for a legitimate rebuild, in which case
`is_rebuild` is true; both remain mapped to the same reviewed released version.
The verifier rejects pretending that one commit is the other.

The checked-in state is `ready` for the reviewed official v0.9.2 publication.
Normal operation only consumes that lock and never silently resolves `latest`.
Future drift updates must review new registry and release evidence, replace the
lock, and update the spec in the same change.
