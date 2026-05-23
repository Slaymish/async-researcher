"""Web access — search (SearXNG + DDGS, ADR-0018) and fetch (Crawl4AI + curl_cffi).

Web-sourced content is indexed in DuckDB with a `web://` relpath prefix (ADR-0019).
Chunking and indexing live in the orchestrator's web executor, not here — this
package is the adapter layer only.
"""

from .adapter import MarkdownDoc, SearchHit, WebAdapter

__all__ = ["MarkdownDoc", "SearchHit", "WebAdapter"]
