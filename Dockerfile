FROM python:3.12-slim-bookworm AS build

# C4ai version
ARG C4AI_VER=0.9.1
ENV C4AI_VERSION=$C4AI_VER
LABEL c4ai.version=$C4AI_VER

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
    REDIS_PORT=6379

ARG PYTHON_VERSION=3.12
ARG INSTALL_TYPE=default
ARG ENABLE_GPU=false
ARG PRELOAD_MODELS=false
ARG TARGETARCH

# Redis version — pinned to a CVE-patched release by default.
# Override with --build-arg REDIS_VERSION="" for latest, or
# --build-arg REDIS_VERSION="6:7.2.7-1rl1~bookworm1" for a specific version.
ARG REDIS_VERSION="6:7.2.7-1rl1~bookworm1"

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
    curl \
    wget \
    gnupg \
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
    libatspi2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN if [ "$ENABLE_GPU" = "true" ] && [ "$TARGETARCH" = "amd64" ] ; then \
    sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources ; \
fi \
    && apt-get update \
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
    fi \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and group
RUN groupadd -r appuser && useradd --no-log-init -r -g appuser appuser

# Create the appuser home, virtualenv, and cache directories up front so
# Python packages, Playwright browsers, and preloaded models live in the same
# user-owned location that runtime will use.
RUN mkdir -p /home/appuser/.cache/ms-playwright /home/appuser/.crawl4ai ${APP_HOME} \
    && python -m venv /home/appuser/.venv \
    && chown -R appuser:appuser /home/appuser ${APP_HOME}

ENV PATH=/home/appuser/.venv/bin:$PATH

WORKDIR ${APP_HOME}

COPY --chown=appuser:appuser . /tmp/project/

USER appuser

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/project/deploy/docker/requirements.txt \
    && if [ "$INSTALL_TYPE" = "all" ] ; then \
        pip install --no-cache-dir "/tmp/project[all]" torchvision torchaudio ; \
    elif [ "$INSTALL_TYPE" = "torch" ] ; then \
        pip install --no-cache-dir "/tmp/project[torch]" torchvision torchaudio ; \
    elif [ "$INSTALL_TYPE" = "transformer" ] ; then \
        pip install --no-cache-dir "/tmp/project[transformer]" ; \
    else \
        pip install --no-cache-dir "/tmp/project" ; \
    fi \
    && if [ "$INSTALL_TYPE" = "all" ] || [ "$INSTALL_TYPE" = "torch" ] ; then \
        python -m nltk.downloader punkt stopwords ; \
    fi \
    && if [ "$PRELOAD_MODELS" = "true" ] && { [ "$INSTALL_TYPE" = "all" ] || [ "$INSTALL_TYPE" = "transformer" ]; }; then \
        python -m crawl4ai.model_loader ; \
    else \
        echo "Skipping model preload during image build"; \
    fi \
    && python -c "import crawl4ai; print('✅ crawl4ai is ready to rock!')" \
    && python -c "from playwright.sync_api import sync_playwright; print('✅ Playwright is feeling dramatic!')"

USER root

RUN /home/appuser/.venv/bin/python -m playwright install-deps \
    && /home/appuser/.venv/bin/python -m patchright install-deps chromium

USER appuser

RUN CRAWL4AI_MODE=api crawl4ai-setup \
    && playwright install \
    && python -m patchright install chromium \
    && crawl4ai-doctor

USER root

# Remove transient build artifacts and any leftover package index/cache files
# after installation and validation. Keep installed packages intact.
RUN apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/project /root/.cache/pip

# Copy application code
COPY --chown=root:root deploy/docker/* ${APP_HOME}/

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

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD bash -c '\
    MEM=$(free -m | awk "/^Mem:/{print \$2}"); \
    if [ $MEM -lt 2048 ]; then \
        echo "⚠️ Warning: Less than 2GB RAM available! Your container might need a memory boost! 🚀"; \
        exit 1; \
    fi && \
    redis-cli ping > /dev/null && \
    curl -f http://localhost:11235/health || exit 1'

# Redis is in-container only (loopback + requirepass); never expose its port.
# (was: EXPOSE 6379)
# Switch to the non-root user before starting the application
USER appuser

# Set environment variables to ptoduction
ENV PYTHON_ENV=production 

# Start via entrypoint.sh, which resolves the socket-level auth/egress posture
# (loopback unless a credential is present) and the redis password, then execs
# supervisord.
CMD ["bash", "entrypoint.sh"]
