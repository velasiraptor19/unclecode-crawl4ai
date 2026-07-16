#!/usr/bin/env bash
set -uo pipefail

image="${1:?usage: smoke-test.sh IMAGE_REF}"
container="crawl4ai-smoke-${GITHUB_RUN_ID:-local}"
mcp_token="crawl4ai-mcp-smoke-${GITHUB_RUN_ID:-local}"
artifact_dir="${SMOKE_ARTIFACT_DIR:-/tmp/crawl4ai-smoke-${GITHUB_RUN_ID:-local}}"
report_path="${artifact_dir}/report.md"
mkdir -p "${artifact_dir}"

declare -a check_names=()
declare -a check_statuses=()
declare -a check_codes=()
failure_count=0

cleanup() {
    docker rm -f "${container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

record_result() {
    check_names+=("$1")
    check_statuses+=("$2")
    check_codes+=("$3")
    if [[ "$2" == "FAIL" ]]; then
        failure_count=$((failure_count + 1))
    fi
}

run_check() {
    local name="$1"
    shift
    echo "::group::${name}"
    "$@" 2>&1 | tee "${artifact_dir}/${name}.log"
    local status=${PIPESTATUS[0]}
    if (( status == 0 )); then
        record_result "${name}" "PASS" "0"
        echo "[PASS] ${name}"
    else
        record_result "${name}" "FAIL" "${status}"
        echo "[FAIL] ${name} (exit ${status})"
    fi
    echo "::endgroup::"
}

write_report() {
    {
        echo "# Crawl4AI AIO Candidate Verification"
        echo
        echo "- Image: \`${image}\`"
        echo "- Checks: ${#check_names[@]}"
        echo "- Failures: ${failure_count}"
        echo
        echo "| Check | Result | Exit |"
        echo "|---|---:|---:|"
        local index
        for index in "${!check_names[@]}"; do
            echo "| \`${check_names[$index]}\` | ${check_statuses[$index]} | ${check_codes[$index]} |"
        done
    } > "${report_path}"
    cat "${report_path}"
}

capture_container_evidence() {
    docker logs "${container}" > "${artifact_dir}/container.log" 2>&1 || true
    docker inspect "${container}" > "${artifact_dir}/container-inspect.json" 2>&1 || true
}

fatal_prerequisite() {
    record_result "$1" "FAIL" "$2"
    capture_container_evidence
    write_report
    exit 1
}

wait_for_health() {
    local health=""
    local state=""
    local attempt
    for attempt in $(seq 1 60); do
        state="$(docker inspect --format '{{.State.Status}}' "${container}" 2>/dev/null || true)"
        health="$(docker inspect --format '{{.State.Health.Status}}' "${container}" 2>/dev/null || true)"
        if [[ "${health}" == "healthy" ]]; then
            return 0
        fi
        if [[ "${state}" != "running" || "${health}" == "unhealthy" ]]; then
            return 1
        fi
        sleep 2
    done
    return 1
}

check_mcp_auth_gate() {
    local status
    status="$(docker exec "${container}" curl -s -o /dev/null -w '%{http_code}' \
        http://127.0.0.1:11235/mcp/http)"
    [[ "${status}" == "401" ]]
}

check_novnc() {
    docker exec "${container}" curl -fsS http://127.0.0.1:6080/vnc.html >/dev/null
}

docker pull "${image}" 2>&1 | tee "${artifact_dir}/image_pull.log"
pull_status=${PIPESTATUS[0]}
if (( pull_status != 0 )); then
    fatal_prerequisite "image_pull" "${pull_status}"
fi
record_result "image_pull" "PASS" "0"

docker run --detach --name "${container}" --shm-size=1g \
    --env "CRAWL4AI_API_TOKEN=${mcp_token}" \
    --mount "type=bind,src=${PWD}/tests/docker/verify_runtime.py,dst=/tmp/verify_runtime.py,readonly" \
    --mount "type=bind,src=${PWD}/tests/docker/verify_searxng.py,dst=/tmp/verify_searxng.py,readonly" \
    --mount "type=bind,src=${PWD}/tests/docker/verify_aio_rest.py,dst=/tmp/verify_aio_rest.py,readonly" \
    --mount "type=bind,src=${PWD}/tests/docker/verify_ownership.py,dst=/tmp/verify_ownership.py,readonly" \
    --mount "type=bind,src=${PWD}/tests/mcp/test_mcp_http.py,dst=/tmp/test_mcp_http.py,readonly" \
    "${image}" 2>&1 | tee "${artifact_dir}/container_start.log"
start_status=${PIPESTATUS[0]}
if (( start_status != 0 )); then
    fatal_prerequisite "container_start" "${start_status}"
fi
record_result "container_start" "PASS" "0"

run_check "container_health" wait_for_health
run_check "pip_check" docker exec --user appuser "${container}" \
    /home/appuser/.venv/bin/python -m pip check
run_check "ownership_contract" docker exec --user appuser "${container}" \
    /home/appuser/.venv/bin/python /tmp/verify_ownership.py
run_check "runtime_contract" docker exec --user appuser "${container}" \
    /home/appuser/.venv/bin/python /tmp/verify_runtime.py
run_check "searxng_contract" docker exec --user appuser "${container}" \
    /home/appuser/.venv/bin/python /tmp/verify_searxng.py
run_check "aio_rest_contract" docker exec --user appuser \
    --env "CRAWL4AI_API_TOKEN=${mcp_token}" "${container}" \
    /home/appuser/.venv/bin/python /tmp/verify_aio_rest.py
run_check "mcp_auth_gate" check_mcp_auth_gate
run_check "novnc_contract" check_novnc
run_check "mcp_http_contract" docker exec --user appuser \
    --env "CRAWL4AI_API_TOKEN=${mcp_token}" \
    --env "CRAWL4AI_MCP_HTTP_URL=http://127.0.0.1:11235/mcp/http" \
    "${container}" /home/appuser/.venv/bin/python /tmp/test_mcp_http.py

capture_container_evidence
write_report

if (( failure_count > 0 )); then
    echo "Candidate verification completed with ${failure_count} failed checks." >&2
    exit 1
fi

echo "Candidate verification passed all ${#check_names[@]} checks."
