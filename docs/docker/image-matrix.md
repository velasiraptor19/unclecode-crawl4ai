# Docker Image Matrix

This document defines the Docker image contract for the v0.9.1 image work.
The first implementation target is a fully tested CPU image. GPU images are
separate artifacts and must not be inferred from a CPU image at runtime.

## Image Contract

Every published image must:

- run the API through the default `CMD` as `appuser`;
- keep application Python packages, models, and browser binaries in
  `/home/appuser`;
- install OS packages only as root and run the final application as `appuser`;
- pass an API health check in a read-only root filesystem with writable runtime
  mounts;
- contain only its declared browser and model assets after build cleanup; and
- carry a tag containing the Crawl4AI release and a source commit tag.

## Initial Variants

| Canonical tag suffix | Build arguments | Intended use |
| --- | --- | --- |
| `all-cpu-preload` | `INSTALL_TYPE=all`, `PRELOAD_MODELS=true`, `ENABLE_GPU=false`, CPU-only PyTorch wheels | Full CPU feature set with baked models and all Playwright browsers |
| `all-gpu-preload` | `INSTALL_TYPE=all`, `PRELOAD_MODELS=true`, `ENABLE_GPU=true`, CUDA-compatible PyTorch wheels | NVIDIA runtime hosts only |

For each canonical suffix, publish a release tag such as
`v0.9.1-all-cpu-preload` and an immutable source tag such as
`sha-<commit>-all-cpu-preload`. The short `all` tag is an explicit alias for
the selected default variant, never an unspecified mixture of CPU and GPU
dependencies.

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
- CPU images install `torch`, `torchvision`, and `torchaudio` from PyTorch's
  official CPU wheel index before installing Crawl4AI extras. The subsequent
  Crawl4AI install must retain those already-resolved CPU packages.
- GPU images select their CUDA wheel index and host-runtime contract explicitly.

## Runtime Verification Matrix

The publishing workflow must prove the final image, rather than only the build
layers, satisfies these checks:

1. Start the default `CMD` with a read-only root filesystem and writable
   `/tmp`, Redis, and Crawl4AI output paths.
2. Wait for the Docker health check and verify the API health endpoint.
3. Verify `gunicorn` is launched from `/home/appuser/.venv/bin`.
4. Run `pip check` from the appuser virtual environment.
5. Launch Chromium, Firefox, and WebKit as appuser.
6. Run one Crawl4AI crawl as appuser.
7. For CPU images, assert CUDA/Triton package directories are absent and
   `torch.cuda.is_available()` is false.
8. Verify declared model and NLTK assets are present when preload is enabled.

## Cleanup Rules

Do not remove preloaded Hugging Face models, NLTK data, or declared Playwright
browsers. They are runtime assets, not caches.

Remove transient files in the same layer in which they are created whenever
possible. The final cleanup may remove apt indexes, apt archives, build source,
pip caches, package-manager logs, font cache, and setup-generated Crawl4AI
state only after all build verification has completed.
