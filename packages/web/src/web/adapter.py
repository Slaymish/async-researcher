"""Search + fetch adapters. ADR-0018.

search(query, k) -> list[SearchHit]  — SearXNG primary, DDGS fallback
fetch(url)       -> MarkdownDoc      — curl_cffi fast path, Crawl4AI fallback

SearXNG must be running locally (Docker) with JSON output mode enabled.
When `searxng_url` is None, only DDGS is used.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str


@dataclass(frozen=True)
class MarkdownDoc:
    url: str
    content: str  # cleaned Markdown; empty string when fetch fails entirely


class WebAdapter:
    def __init__(
        self,
        *,
        searxng_url: str | None = None,
        fetch_timeout_s: float = 30.0,
        max_fetch_urls: int = 5,
    ) -> None:
        self._searxng_url = searxng_url
        self._fetch_timeout_s = fetch_timeout_s
        self.max_fetch_urls = max_fetch_urls

    # ── search ────────────────────────────────────────────────────────────────

    async def search(self, query: str, k: int = 10) -> list[SearchHit]:
        """Return up to k search hits. SearXNG when configured, DDGS otherwise."""
        if self._searxng_url:
            try:
                return await self._search_searxng(query, k)
            except Exception:
                log.warning("SearXNG search failed, falling back to DDGS")
        return await self._search_ddgs(query, k)

    async def _search_searxng(self, query: str, k: int) -> list[SearchHit]:
        import httpx

        params = {"q": query, "format": "json", "categories": "general"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self._searxng_url}/search", params=params)
            r.raise_for_status()
            data = r.json()
        return [
            SearchHit(
                url=result.get("url", ""),
                title=result.get("title", ""),
                snippet=result.get("content", ""),
            )
            for result in data.get("results", [])[:k]
        ]

    async def _search_ddgs(self, query: str, k: int) -> list[SearchHit]:
        from ddgs import DDGS

        def _sync() -> list[dict]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=k))

        results = await asyncio.get_running_loop().run_in_executor(None, _sync)
        return [
            SearchHit(
                url=r.get("href", ""),
                title=r.get("title", ""),
                snippet=r.get("body", ""),
            )
            for r in results
        ]

    # ── fetch ─────────────────────────────────────────────────────────────────

    async def fetch(self, url: str) -> MarkdownDoc:
        """Fetch a URL as Markdown. curl_cffi fast path, Crawl4AI on 403/empty body."""
        try:
            doc = await self._fetch_curl_cffi(url)
            if doc.content.strip():
                return doc
            log.debug("curl_cffi returned empty body for %s, trying Crawl4AI", url)
        except Exception as exc:
            log.debug("curl_cffi failed for %s (%s), trying Crawl4AI", url, exc)
        try:
            return await self._fetch_crawl4ai(url)
        except Exception as exc:
            log.warning("Crawl4AI fetch failed for %s: %s", url, exc)
            return MarkdownDoc(url=url, content="")

    async def _fetch_curl_cffi(self, url: str) -> MarkdownDoc:
        import html2text
        from curl_cffi.requests import AsyncSession

        async with AsyncSession(impersonate="chrome124") as session:
            r = await session.get(url, timeout=self._fetch_timeout_s)
        if r.status_code == 403:
            raise RuntimeError(f"403 Forbidden from {url}")
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0
        content = h.handle(r.text)
        return MarkdownDoc(url=url, content=content)

    async def _fetch_crawl4ai(self, url: str) -> MarkdownDoc:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

        browser_cfg = BrowserConfig(headless=True)
        run_cfg = CrawlerRunConfig()
        # stealth_mode available in crawl4ai >= 0.4; skip gracefully if absent
        try:
            run_cfg = CrawlerRunConfig(stealth_mode=True)  # type: ignore[call-arg]
        except TypeError:
            pass

        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)
        # markdown attribute varies by crawl4ai version
        md = getattr(result, "markdown", None)
        if md is None:
            content = ""
        elif hasattr(md, "raw_markdown"):
            content = md.raw_markdown or ""
        else:
            content = str(md)
        return MarkdownDoc(url=url, content=content)
