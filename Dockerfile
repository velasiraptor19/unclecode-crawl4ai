# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.25@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9 AS uv-bin

FROM docker.io/searxng/searxng@sha256:1a196e52ef0aec52a462667e5c54030840f94865c13e1260004caa10cca6be49 AS searxng-source

# Materialize a source-only filesystem snapshot. The final Debian image copies
# from this stage, so the upstream Void virtualenv and its layers are not inherited.
FROM searxng-source AS searxng-sanitized
USER root
RUN rm -rf /usr/local/searxng/.venv \
    && test ! -e /usr/local/searxng/.venv

FROM python:3.12-slim-bookworm@sha256:72d3d75f2639ab82b34b29390ad3d6e0827c775befee94edda8e9976818f488d AS build

# C4ai version
ARG C4AI_VER=0.9.2
ARG AIO_IMAGE_REVISION=1
ARG SOURCE_COMMIT=unknown
ARG AIO_PROVENANCE_INDEX_DIGEST=unlocked
ARG AIO_PROVENANCE_RELEASE_COMMIT=unlocked
ARG AIO_SEARXNG_INDEX_DIGEST=unlocked
ARG AIO_SEARXNG_PLATFORM_DIGEST=unlocked
ARG AIO_SEARXNG_VERSION=unlocked
ARG AIO_SEARXNG_SOURCE_COMMIT=unlocked
ARG AIO_CAMOUFOX_PACKAGE_VERSION=unlocked
ARG AIO_CAMOUFOX_BROWSER_VERSION=unlocked
ARG AIO_CAMOUFOX_BROWSER_SHA256=unlocked
ENV C4AI_VERSION=$C4AI_VER
LABEL c4ai.version=$C4AI_VER \
    org.opencontainers.image.version=$C4AI_VER \
    org.opencontainers.image.revision=$SOURCE_COMMIT \
    io.crawl4ai.aio.image-revision=$AIO_IMAGE_REVISION \
    io.crawl4ai.aio.provenance.index-digest=$AIO_PROVENANCE_INDEX_DIGEST \
    io.crawl4ai.aio.provenance.release-commit=$AIO_PROVENANCE_RELEASE_COMMIT \
    io.crawl4ai.aio.searxng.index-digest=$AIO_SEARXNG_INDEX_DIGEST \
    io.crawl4ai.aio.searxng.platform-digest=$AIO_SEARXNG_PLATFORM_DIGEST \
    io.crawl4ai.aio.searxng.version=$AIO_SEARXNG_VERSION \
    io.crawl4ai.aio.searxng.source-commit=$AIO_SEARXNG_SOURCE_COMMIT \
    io.crawl4ai.aio.camoufox.package-version=$AIO_CAMOUFOX_PACKAGE_VERSION \
    io.crawl4ai.aio.camoufox.browser-version=$AIO_CAMOUFOX_BROWSER_VERSION \
    io.crawl4ai.aio.camoufox.browser-sha256=$AIO_CAMOUFOX_BROWSER_SHA256

# Set build arguments
ARG APP_HOME=/app

ENV PYTHONFAULTHANDLER=1 \
    HOME=/home/appuser \
    PYTHONHASHSEED=random \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright \
    XDG_CACHE_HOME=/home/appuser/.cache \
    DEBIAN_FRONTEND=noninteractive \
    REDIS_HOST=localhost \
    REDIS_PORT=6379 \
    SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml \
    DISPLAY=:99 \
    CAMOUFOX_CACHE_DIR=/home/appuser/.cache/camoufox

ARG PYTHON_VERSION=3.12
ARG INSTALL_TYPE=all
ARG ENABLE_GPU=false
ARG PRELOAD_MODELS=true
ARG TARGETARCH
ARG CAMOUFOX_BROWSER_VERSION=150.0.2-alpha.26
ARG CAMOUFOX_BROWSER_URL=https://github.com/daijro/camoufox/releases/download/v150.0.2-beta.25/camoufox-150.0.2-alpha.26-lin.x86_64.zip
ARG CAMOUFOX_BROWSER_SHA256=b146b98b0c2c41023716feef36451f319a534309f72c54584a4b0b88670f510b

# Redis version — pinned to a CVE-patched release by default.
# Override with --build-arg REDIS_VERSION="" for latest, or
# --build-arg REDIS_VERSION="6:7.2.7-1rl1~bookworm1" for a specific version.
ARG REDIS_VERSION="6:7.2.7-1rl1~bookworm1"

RUN test "$INSTALL_TYPE" = "all" && test "$ENABLE_GPU" = "false"

