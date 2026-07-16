"""Bounded response shaping without cloning the complete crawl payload."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from schemas import OutputControl


TEXT_FIELDS = (
    "html", "cleaned_html", "fit_html", "extracted_content", "mhtml", "markdown",
)
MARKDOWN_FIELDS = (
    "raw_markdown", "fit_markdown", "fit_html",
    "markdown_with_citations", "references_markdown",
)


def _page_text(value: str, control: OutputControl) -> tuple[str, Optional[dict]]:
    offset = control.content_offset
    end = None if control.content_limit is None else offset + control.content_limit
    returned = value[offset:end]
    if offset == 0 and len(returned) == len(value):
        return value, None
    next_offset = offset + len(returned)
    return returned, {
        "total_chars": len(value),
        "returned_chars": len(returned),
        "offset": offset,
        "next_offset": next_offset if next_offset < len(value) else None,
        "has_more": next_offset < len(value),
    }


def _limit_collections(data: Dict[str, Any], control: OutputControl, stats: dict) -> None:
    for field, groups, limit in (
        ("links", ("internal", "external"), control.max_links),
        ("media", ("images", "videos", "audios"), control.max_media),
    ):
        value = data.get(field)
        if limit is None or not isinstance(value, dict):
            continue
        copied = value.copy()
        data[field] = copied
        for group in groups:
            items = value.get(group)
            if isinstance(items, list) and len(items) > limit:
                copied[group] = items[:limit]
                stats[f"{field}.{group}"] = {
                    "total_count": len(items), "returned_count": limit,
                }

    tables = data.get("tables")
    if control.max_tables is not None and isinstance(tables, list) and len(tables) > control.max_tables:
        data["tables"] = tables[:control.max_tables]
        stats["tables"] = {
            "total_count": len(tables), "returned_count": control.max_tables,
        }


def apply_output_control(data: Dict[str, Any], control: Optional[OutputControl]) -> Dict[str, Any]:
    """Return a selectively copied, bounded representation of one result."""
    if control is None:
        return data

    result = data.copy()
    excluded = []
    for path in control.exclude_fields:
        if "." not in path:
            if path in result:
                result.pop(path)
                excluded.append(path)
            continue
        parent, child = path.split(".", 1)
        nested = result.get(parent)
        if isinstance(nested, dict) and child in nested:
            nested_copy = nested.copy()
            nested_copy.pop(child)
            result[parent] = nested_copy
            excluded.append(path)

    content_stats: Dict[str, dict] = {}
    for field in TEXT_FIELDS:
        value = result.get(field)
        if isinstance(value, str):
            result[field], stat = _page_text(value, control)
            if stat:
                content_stats[field] = stat

    markdown = result.get("markdown")
    if isinstance(markdown, dict):
        markdown_copy = markdown.copy()
        changed = False
        for field in MARKDOWN_FIELDS:
            value = markdown_copy.get(field)
            if isinstance(value, str):
                markdown_copy[field], stat = _page_text(value, control)
                if stat:
                    content_stats[f"markdown.{field}"] = stat
                    changed = True
        if changed:
            result["markdown"] = markdown_copy

    collection_stats: Dict[str, dict] = {}
    _limit_collections(result, control, collection_stats)
    if excluded or content_stats or collection_stats:
        result["_output_meta"] = {
            "truncated": True,
            "excluded_fields": excluded,
            "content_stats": content_stats,
            "collection_stats": collection_stats,
        }
    return result


def apply_output_control_to_batch(
    results: Iterable[Dict[str, Any]], control: Optional[OutputControl]
) -> list[Dict[str, Any]]:
    return [apply_output_control(result, control) for result in results]
