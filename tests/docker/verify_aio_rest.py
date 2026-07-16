"""Collecting REST contract for the AIO search and Camoufox endpoints."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


BASE_URL = "http://127.0.0.1:11235"
TOKEN = os.environ["CRAWL4AI_API_TOKEN"]


def request(
    path: str,
    body: dict | None = None,
    timeout: int = 90,
    expected_status: int = 200,
) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method="GET" if body is None else "POST",
    )
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        content_type = response.headers.get_content_type()
        raw_body = response.read()
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = raw_body.decode("utf-8", errors="replace")
        assert response.status == expected_status, (path, response.status, payload)
        assert content_type == "application/json", (path, content_type, payload)
    assert isinstance(payload, dict), f"{path} returned {type(payload).__name__}"
    return payload


def main() -> None:
    passed = []
    failures = []

    def check(name, operation):
        try:
            operation()
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        else:
            passed.append(name)
            print(f"[PASS] {name}")

    def search():
        payload = request("/web/search", {"query": "Crawl4AI", "max_results": 5})
        assert payload["result_count"] > 0
        assert payload["results"][0]["url"].startswith(("http://", "https://"))

    def markdown():
        payload = request("/md", {"url": "https://example.com", "f": "raw"})
        assert payload["success"] is True and "Example Domain" in payload["markdown"]

    def html():
        payload = request("/html", {"url": "https://example.com"})
        assert payload["success"] is True and "Example Domain" in payload["html"]

    def screenshot():
        payload = request(
            "/screenshot",
            {"url": "https://example.com", "screenshot_wait_for": 0},
        )
        assert payload["success"] is True and payload["mime"] == "image/png"
        assert payload["artifact_id"] and payload["size"] > 0

    def pdf():
        payload = request("/pdf", {"url": "https://example.com"})
        assert payload["success"] is True and payload["mime"] == "application/pdf"
        assert payload["artifact_id"] and payload["size"] > 0

    def execute_js_policy():
        payload = request(
            "/execute_js",
            {"url": "https://example.com", "scripts": ["() => document.title"]},
            expected_status=403,
        )
        assert "disabled" in payload["detail"]

    def crawl():
        payload = request(
            "/crawl",
            {"urls": ["https://example.com"], "browser_config": {}, "crawler_config": {}},
        )
        assert payload["results"][0]["success"] is True

    def ask():
        query = urllib.parse.urlencode(
            {"context_type": "doc", "query": "AsyncWebCrawler", "max_results": 3}
        )
        payload = request(f"/ask?{query}")
        assert payload.get("doc_results")

    def status():
        payload = request("/camoufox/status")
        assert payload["package_version"] == "0.6.0"
        assert payload["browser_present"] is True

    def read():
        payload = request(
            "/camoufox/read",
            {"url": "https://example.com", "max_chars": 5000, "timeout_seconds": 60},
        )
        assert payload["success"] is True and payload["browser"] == "camoufox"
        assert "Example Domain" in payload["text"]

    def capture():
        payload = request(
            "/camoufox/capture",
            {"url": "https://example.com", "wait_seconds": 0, "timeout_seconds": 60},
        )
        assert payload["success"] is True and payload["browser"] == "camoufox"
        assert payload["mime"] == "image/png" and payload["size"] > 0

    for name, operation in (
        ("markdown_rest", markdown),
        ("html_rest", html),
        ("screenshot_rest", screenshot),
        ("pdf_rest", pdf),
        ("execute_js_default_policy_rest", execute_js_policy),
        ("crawl_rest", crawl),
        ("ask_rest", ask),
        ("web_search_rest", search),
        ("camoufox_status_rest", status),
        ("camoufox_read_rest", read),
        ("camoufox_capture_rest", capture),
    ):
        check(name, operation)

    print(f"AIO REST contract summary: {len(passed)} passed, {len(failures)} failed")
    if failures:
        raise AssertionError("AIO REST contract failures:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
