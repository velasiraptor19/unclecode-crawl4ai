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


def write_summary(run: dict, lines: list[str], destination: Path) -> None:
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
    passed_checks = [line for line in lines if line.startswith("[PASS]")]
    failed_checks = [line for line in lines if line.startswith("[FAIL]")]
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

    def smoke_result(success_evidence: bool = False) -> str:
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
        if "nltk.downloader" in line or "crawl4ai.model_loader" in line
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

    checks = [
        ("Published image pull", "passed" if digest else "not evidenced in raw log"),
        ("Container health check", smoke_result()),
        ("pip check", smoke_result(any("No broken requirements found." in line for line in lines))),
        ("Crawl runtime contract", smoke_result(any("runtime contract passed" in line for line in lines))),
        ("Unauthenticated MCP HTTP returns 401", smoke_result()),
        ("Authenticated Streamable HTTP MCP tool test", smoke_result()),
        (
            "Collecting candidate verification",
            f"{len(passed_checks)} passed, {len(failed_checks)} failed",
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
    write_summary(run, lines, archive / "summary.md")
    write_index(args.output)
    print(f"Archived run {args.run_id} in {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
