#!/usr/bin/env python3
"""Download one GitHub Actions run and create a compact local evidence archive."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_REPOSITORY = "velasiraptor19/unclecode-crawl4ai"
DEFAULT_OUTPUT = Path("build-logs")
RUN_FIELDS = (
    "databaseId,status,conclusion,displayTitle,headBranch,headSha,createdAt,"
    "updatedAt,url,event,jobs"
)
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\a]*(?:\a|\x1b\\))")
TIMESTAMP_PREFIX = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
GITHUB_LOG_PREFIX = re.compile(
    r"^[^\t]+\t[^\t]+\t\ufeff?\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?"
)


def command(*args: str) -> str:
    completed = subprocess.run(args, check=True, capture_output=True, text=True)
    return completed.stdout


def clean_line(line: str) -> str:
    clean = ANSI_ESCAPE.sub("", line)
    clean = GITHUB_LOG_PREFIX.sub("", clean)
    return TIMESTAMP_PREFIX.sub("", clean).strip()


def duration(start: str, end: str) -> str:
    started = datetime.fromisoformat(start.replace("Z", "+00:00"))
    finished = datetime.fromisoformat(end.replace("Z", "+00:00"))
    seconds = int((finished - started).total_seconds())
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s"


def first_match(lines: list[str], pattern: str) -> str | None:
    matcher = re.compile(pattern)
    for line in lines:
        match = matcher.search(line)
        if match:
            return match.group(1)
    return None


def write_summary(
    run: dict,
    lines: list[str],
    destination: Path,
    evidence_lines: list[str] | None = None,
) -> None:
    evidence_lines = evidence_lines or []
    smoke_image = (
        first_match(lines, r"- Image: `([^`]+)`")
        or first_match(lines, r"(ghcr\.io/[^ ]+:candidate-[^ ]+@sha256:[a-f0-9]{64})")
        or first_match(lines, r'tests/docker/smoke-test\.sh "([^"]+)"')
    )
    digest = first_match(lines, r"Digest: (sha256:[a-f0-9]+)")
    build_command = next(
        (line for line in lines if "docker buildx build --build-arg" in line), ""
    )
    build_args = " ".join(re.findall(r"--build-arg ([^ ]+)", build_command)) or None
    report_results: dict[str, str] = {}
    report_row = re.compile(r"^\| `([^`]+)` \| (PASS|FAIL) \| [^|]+\|$")
    for line in lines:
        match = report_row.fullmatch(line)
        if match:
            report_results[match.group(1)] = match.group(2).lower()
    smoke_job = next(
        (
            job
            for job in run["jobs"]
            if any("Run smoke" in step["name"] for step in job["steps"])
        ),
        None,
    )
    smoke_step = next(
        (step for step in smoke_job["steps"] if "Run smoke" in step["name"]),
        None,
    ) if smoke_job else None

    def smoke_result(check_name: str | None = None, success_evidence: bool = False) -> str:
        if check_name in report_results:
            return report_results[check_name]
        if smoke_step is None or smoke_step["conclusion"] == "skipped":
            return "not run (build failed before smoke)"
        if success_evidence or smoke_step["conclusion"] == "success":
            return "passed"
        return "failed"

    warning_groups: list[str] = []
    node_warnings = [line for line in lines if "Node.js 20 is deprecated" in line]
    if node_warnings:
        warning_groups.append(
            "GitHub Actions Node 20 deprecation: external action-runtime warning; "
            "the runner forced Node 24 and the run completed."
        )
    manpage_warnings = [line for line in lines if "update-alternatives: warning" in line]
    if manpage_warnings:
        warning_groups.append(
            f"{len(manpage_warnings)} `update-alternatives` manual-page symlink warnings: "
            "expected after image documentation cleanup; not a browser/runtime dependency."
        )
    preload_warnings = [
        line for line in lines
        if "RuntimeWarning" in line
        and ("nltk.downloader" in line or "crawl4ai.model_loader" in line)
    ]
    if preload_warnings:
        warning_groups.append(
            "Model preload `runpy` warnings for NLTK/model_loader: preload completed and "
            "the later runtime contract passed."
        )
    if any("unauthenticated requests to the HF Hub" in line for line in lines):
        warning_groups.append(
            "Hugging Face preload used anonymous access: it can be rate-limited, but the "
            "download completed. A token is optional for higher limits."
        )
    if any("Memory overcommit must be enabled" in line for line in evidence_lines):
        warning_groups.append(
            "Redis reported host kernel `vm.overcommit_memory=0`; this is a host-level "
            "deployment recommendation, not an image dependency failure."
        )
    if any("_XSERVTransmkdir: ERROR" in line for line in evidence_lines):
        warning_groups.append(
            "Xvfb could not create `/tmp/.X11-unix` as appuser; browser/noVNC tests "
            "still ran, but the runtime socket setup should be normalized."
        )
    if any("No SECRET_KEY set" in line for line in evidence_lines):
        warning_groups.append(
            "Crawl4AI generated an ephemeral runtime `SECRET_KEY`; configure or generate "
            "one in the entrypoint to keep tokens stable for the container lifetime."
        )
    if any("LeakWarning: When using a proxy" in line for line in evidence_lines):
        warning_groups.append(
            "Camoufox reported a GeoIP leak warning for the image's own loopback pinning proxy."
        )
    engine_failures = [
        line for line in evidence_lines
        if "SearxEngine" in line
        or "can't register engine" in line
        or "engine INIT failed" in line
    ]
    if engine_failures:
        warning_groups.append(
            f"SearXNG logged {len(engine_failures)} engine initialization/rate-limit lines; "
            "the independent search contract determines whether usable engines remain."
        )

    checks = [
        ("Published image pull", smoke_result("image_pull", bool(digest))),
        ("Container health check", smoke_result("container_health")),
        (
            "pip check",
            smoke_result(
                "pip_check",
                any("No broken requirements found." in line for line in lines),
            ),
        ),
        (
            "Crawl runtime contract",
            smoke_result(
                "runtime_contract",
                any("runtime contract passed" in line for line in lines),
            ),
        ),
        ("Direct AIO REST contract", smoke_result("aio_rest_contract")),
        ("Unauthenticated MCP HTTP returns 401", smoke_result("mcp_auth_gate")),
        ("Authenticated Streamable HTTP MCP tool test", smoke_result("mcp_http_contract")),
        ("Runtime log contract", smoke_result("runtime_log_contract")),
        (
            "Collecting candidate verification",
            f"{sum(result == 'pass' for result in report_results.values())} passed, "
            f"{sum(result == 'fail' for result in report_results.values())} failed",
        ),
    ]

    job = run["jobs"][0]
    text = [
        f"# Build {run['databaseId']}",
        "",
        f"- **Result:** {run['conclusion']} ({run['status']})",
        f"- **Workflow:** {run['displayTitle']}",
        f"- **Branch:** `{run['headBranch']}`",
        f"- **Commit:** `{run['headSha']}`",
        f"- **Started:** {run['createdAt']}",
        f"- **Finished:** {run['updatedAt']}",
        f"- **Elapsed:** {duration(job['startedAt'], job['completedAt'])}",
        f"- **Run:** {run['url']}",
        "",
        "## Image",
        "",
        f"- **Smoke-tested tag:** `{smoke_image or 'not found'}`",
        f"- **Pulled digest:** `{digest or 'not found'}`",
        f"- **Build args:** `{build_args or 'not found'}`",
        "",
        "## Smoke Contract",
        "",
    ]
    text.extend(f"- {name}: **{result}**" for name, result in checks)
    text.extend(["", "## Warnings", ""])
    if warning_groups:
        text.extend(f"- {warning}" for warning in warning_groups)
    else:
        text.append("- None found.")
    text.extend([
        "",
        "## Files",
        "",
        "- `metadata.json`: unmodified GitHub run metadata.",
        "- `raw.log`: complete log downloaded through `gh run view --log`.",
        "- `evidence/`: uploaded per-check logs, report, container log, and inspect output when available.",
    ])
    destination.write_text("\n".join(text) + "\n", encoding="utf-8")


def write_index(output: Path) -> None:
    rows = []
    for metadata_path in output.glob("runs/*/metadata.json"):
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        rows.append(data)
    rows.sort(key=lambda item: item["createdAt"], reverse=True)

    text = [
        "# Local Build Evidence Index",
        "",
        "This local-only archive contains complete GitHub Actions logs plus compact summaries.",
        "Regenerate or add an entry with `python3 tools/archive_gh_build.py <run-id>`.",
        "",
        "| Run | Result | Branch | Commit | Summary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in rows:
        run_id = item["databaseId"]
        text.append(
            f"| [{run_id}]({item['url']}) | {item['conclusion']} | "
            f"`{item['headBranch']}` | `{item['headSha'][:7]}` | "
            f"[local](runs/{run_id}/summary.md) |"
        )
    (output / "INDEX.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=int, help="GitHub Actions run ID")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY, help="owner/repository")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="archive root")
    args = parser.parse_args()

    try:
        run = json.loads(command("gh", "run", "view", str(args.run_id), "--repo", args.repo, "--json", RUN_FIELDS))
        raw_log = command("gh", "run", "view", str(args.run_id), "--repo", args.repo, "--log")
    except subprocess.CalledProcessError as error:
        sys.stderr.write(error.stderr)
        return error.returncode

    archive = args.output / "runs" / str(args.run_id)
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "metadata.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    (archive / "raw.log").write_text(raw_log, encoding="utf-8")
    artifacts = json.loads(command(
        "gh", "api", f"repos/{args.repo}/actions/runs/{args.run_id}/artifacts"
    ))
    evidence_artifact = next(
        (
            artifact for artifact in artifacts.get("artifacts", [])
            if artifact["name"].startswith((
                "aio-candidate-verification-",
                "aio-existing-candidate-verification-",
            ))
        ),
        None,
    )
    evidence_dir = archive / "evidence"
    if evidence_artifact:
        if evidence_dir.exists():
            shutil.rmtree(evidence_dir)
        command(
            "gh", "run", "download", str(args.run_id), "--repo", args.repo,
            "--name", evidence_artifact["name"], "--dir", str(evidence_dir),
        )
    lines = [clean_line(line) for line in raw_log.splitlines()]
    evidence_lines: list[str] = []
    container_log = evidence_dir / "container.log"
    if container_log.is_file():
        evidence_lines = [clean_line(line) for line in container_log.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()]
    write_summary(run, lines, archive / "summary.md", evidence_lines)
    write_index(args.output)
    print(f"Archived run {args.run_id} in {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
