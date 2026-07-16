# AIO Image Verification

The AIO release pipeline separates image construction, runtime verification,
and tag promotion. A candidate is never published under a final tag until the
exact registry digest has passed the complete runtime suite.

## Failure policy

True prerequisites fail fast because no meaningful downstream check can run:

- invalid source/provenance locks
- an invalid Dockerfile or unresolved package lock
- failure to build, push, pull, or start the candidate image

Independent checks collect failures and continue. The suite returns a failing
status only after every applicable check has run:

- container health
- `pip check` and appuser ownership
- frozen runtime, CPU-only, preload, Playwright, and real crawl contracts
- SearXNG health, config, source layout, and real search
- direct REST calls for every default web tool
- MCP authentication and Streamable HTTP calls for every default web tool
- noVNC availability
- absence of known actionable framework and Camoufox proxy warnings in runtime logs

The Dockerfile's build-time browser verifier follows the same collecting model
for Chromium, Firefox, WebKit, Patchright, Camoufox, preload assets, and the CPU
package contract.

Playwright system packages are resolved by the installed Playwright version's
own `install-deps` command. Browser asset expectations are likewise read from
the installed Playwright and Patchright `browsers.json` manifests. The build
requires those manifests to agree and rejects missing or duplicate browser
revisions in appuser's runtime cache.

The pinned `uv` executable is mounted from a digest-locked tool stage only for
the dependency sync step. It is not installed into the Python runtime and the
ownership contract verifies that neither `uv` nor `uvx` leaks into the final
image.

## Image revisions

The Crawl4AI application version and AIO packaging revision are independent.
Immutable release tags use `v<C4AI_VERSION>-r<AIO_IMAGE_REVISION>-...`, while
the OCI `org.opencontainers.image.version` label remains the application
version. Any image-content change after an immutable release increments the AIO
revision instead of replacing the previously published digest.

## Evidence

`tests/docker/smoke-test.sh` writes one Markdown index plus one log per check,
the full container log, and `docker inspect` output. GitHub Actions uploads that
directory as a 30-day artifact and appends the index to the run summary.

The smoke step uses `continue-on-error` only so evidence collection can finish.
A separate required gate checks its original outcome before promotion. Any
failed check therefore blocks all final tags.

## Retesting a digest

The `Verify Existing Crawl4AI AIO Candidate` workflow accepts only an immutable
reference from this repository in this form:

```text
ghcr.io/OWNER/REPOSITORY:optional-tag@sha256:DIGEST
```

It mounts the verification scripts from the selected branch into the existing
candidate and runs the complete suite without rebuilding or promoting it. Use
this path when only verification code or assertions changed. Changes to image
contents still require a new build and a new digest.
