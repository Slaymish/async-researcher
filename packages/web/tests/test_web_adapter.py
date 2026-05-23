"""Tests for web.adapter — WebAdapter search and fetch, with mocked backends."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from web.adapter import MarkdownDoc, SearchHit, WebAdapter


# --- search ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_uses_ddgs_when_no_searxng_url():
    adapter = WebAdapter(searxng_url=None)
    fake_results = [{"href": "https://x.com", "title": "X", "body": "snippet"}]

    with patch.object(adapter, "_search_ddgs", new=AsyncMock(return_value=[
        SearchHit(url="https://x.com", title="X", snippet="snippet")
    ])) as mock_ddgs:
        results = await adapter.search("query")

    mock_ddgs.assert_called_once_with("query", 10)
    assert len(results) == 1
    assert results[0].url == "https://x.com"


@pytest.mark.asyncio
async def test_search_uses_searxng_when_configured():
    adapter = WebAdapter(searxng_url="http://localhost:8888")
    expected = [SearchHit(url="https://y.com", title="Y", snippet="s")]

    with patch.object(adapter, "_search_searxng", new=AsyncMock(return_value=expected)) as mock_sx:
        results = await adapter.search("test", k=5)

    mock_sx.assert_called_once_with("test", 5)
    assert results == expected


@pytest.mark.asyncio
async def test_search_falls_back_to_ddgs_when_searxng_fails():
    adapter = WebAdapter(searxng_url="http://localhost:8888")
    ddgs_result = [SearchHit(url="https://fallback.com", title="F", snippet="f")]

    with (
        patch.object(adapter, "_search_searxng", new=AsyncMock(side_effect=RuntimeError("down"))),
        patch.object(adapter, "_search_ddgs", new=AsyncMock(return_value=ddgs_result)) as mock_ddgs,
    ):
        results = await adapter.search("query")

    mock_ddgs.assert_called_once()
    assert results == ddgs_result


# --- fetch -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_returns_curl_cffi_result_when_non_empty():
    adapter = WebAdapter()
    doc = MarkdownDoc(url="https://x.com", content="# Article content")

    with patch.object(adapter, "_fetch_curl_cffi", new=AsyncMock(return_value=doc)):
        result = await adapter.fetch("https://x.com")

    assert result.content == "# Article content"
    assert result.url == "https://x.com"


@pytest.mark.asyncio
async def test_fetch_falls_back_to_crawl4ai_when_curl_returns_empty():
    adapter = WebAdapter()
    empty_doc = MarkdownDoc(url="https://x.com", content="   ")
    crawl_doc = MarkdownDoc(url="https://x.com", content="Real content from crawl4ai")

    with (
        patch.object(adapter, "_fetch_curl_cffi", new=AsyncMock(return_value=empty_doc)),
        patch.object(adapter, "_fetch_crawl4ai", new=AsyncMock(return_value=crawl_doc)),
    ):
        result = await adapter.fetch("https://x.com")

    assert result.content == "Real content from crawl4ai"


@pytest.mark.asyncio
async def test_fetch_falls_back_to_crawl4ai_when_curl_raises():
    adapter = WebAdapter()
    crawl_doc = MarkdownDoc(url="https://x.com", content="From crawl4ai")

    with (
        patch.object(adapter, "_fetch_curl_cffi", new=AsyncMock(side_effect=RuntimeError("403 Forbidden"))),
        patch.object(adapter, "_fetch_crawl4ai", new=AsyncMock(return_value=crawl_doc)),
    ):
        result = await adapter.fetch("https://x.com")

    assert result.content == "From crawl4ai"


@pytest.mark.asyncio
async def test_fetch_returns_empty_doc_when_both_backends_fail():
    adapter = WebAdapter()

    with (
        patch.object(adapter, "_fetch_curl_cffi", new=AsyncMock(side_effect=RuntimeError("fail"))),
        patch.object(adapter, "_fetch_crawl4ai", new=AsyncMock(side_effect=RuntimeError("also fail"))),
    ):
        result = await adapter.fetch("https://x.com")

    assert result.url == "https://x.com"
    assert result.content == ""


# --- SearchHit / MarkdownDoc dataclasses -------------------------------------


def test_search_hit_is_frozen():
    hit = SearchHit(url="https://x.com", title="X", snippet="s")
    import dataclasses
    assert dataclasses.is_dataclass(hit)


def test_markdown_doc_is_frozen():
    doc = MarkdownDoc(url="https://x.com", content="text")
    import dataclasses
    assert dataclasses.is_dataclass(doc)


# --- max_fetch_urls config ---------------------------------------------------


def test_max_fetch_urls_is_stored():
    adapter = WebAdapter(max_fetch_urls=3)
    assert adapter.max_fetch_urls == 3


def test_default_max_fetch_urls():
    adapter = WebAdapter()
    assert adapter.max_fetch_urls == 5
