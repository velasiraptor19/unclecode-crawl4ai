"""Runtime contract for the SearXNG service embedded in the AIO image."""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = "http://127.0.0.1:8080"
SEARXNG_ROOT = Path("/usr/local/searxng")


def get(path: str, timeout: int = 20) -> tuple[int, bytes, str]:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as response:
        return response.status, response.read(), response.headers.get_content_type()


def main() -> None:
    # Supervisor starts Granian with directory=/usr/local/searxng. This verifier
    # is bind-mounted under /tmp, so reproduce that source-root import context.
    assert (SEARXNG_ROOT / "searx" / "__init__.py").is_file(), "SearXNG source missing"
    sys.path.insert(0, str(SEARXNG_ROOT))
    import searx  # noqa: F401

    assert not (SEARXNG_ROOT / ".venv").exists(), "upstream SearXNG venv was copied"

    status, body, _ = get("/healthz")
    assert status == 200 and body.strip() == b"OK"

    status, body, content_type = get("/config")
    config = json.loads(body)
    assert status == 200 and content_type == "application/json"
    assert config.get("instance_name") == "Crawl4AI AIO Search"

    failures = []
    for engine in ("brave", "duckduckgo"):
        query = urllib.parse.urlencode(
            {"q": "OpenAI", "format": "json", "engines": engine, "language": "en"}
        )
        try:
            status, body, content_type = get(f"/search?{query}", timeout=45)
            result = json.loads(body)
            assert status == 200 and content_type == "application/json"
            assert result.get("results"), result
            assert all(item.get("url") and item.get("title") for item in result["results"])
            assert not result.get("unresponsive_engines"), result.get("unresponsive_engines")
        except Exception as exc:  # The next independent engine remains a real network test.
            failures.append(f"{engine}: {exc}")
            continue
        print(f"SearXNG runtime contract passed via {engine} with {len(result['results'])} results")
        break
    else:
        raise AssertionError(f"all real SearXNG engine checks failed: {failures}")


if __name__ == "__main__":
    main()