LABEL maintainer="unclecode"
LABEL description="🔥🕷️ Crawl4AI: Open-source LLM Friendly Web Crawler & scraper"
LABEL version="1.0"

# Reserve the runtime identity before Debian packages create their own system
# users. Otherwise packages such as Redis may claim UID/GID 999 first.
RUN groupadd --system --gid 999 appuser \
    && useradd --no-log-init --system --uid 999 --gid 999 --home-dir /home/appuser appuser

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg \
    && curl -fsSL https://packages.redis.io/gpg | gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb bookworm main" \
    > /etc/apt/sources.list.d/redis.list \
    && apt-get update \
    && apt-get dist-upgrade -y \
    && apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    git \
    cmake \
    pkg-config \
    python3-dev \
    libjpeg-dev \
    unzip \
    xvfb \
    fluxbox \
    x11vnc \
    novnc \
    websockify \
    redis-tools${REDIS_VERSION:+=$REDIS_VERSION} \
    redis-server${REDIS_VERSION:+=$REDIS_VERSION} \
    supervisor \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libcairo-gobject2 \
    libgdk-pixbuf-2.0-0 \
    libgtk-3-0 \
    libpangocairo-1.0-0 \
    libxcb1 \
    libxcursor1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libgl1 \
    libegl1 \
    libgles2 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0

RUN if [ "$ENABLE_GPU" = "true" ] && [ "$TARGETARCH" = "amd64" ] ; then \
    sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources ; \
    apt-get update ; \
fi \
    && if [ "$ENABLE_GPU" = "true" ] && [ "$TARGETARCH" = "amd64" ] ; then \
        apt-get install -y --no-install-recommends nvidia-cuda-toolkit ; \
    else \
        echo "Skipping NVIDIA CUDA Toolkit installation (unsupported platform or GPU disabled)" ; \
    fi \
    && if [ "$TARGETARCH" = "arm64" ]; then \
        echo "🦾 Installing ARM-specific optimizations" ; \
        apt-get install -y --no-install-recommends libopenblas-dev ; \
    elif [ "$TARGETARCH" = "amd64" ]; then \
        echo "🖥️ Installing AMD64-specific optimizations" ; \
        apt-get install -y --no-install-recommends libomp-dev ; \
    else \
        echo "Skipping platform-specific optimizations (unsupported platform)" ; \
    fi

# Create the appuser home and cache directories up front so
# Python packages, Playwright browsers, and preloaded models live in the same
# user-owned location that runtime will use.
RUN mkdir -p /home/appuser/.cache/ms-playwright /home/appuser/.crawl4ai ${APP_HOME} \
    && chown -R appuser:appuser /home/appuser ${APP_HOME}

ENV PATH=/home/appuser/.venv/bin:$PATH

WORKDIR ${APP_HOME}

USER appuser

RUN --mount=type=bind,source=.,target=/mnt/project,readonly \
    --mount=type=bind,from=uv-bin,source=/,target=/opt/uv-bin,readonly \
    --mount=type=cache,id=crawl4ai-aio-source,target=/tmp/project,uid=999,gid=999,mode=0700,sharing=locked \
    find /tmp/project -mindepth 1 -maxdepth 1 -exec rm -rf {} + \
    && cp -R --no-preserve=ownership /mnt/project/. /tmp/project/ \
    && chmod -R u+w /tmp/project \
    && UV_PROJECT_ENVIRONMENT=/home/appuser/.venv UV_CACHE_DIR=/tmp/uv-cache \
        /opt/uv-bin/uv sync --project /tmp/project/aio/runtime --frozen --no-dev --no-editable \
    && rm -rf /tmp/uv-cache \
    && python -c "import nltk; assert nltk.download('punkt'); assert nltk.download('stopwords')" \
    && if [ "$PRELOAD_MODELS" = "true" ]; then \
        python -c "from crawl4ai.model_loader import download_all_models; download_all_models()" ; \
    else \
        echo "Skipping model preload during image build"; \
    fi \
    && python -c "import crawl4ai; print('✅ crawl4ai is ready to rock!')" \
    && python -c "from playwright.sync_api import sync_playwright; print('✅ Playwright is feeling dramatic!')" \
    && find /tmp/project -mindepth 1 -maxdepth 1 -exec rm -rf {} +

