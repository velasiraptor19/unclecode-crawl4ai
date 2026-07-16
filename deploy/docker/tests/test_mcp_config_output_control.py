"""Contracts adapted from upstream PRs #1965 and #1674."""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError


def test_output_control_is_bounded_and_rejects_unknown_fields():
    from schemas import OutputControl

    with pytest.raises(ValidationError):
        OutputControl(content_limit=200_001)
    with pytest.raises(ValidationError):
        OutputControl(exclude_fields=["__class__"])
    with pytest.raises(ValidationError):
        OutputControl(unexpected=True)


def test_output_control_pages_without_deep_copying_untouched_payloads():
    from output_control import apply_output_control
    from schemas import OutputControl

    untouched = [{"large": "object"}]
    source = {
        "html": "abcdefghij",
        "markdown": {"raw_markdown": "0123456789", "references_markdown": "refs"},
        "links": {"internal": [{"n": 1}, {"n": 2}], "external": []},
        "metadata": untouched,
    }
    result = apply_output_control(
        source,
        OutputControl(
            content_offset=2,
            content_limit=4,
            max_links=1,
            exclude_fields=["markdown.references_markdown"],
        ),
    )

    assert result["html"] == "cdef"
    assert result["markdown"]["raw_markdown"] == "2345"
    assert "references_markdown" not in result["markdown"]
    assert len(result["links"]["internal"]) == 1
    assert result["metadata"] is untouched
    assert source["html"] == "abcdefghij"
    assert len(source["links"]["internal"]) == 2
    assert result["_output_meta"]["content_stats"]["html"]["next_offset"] == 6


def test_no_output_control_preserves_object_identity():
    from output_control import apply_output_control

    source = {"html": "unchanged"}
    assert apply_output_control(source, None) is source


def test_all_narrow_mcp_models_expose_both_contracts():
    from schemas import (
        HTMLRequest,
        JSEndpointRequest,
        MarkdownRequest,
        PDFRequest,
        ScreenshotRequest,
    )

    for model in (MarkdownRequest, HTMLRequest, ScreenshotRequest, PDFRequest, JSEndpointRequest):
        properties = model.model_json_schema()["properties"]
        assert "crawler_config" in properties
        assert "output_control" in properties


def test_untrusted_loader_rejects_power_fields(server_module):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        server_module._load_untrusted_crawler_config({
            "deep_crawl_strategy": {
                "type": "BFSDeepCrawlStrategy",
                "params": {"max_depth": 50},
            }
        })
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_html_uses_safe_config_and_returns_bounded_output(monkeypatch, server_module):
    result = type("Result", (), {
        "success": True,
        "html": "<html><body>abcdefghij</body></html>",
        "error_message": "",
    })()
    crawler = type("Crawler", (), {"arun": AsyncMock(return_value=[result])})()
    monkeypatch.setattr(server_module, "get_crawler", AsyncMock(return_value=crawler))
    monkeypatch.setattr(server_module, "release_crawler", AsyncMock())
    monkeypatch.setattr(
        "crawl4ai.utils.preprocess_html_for_schema", lambda value: "abcdefghij"
    )

    from schemas import HTMLRequest, OutputControl

    response = await server_module.generate_html.__wrapped__(
        request=None,
        body=HTMLRequest(
            url="https://example.com",
            crawler_config={"delay_before_return_html": 0.25},
            output_control=OutputControl(content_limit=4),
        ),
        _td={},
    )
    assert b'"html":"abcd"' in response.body
    config_used = crawler.arun.await_args.kwargs["config"]
    assert config_used.delay_before_return_html == 0.25


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "request_name", "forced_field"),
    (("generate_screenshot", "ScreenshotRequest", "screenshot"),
     ("generate_pdf", "PDFRequest", "pdf")),
)
async def test_artifact_handlers_enforce_flags_and_do_not_return_base64(
    monkeypatch, server_module, handler_name, request_name, forced_field
):
    payload = b"binary"
    result = type("Result", (), {
        "success": True,
        "screenshot": "YmluYXJ5",
        "pdf": payload,
        "error_message": "",
    })()
    crawler = type("Crawler", (), {"arun": AsyncMock(return_value=[result])})()
    monkeypatch.setattr(server_module, "get_crawler", AsyncMock(return_value=crawler))
    monkeypatch.setattr(server_module, "release_crawler", AsyncMock())
    monkeypatch.setattr(
        server_module,
        "_store_artifact",
        lambda kind, data: {
            "artifact_id": "a" * 32,
            "url": "/artifacts/" + "a" * 32,
            "mime": "image/png" if kind == "png" else "application/pdf",
            "size": len(data),
        },
    )
    import schemas

    request_model = getattr(schemas, request_name)
    response = await getattr(server_module, handler_name).__wrapped__(
        request=None,
        body=request_model(url="https://example.com", crawler_config={}),
        _td={},
    )
    assert forced_field not in response
    assert response["artifact_id"] == "a" * 32
    config_used = crawler.arun.await_args.kwargs["config"]
    assert getattr(config_used, forced_field) is True
