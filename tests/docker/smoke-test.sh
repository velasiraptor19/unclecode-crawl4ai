#!/usr/bin/env bash
set -euo pipefail

image="$1"
container="crawl4ai-smoke-${GITHUB_RUN_ID:-local}"
mcp_token="crawl4ai-mcp-smoke-${GITHUB_RUN_ID:-local}"

cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker pull "$image"
docker run --detach --name "$container" --shm-size=1g \
    --env "CRAWL4AI_API_TOKEN=${mcp_token}" \
    --mount "type=bind,src=${PWD}/tests/docker/verify_runtime.py,dst=/tmp/verify_runtime.py,readonly" \
    --mount "type=bind,src=${PWD}/tests/docker/verify_searxng.py,dst=/tmp/verify_searxng.py,readonly" \
    --mount "type=bind,src=${PWD}/tests/docker/verify_ownership.py,dst=/tmp/verify_ownership.py,readonly" \
    --mount "type=bind,src=${PWD}/tests/mcp/test_mcp_http.py,dst=/tmp/test_mcp_http.py,readonly" \
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
docker exec --user appuser "$container" /home/appuser/.venv/bin/python /tmp/verify_ownership.py
docker exec --user appuser "$container" /home/appuser/.venv/bin/python /tmp/verify_runtime.py
docker exec --user appuser "$container" /home/appuser/.venv/bin/python /tmp/verify_searxng.py
test "$(docker exec "$container" curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:11235/mcp/http)" = "401"
docker exec "$container" curl -fsS http://127.0.0.1:6080/vnc.html >/dev/null
docker exec --user appuser \
    --env "CRAWL4AI_API_TOKEN=${mcp_token}" \
    --env "CRAWL4AI_MCP_HTTP_URL=http://127.0.0.1:11235/mcp/http" \
    "$container" /home/appuser/.venv/bin/python /tmp/test_mcp_http.py
