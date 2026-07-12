# Build Log Archive

`tools/archive_gh_build.py` keeps complete GitHub Actions build evidence locally without adding large, generated logs to Git history.

For each run, it creates `runs/<run-id>/` with the unmodified Actions log, GitHub metadata, and a concise result summary. `INDEX.md` is regenerated so the newest run and its tested image are visible immediately.

```bash
python3 tools/archive_gh_build.py <run-id>
```

The command uses `gh run view --log`; it does not rebuild or pull an image. GitHub retains the canonical Action run, while this archive keeps the full local evidence needed for later comparison and PR preparation.
