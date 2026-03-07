"""Tests for web search tool."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from longxiaclaw.tools.web_search import (
    DuckDuckGoSearch,
    SearchResult,
    format_search_results,
    _escape_xml,
)


class TestSearchResult:
    def test_dataclass(self):
        r = SearchResult(title="Test", url="https://example.com", snippet="A test result")
        assert r.title == "Test"
        assert r.url == "https://example.com"
        assert r.snippet == "A test result"


class TestFormatSearchResults:
    def test_format_with_results(self):
        results = [
            SearchResult(title="Python", url="https://python.org", snippet="Python language"),
            SearchResult(title="Rust", url="https://rust-lang.org", snippet="Rust language"),
        ]
        formatted = format_search_results(results)
        assert "<web_search_results>" in formatted
        assert "</web_search_results>" in formatted
        assert 'title="Python"' in formatted
        assert 'url="https://python.org"' in formatted
        assert "Python language" in formatted
        assert 'title="Rust"' in formatted

    def test_format_empty_results(self):
        formatted = format_search_results([])
        assert "<no_results/>" in formatted

    def test_format_escapes_xml(self):
        results = [
            SearchResult(
                title='Test & "Quote"',
                url="https://example.com?a=1&b=2",
                snippet="<script>alert('xss')</script>",
            ),
        ]
        formatted = format_search_results(results)
        assert "&amp;" in formatted
        assert "&lt;script&gt;" in formatted
        assert "&quot;" in formatted


class TestEscapeXml:
    def test_escape_ampersand(self):
        assert _escape_xml("a & b") == "a &amp; b"

    def test_escape_angle_brackets(self):
        assert _escape_xml("<b>") == "&lt;b&gt;"

    def test_escape_quotes(self):
        assert _escape_xml('"hello"') == "&quot;hello&quot;"

    def test_no_escape_needed(self):
        assert _escape_xml("hello world") == "hello world"


class TestDuckDuckGoSearch:
    @pytest.mark.asyncio
    async def test_search_with_mock(self):
        mock_results = [
            {"title": "Result 1", "href": "https://example.com/1", "body": "Snippet 1"},
            {"title": "Result 2", "href": "https://example.com/2", "body": "Snippet 2"},
        ]

        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = mock_results
        mock_ddgs_instance.__enter__ = MagicMock(return_value=mock_ddgs_instance)
        mock_ddgs_instance.__exit__ = MagicMock(return_value=False)

        with patch("longxiaclaw.tools.web_search.DuckDuckGoSearch._sync_search") as mock_sync:
            mock_sync.return_value = [
                SearchResult(title="Result 1", url="https://example.com/1", snippet="Snippet 1"),
                SearchResult(title="Result 2", url="https://example.com/2", snippet="Snippet 2"),
            ]
            search = DuckDuckGoSearch()
            results = await search.search("python programming", max_results=2)

        assert len(results) == 2
        assert results[0].title == "Result 1"
        assert results[1].url == "https://example.com/2"

    def test_sync_search_parsing(self):
        """Test _sync_search result parsing with mocked DDGS."""
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = [
            {"title": "Test", "href": "https://test.com", "body": "Test body"},
        ]
        mock_ddgs_instance.__enter__ = MagicMock(return_value=mock_ddgs_instance)
        mock_ddgs_instance.__exit__ = MagicMock(return_value=False)

        with patch("ddgs.DDGS", return_value=mock_ddgs_instance):
            search = DuckDuckGoSearch()
            results = search._sync_search("test", 5)

        assert len(results) == 1
        assert results[0].title == "Test"
        assert results[0].url == "https://test.com"
        assert results[0].snippet == "Test body"

    @pytest.mark.network
    @pytest.mark.asyncio
    async def test_live_search(self):
        """Live search test - skipped unless --run-network flag is used."""
        search = DuckDuckGoSearch()
        results = await search.search("Python programming language", max_results=3)
        assert len(results) > 0
        assert all(r.title for r in results)
        assert all(r.url for r in results)
