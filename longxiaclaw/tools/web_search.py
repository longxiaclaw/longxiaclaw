"""DuckDuckGo web search tool."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class WebSearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ...


class DuckDuckGoSearch(WebSearchProvider):
    """Uses duckduckgo-search library. No API key needed.
    Runs DDGS().text() in executor to avoid blocking the event loop."""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, self._sync_search, query, max_results
        )
        return results

    def _sync_search(self, query: str, max_results: int) -> list[SearchResult]:
        from ddgs import DDGS

        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                )
                for r in raw
            ]


def format_search_results(results: list[SearchResult]) -> str:
    """Format as XML context block for prompt injection."""
    if not results:
        return "<web_search_results>\n  <no_results/>\n</web_search_results>"

    lines = ["<web_search_results>"]
    for r in results:
        # Escape basic XML chars in content
        title = _escape_xml(r.title)
        url = _escape_xml(r.url)
        snippet = _escape_xml(r.snippet)
        lines.append(f'  <result title="{title}" url="{url}">{snippet}</result>')
    lines.append("</web_search_results>")
    return "\n".join(lines)


def _escape_xml(text: str) -> str:
    """Minimal XML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