# Install the reviewed Camoufox browser archive directly into appuser's cache.
# The package and browser are separate locks: PyPI supplies the Python API,
# while this exact GitHub release asset supplies the Firefox-derived runtime.
RUN set -eux; \
    browser_dir="${CAMOUFOX_CACHE_DIR}/browsers/official/${CAMOUFOX_BROWSER_VERSION}"; \
    mkdir -p "${browser_dir}"; \
    curl -fL --retry 5 --retry-all-errors "${CAMOUFOX_BROWSER_URL}" -o /tmp/camoufox.zip; \
    echo "${CAMOUFOX_BROWSER_SHA256}  /tmp/camoufox.zip" | sha256sum -c -; \
    unzip -q /tmp/camoufox.zip -d "${browser_dir}"; \
    rm -f /tmp/camoufox.zip; \
    printf '%s\n' \
      '{"version":"150.0.2","build":"alpha.26","prerelease":false,"asset_id":419692983,"asset_size":661687098,"asset_updated_at":"2026-05-13T23:38:29Z"}' \
      > "${browser_dir}/version.json"; \
    printf '%s\n' \
      '{"active_version":"browsers/official/150.0.2-alpha.26","channel":"official/stable","pinned":"150.0.2-alpha.26"}' \
      > "${CAMOUFOX_CACHE_DIR}/config.json"; \
    touch "${CAMOUFOX_CACHE_DIR}/.0.5_FLAG"; \
    python -c "from camoufox.pkgman import camoufox_path; print(camoufox_path(download_if_missing=False))"

USER root

RUN /home/appuser/.venv/bin/python -m playwright install-deps

USER appuser

RUN CRAWL4AI_MODE=api crawl4ai-setup \
    && playwright install \
    && python -m patchright install chromium \
    && crawl4ai-doctor

# Validate the final appuser-owned runtime assets before root removes transient
# setup state. Doctor covers a real Crawl4AI crawl; this adds all browsers,
# Patchright, preload assets, and the declared CPU package contract.
RUN INSTALL_TYPE="$INSTALL_TYPE" PRELOAD_MODELS="$PRELOAD_MODELS" ENABLE_GPU="$ENABLE_GPU" python - <<'PY'
import importlib.util
import json
import os
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright
from patchright.sync_api import sync_playwright as sync_patchright
from camoufox.addons import DefaultAddons
from camoufox.sync_api import Camoufox

home = Path(os.environ["HOME"])
browser_root = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
failures = []


def check(name, operation):
    try:
        operation()
    except Exception as exc:
        failures.append(f"{name}: {type(exc).__name__}: {exc}")
        print(f"[FAIL] {name}")
        traceback.print_exc()
    else:
        print(f"[PASS] {name}")


def default_browser_manifest(package_name):
    spec = importlib.util.find_spec(package_name)
    assert spec and spec.submodule_search_locations, f"cannot locate {package_name} package"
    package_root = Path(next(iter(spec.submodule_search_locations)))
    manifest = json.loads(
        (package_root / "driver" / "package" / "browsers.json").read_text(encoding="utf-8")
    )
    return {
        browser["name"]: str(browser["revision"])
        for browser in manifest["browsers"]
        if browser.get("installByDefault")
    }


def verify_assets():
    playwright_manifest = default_browser_manifest("playwright")
    patchright_manifest = default_browser_manifest("patchright")
    assert patchright_manifest == playwright_manifest, (
        f"Playwright/Patchright browser revisions differ: "
        f"{playwright_manifest} != {patchright_manifest}"
    )
    expected = {
        f"{name.replace('-', '_')}-{revision}"
        for name, revision in playwright_manifest.items()
    }
    prefixes = tuple(f"{name.replace('-', '_')}-" for name in playwright_manifest)
    installed = {
        path.name
        for path in browser_root.iterdir()
        if path.is_dir() and path.name.startswith(prefixes)
    }
    assert installed == expected, f"unexpected Playwright asset set: {sorted(installed)}"


def verify_playwright(browser_name):
    with sync_playwright() as playwright:
        browser = getattr(playwright, browser_name).launch()
        page = browser.new_page()
        page.set_content(f"<title>{browser_name}</title>")
        assert page.title() == browser_name
        browser.close()


def verify_patchright():
    with sync_patchright() as patchright:
        browser = patchright.chromium.launch()
        browser.close()


def verify_camoufox():
    with Camoufox(
        headless=True,
        os="linux",
        fingerprint_preset=True,
        webgl_config=("Intel", "Intel(R) HD Graphics, or similar"),
        exclude_addons=list(DefaultAddons),
    ) as browser:
        page = browser.new_page()
        page.set_content("<title>camoufox</title>")
        assert page.title() == "camoufox"


def verify_huggingface_preload():
    assert (home / ".cache" / "huggingface").is_dir(), "preloaded Hugging Face models missing"


def verify_nltk_preload():
    assert (home / "nltk_data").is_dir(), "preloaded NLTK data missing"


