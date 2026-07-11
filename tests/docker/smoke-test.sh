#!/usr/bin/env bash
set -euo pipefail

image="$1"
container="crawl4ai-smoke-${GITHUB_RUN_ID:-local}"

cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker pull "$image"
docker run --detach --name "$container" --read-only --shm-size=1g \
    --tmpfs /tmp:rw,exec,nosuid,nodev,size=1g \
    --tmpfs /var/lib/redis:rw,uid=999,gid=999,mode=0700 \
    --tmpfs /var/log/redis:rw,uid=999,gid=999,mode=0700 \
    --tmpfs /var/lib/crawl4ai:rw,uid=999,gid=999,mode=0700 \
    --mount "type=bind,src=${PWD}/tests/docker/verify_runtime.py,dst=/tmp/verify_runtime.py,readonly" \
    "$image" >/dev/null

for _ in $(seq 1 60); do
    health="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
    if [ "$health" = "healthy" ]; then
        break
    fi
    if [ "$health" = "unhealthy" ]; then
        docker logs "$container"
        exit 1
    fi
    sleep 2
done

test "$(docker inspect --format '{{.State.Health.Status}}' "$container")" = "healthy"
docker exec --user appuser "$container" /home/appuser/.venv/bin/python -m pip check
docker exec --user appuser "$container" /home/appuser/.venv/bin/python /tmp/verify_runtime.py
