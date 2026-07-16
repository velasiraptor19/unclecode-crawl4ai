"""Focused writable-runtime ownership contract for the published image."""

import os
from pathlib import Path


EXPECTED_ID = 999
HOME = Path("/home/appuser")
RUNTIME_DIR = HOME / ".crawl4ai"


def main() -> None:
    assert os.getuid() == EXPECTED_ID, f"appuser UID must be {EXPECTED_ID}"
    assert os.getgid() == EXPECTED_ID, f"appuser GID must be {EXPECTED_ID}"
    assert HOME.stat().st_uid == EXPECTED_ID
    assert HOME.stat().st_gid == EXPECTED_ID
    assert RUNTIME_DIR.stat().st_uid == EXPECTED_ID
    assert RUNTIME_DIR.stat().st_gid == EXPECTED_ID

    probe = RUNTIME_DIR / ".ownership-contract"
    probe.write_text("writable\n", encoding="ascii")
    probe.unlink()
    print("ownership contract passed")


if __name__ == "__main__":
    main()