def verify_cpu_contract():
    import torch

    assert not torch.cuda.is_available(), "CPU image unexpectedly has an available CUDA device"
    for package in ("nvidia", "triton", "cuda"):
        assert importlib.util.find_spec(package) is None, f"CPU image contains {package}"


check("playwright_assets", verify_assets)
for name in ("chromium", "firefox", "webkit"):
    check(f"playwright_{name}", lambda name=name: verify_playwright(name))
check("patchright_chromium", verify_patchright)
check("camoufox", verify_camoufox)

if os.environ["PRELOAD_MODELS"] == "true" and os.environ["INSTALL_TYPE"] in {"all", "transformer"}:
    check("huggingface_preload", verify_huggingface_preload)
if os.environ["INSTALL_TYPE"] in {"all", "torch"}:
    check("nltk_preload", verify_nltk_preload)
if os.environ["ENABLE_GPU"] == "false" and os.environ["INSTALL_TYPE"] in {"all", "torch"}:
    check("cpu_package_contract", verify_cpu_contract)

if failures:
    raise AssertionError("build runtime failures:\n- " + "\n- ".join(failures))
PY

USER root

# The Redis repository and the optional GPU repository each require a fresh
# package index. Keep indexes until Playwright's root-only dependency install
# has finished, then clean every apt cache exactly once.
RUN apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /root/.cache/pip \
    && rm -rf /var/log/apt /var/log/dpkg.log /var/log/fontconfig.log /var/cache/fontconfig \
    && rm -rf /tmp/* /var/tmp/* \
    && find /home/appuser/.crawl4ai -mindepth 1 -maxdepth 1 -exec rm -rf {} + \
    && chown -R appuser:appuser /home/appuser/.crawl4ai

# Copy application code
COPY --chown=root:root deploy/docker/* ${APP_HOME}/

RUN mkdir -p /opt/crawl4ai
COPY --chown=root:root aio/runtime/uv.lock /opt/crawl4ai/aio-runtime.uv.lock

# Copy only the sanitized merged filesystem into Debian. No stage based on the
# upstream Void image is an ancestor of this final stage.
COPY --from=searxng-sanitized --chown=root:root /usr/local/searxng/ /usr/local/searxng/
COPY --chown=root:root aio/searxng/settings.yml /etc/searxng/settings.yml

# copy the playground + any future static assets
COPY --chown=root:root deploy/docker/static ${APP_HOME}/static

# /app is root-owned and read-only to the runtime user: a write bug can no
# longer plant a persistent self-RCE in the application directory.
RUN chown -R root:root ${APP_HOME} && chmod -R a-w ${APP_HOME}

# give permissions to redis persistence dirs if used
RUN mkdir -p /var/lib/redis /var/log/redis && chown -R appuser:appuser /var/lib/redis /var/log/redis

# Sandboxed artifact store (server-owned screenshot/PDF outputs), 0700.
RUN mkdir -p /var/lib/crawl4ai/outputs \
    && chown -R appuser:appuser /var/lib/crawl4ai \
    && chmod 700 /var/lib/crawl4ai/outputs

RUN mkdir -p /var/cache/searxng \
    && chown appuser:appuser /var/cache/searxng \
    && chmod 700 /var/cache/searxng \
    && test ! -e /usr/local/searxng/.venv

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD bash -c '\
    MEM=$(free -m | awk "/^Mem:/{print \$2}"); \
    if [ $MEM -lt 2048 ]; then \
        echo "⚠️ Warning: Less than 2GB RAM available! Your container might need a memory boost! 🚀"; \
        exit 1; \
    fi && \
    redis-cli ping > /dev/null && \
    curl -f http://localhost:11235/health && \
    curl -f http://localhost:8080/healthz || exit 1'

# Redis is in-container only (loopback + requirepass); never expose its port.
# (was: EXPOSE 6379)
EXPOSE 11235 8080 6080
# Switch to the non-root user before starting the application
USER appuser

# Set the runtime environment.
ENV PYTHON_ENV=production 

RUN cd /usr/local/searxng \
    && python -c "import granian, searx; print('SearXNG shared appuser runtime is ready')" \
    && test ! -e /usr/local/searxng/.venv \
    && cd ${APP_HOME} \
    && CRAWL4AI_API_TOKEN=build-import-check \
       SECRET_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
       python -c "import server; assert server.app; print('Crawl4AI server import is ready')"

# Start via entrypoint.sh, which resolves the socket-level auth/egress posture
# (loopback unless a credential is present) and the redis password, then execs
# supervisord.
CMD ["bash", "entrypoint.sh"]
