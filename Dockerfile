# syntax=docker/dockerfile:1

FROM docker.io/searxng/searxng@sha256:1a196e52ef0aec52a462667e5c54030840f94865c13e1260004caa10cca6be49 AS searxng-source

# Materialize a source-only filesystem snapshot. The final Debian image copies
# from this stage, so the upstream Void virtualenv and its layers are not inherited.
FROM searxng-source AS searxng-sanitized
USER root
RUN rm -rf /usr/local/searxng/.venv \
    && test ! -e /usr/local/searxng/.venv

FROM python:3.12-slim-bookworm AS build

# C4ai version
ARG C4AI_VER=0.9.2
ARG SOURCE_COMMIT=unknown
ARG AIO_PROVENANCE_INDEX_DIGEST=unlocked
ARG AIO_PROVENANCE_RELEASE_COMMIT=unlocked
ARG AIO_SEARXNG_INDEX_DIGEST=unlocked
ARG AIO_SEARXNG_PLATFORM_DIGEST=unlocked
ARG AIO_SEARXNG_VERSION=unlocked
ARG AIO_SEARXNG_SOURCE_COMMIT=unlocked
ENV C4AI_VERSION=$C4AI_VER
LABEL c4ai.version=$C4AI_VER \
    org.opencontainers.image.version=$C4AI_VER \
    org.opencontainers.image.revision=$SOURCE_COMMIT \
    io.crawl4ai.aio.provenance.index-digest=$AIO_PROVENANCE_INDEX_DIGEST \
    io.crawl4ai.aio.provenance.release-commit=$AIO_PROVENANCE_RELEASE_COMMIT \
    io.crawl4ai.aio.searxng.index-digest=$AIO_SEARXNG_INDEX_DIGEST \
    io.crawl4ai.aio.searxng.platform-digest=$AIO_SEARXNG_PLATFORM_DIGEST \
    io.crawl4ai.aio.searxng.version=$AIO_SEARXNG_VERSION \
    io.crawl4ai.aio.searxng.source-commit=$AIO_SEARXNG_SOURCE_COMMIT

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
    SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml

ARG PYTHON_VERSION=3.12
ARG INSTALL_TYPE=all
ARG ENABLE_GPU=false
ARG PRELOAD_MODELS=true
ARG TARGETARCH
ARG UV_VERSION=0.11.25

# Redis version — pinned to a CVE-patched release by default.
# Override with --build-arg REDIS_VERSION="" for latest, or
# --build-arg REDIS_VERSION="6:7.2.7-1rl1~bookworm1" for a specific version.
ARG REDIS_VERSION="6:7.2.7-1rl1~bookworm1"

RUN test "$INSTALL_TYPE" = "all" && test "$ENABLE_GPU" = "false"

LABEL maintainer="unclecode"
LABEL description="🔥🕷️ Crawl4AI: Open-source LLM Friendly Web Crawler & scraper"
LABEL version="1.0"

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

# Keep the runtime identity aligned with Compose tmpfs ownership.
RUN groupadd --system --gid 999 appuser \
    && useradd --no-log-init --system --uid 999 --gid 999 --home-dir /home/appuser appuser

# Create the appuser home and cache directories up front so
# Python packages, Playwright browsers, and preloaded models live in the same
# user-owned location that runtime will use.
RUN mkdir -p /home/appuser/.cache/ms-playwright /home/appuser/.crawl4ai ${APP_HOME} \
    && chown -R appuser:appuser /home/appuser ${APP_HOME}

ENV PATH=/home/appuser/.venv/bin:$PATH

WORKDIR ${APP_HOME}

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

USER appuser

RUN --mount=type=bind,source=.,target=/tmp/project,readonly \
    UV_PROJECT_ENVIRONMENT=/home/appuser/.venv UV_CACHE_DIR=/tmp/uv-cache \
        uv sync --project /tmp/project/aio/runtime --frozen --no-dev --no-editable \
    && rm -rf /tmp/uv-cache \
    && python -m nltk.downloader punkt stopwords \
    && if [ "$PRELOAD_MODELS" = "true" ]; then \
        python -m crawl4ai.model_loader ; \
    else \
        echo "Skipping model preload during image build"; \
    fi \
    && python -c "import crawl4ai; print('✅ crawl4ai is ready to rock!')" \
    && python -c "from playwright.sync_api import sync_playwright; print('✅ Playwright is feeling dramatic!')"

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
import os
from pathlib import Path

from playwright.sync_api import sync_playwright
from patchright.sync_api import sync_playwright as sync_patchright

home = Path(os.environ["HOME"])
browser_root = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
expected_assets = ("chromium-", "chromium_headless_shell-", "firefox-", "webkit-", "ffmpeg-")
installed_assets = tuple(path.name for path in browser_root.iterdir())
for prefix in expected_assets:
    assert any(name.startswith(prefix) for name in installed_assets), f"missing Playwright asset: {prefix}"

with sync_playwright() as playwright:
    for browser_name in ("chromium", "firefox", "webkit"):
        browser = getattr(playwright, browser_name).launch()
        page = browser.new_page()
        page.set_content(f"<title>{browser_name}</title>")
        assert page.title() == browser_name
        browser.close()

with sync_patchright() as patchright:
    browser = patchright.chromium.launch()
    browser.close()

if os.environ["PRELOAD_MODELS"] == "true" and os.environ["INSTALL_TYPE"] in {"all", "transformer"}:
    assert (home / ".cache" / "huggingface").is_dir(), "preloaded Hugging Face models missing"
if os.environ["INSTALL_TYPE"] in {"all", "torch"}:
    assert (home / "nltk_data").is_dir(), "preloaded NLTK data missing"
if os.environ["ENABLE_GPU"] == "false" and os.environ["INSTALL_TYPE"] in {"all", "torch"}:
    import torch
    assert not torch.cuda.is_available(), "CPU image unexpectedly has an available CUDA device"
    for package in ("nvidia", "triton", "cuda"):
        assert importlib.util.find_spec(package) is None, f"CPU image contains {package}"
PY

USER root

# The Redis repository and the optional GPU repository each require a fresh
# package index. Keep indexes until Playwright's root-only dependency install
# has finished, then clean every apt cache exactly once.
RUN apt-get clean \
    && python -m pip uninstall -y uv \
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
EXPOSE 11235 8080
# Switch to the non-root user before starting the application
USER appuser

# Set the runtime environment.
ENV PYTHON_ENV=production 

RUN cd /usr/local/searxng \
    && python -c "import granian, searx; print('SearXNG shared appuser runtime is ready')" \
    && test ! -e /usr/local/searxng/.venv

# Start via entrypoint.sh, which resolves the socket-level auth/egress posture
# (loopback unless a credential is present) and the redis password, then execs
# supervisord.
CMD ["bash", "entrypoint.sh"]
