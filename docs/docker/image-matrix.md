# Docker Image Matrix

This document defines the Docker image contract for the v0.9.2 image work.
The first implementation target is a fully tested CPU image. GPU images are
separate artifacts and must not be inferred from a CPU image at runtime.

For the v0.9.2 AIO web-stack phase, the only publishable contract is
`INSTALL_TYPE=all`, `ENABLE_GPU=false`, and `PRELOAD_MODELS=true`, from
`refs/heads/aio-v0.9.2-web-stack-latest`. Other variants and refs fail
before the build. GPU rows below remain a future contract, not published
artifacts from this workflow.

The web-stack image adds the published-latest SearXNG source and Granian to the
same appuser-owned Python environment. It exposes Crawl4AI on `11235` and
SearXNG on `8080`. The upstream SearXNG Void Linux virtualenv is excluded;
only its digest-pinned source and precompressed static files cross the stage
boundary.

SearXNG intentionally binds all container interfaces and has no built-in API
authentication in this phase. Port `8080` is for an isolated, trusted Docker
network or LAN only; do not publish it directly to the Internet. The default
Compose root filesystem remains writable so operators can add models and
packages without rebuilding. Operators may enable read-only mode after their
runtime assets have been provisioned.

## Image Contract

Every published image must:

- run the API through the default `CMD` as `appuser`;
- keep application Python packages, models, and browser binaries in
  `/home/appuser`;
- install OS packages only as root and run the final application as `appuser`;
- pass an API health check using the default Docker runtime filesystem;
- contain only its declared browser and model assets after build cleanup; and
- carry a protected release tag and a protected source commit tag.

## Initial Variants

| Canonical tag suffix | Build arguments | Intended use |
| --- | --- | --- |
| `all-cpu-preload` | `INSTALL_TYPE=all`, `PRELOAD_MODELS=true`, `ENABLE_GPU=false`, CPU-only PyTorch wheels | Full CPU feature set with baked models and all Playwright browsers |
| `all-gpu-preload` | `INSTALL_TYPE=all`, `PRELOAD_MODELS=true`, `ENABLE_GPU=true`, CUDA-compatible PyTorch wheels | NVIDIA runtime hosts only |

This phase publishes the isolated aliases `aio-web-latest` and
`aio-web-all-cpu-preload`, a protected release tag
`v0.9.2-aio-web-all-cpu-preload`, and a protected source tag
`sha-<commit>-aio-web-all-cpu-preload`. It does not replace the existing
Crawl-only `latest` or `all` aliases. The workflow enforces immutability for
the protected tags:
an existing protected tag may be reused only when it already names the tested
digest, and a digest mismatch fails the release.

The GHCR workflow first publishes a non-release `candidate-<run>-<attempt>`
tag. Smoke, package, Crawl4AI runtime, MCP, and Chromium/Firefox/WebKit checks
run against that candidate's immutable digest. Only after all checks pass does
one metadata-only promotion attach mutable, v0.9.2 release, and full source-SHA
tags to that exact digest; the image is not rebuilt during promotion. The image
labels and workflow summary record the locked upstream index digest and release
commit from `aio/provenance/components.lock.json`. Workflow concurrency
serializes builds for the publishing branch, and promotion reads the
authoritative remote branch tip again immediately before moving any tag.
Therefore `aio-web-latest` and
`aio-web-all-cpu-preload` can move only for the current publishing-branch tip.

## v0.9.2 dependency lock identity

The published image uses the dedicated Python 3.12 AIO project at
`aio/runtime/pyproject.toml` and its adjacent `uv.lock`. This leaves the
library's cross-version development lock semantics unchanged. The AIO project
locks the local `crawl4ai[all]` package together with every API dependency and
pins `torch==2.13.0+cpu`, `torchvision==0.28.0+cpu`, and
`torchaudio==2.11.0+cpu` to PyTorch's explicit CPU wheel index. The lock has no
CUDA, NVIDIA, or Triton distributions.

The Docker build runs `uv sync --frozen` into the appuser virtual environment.
It ships the lock as `/opt/crawl4ai/aio-runtime.uv.lock`; smoke verification
compares every installed distribution version with that lock, rejects
unlocked distributions, checks direct locked dependencies, and validates
installed dependency metadata in addition to running `pip check`.

The long form requested by operators,
`install-type-all-with-cpu-preload-true-gpu-false-without-cuda-triton`, is a
description of `all-cpu-preload`; it is not a separate artifact. Keeping one
canonical tag prevents duplicate images with identical content.

## Build Cache Policy

BuildKit cache is builder state, not runtime image content. A "wiped-build-kit"
variant therefore cannot produce a meaningfully different runtime image.

- Development builds may import/export a branch-scoped remote cache.
- Release verification builds use `pull: true` and no external cache export.
- A release is published only after the clean build passes the runtime suite.

## Dependency Authority

- The installed Playwright version supplies browser OS dependencies through
  `python -m playwright install-deps` executed as root.
- Browser payloads are installed separately as `appuser` into the persistent
  `PLAYWRIGHT_BROWSERS_PATH`.
- CPU images resolve `torch`, `torchvision`, and `torchaudio` only from
  PyTorch's explicit CPU wheel index in the frozen AIO runtime lock.
- GPU images select their CUDA wheel index and host-runtime contract explicitly.

## Runtime Verification Matrix

The publishing workflow must prove the final image, rather than only the build
layers, satisfies these checks:

1. Start the default `CMD` with the normal Docker runtime filesystem.
2. Wait for the Docker health check and verify the API health endpoint.
3. Verify `gunicorn` is launched from `/home/appuser/.venv/bin`.
4. Run `pip check` and compare all installed versions with the shipped AIO lock.
5. Launch Chromium, Firefox, and WebKit as appuser.
6. Run one Crawl4AI crawl as appuser.
7. For CPU images, assert CUDA/Triton package directories are absent and
   `torch.cuda.is_available()` is false.
8. Verify declared model and NLTK assets are present when preload is enabled.
9. Verify SearXNG `/healthz`, `/config`, and a real JSON search using its
   appuser Granian process.
10. Verify `/usr/local/searxng/.venv` is absent and all installed Python
    distributions match the shipped AIO runtime lock.

## Cleanup Rules

Do not remove preloaded Hugging Face models, NLTK data, or declared Playwright
browsers. They are runtime assets, not caches.

Remove transient files in the same layer in which they are created whenever
possible. The final cleanup removes the build-only uv executable, uv/pip
caches, apt indexes, apt archives, build source, package-manager logs, font
cache, and setup-generated Crawl4AI state only after build verification.

The AIO image intentionally remains an extensible toolkit. Its existing OS
packages, including `build-essential`, `wget`, `git`, `cmake`, `pkg-config`,
`python3-dev`, `libjpeg-dev`, `gnupg`, and architecture-specific OpenBLAS/OpenMP
development packages, remain available in the final image.
