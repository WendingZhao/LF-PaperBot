from datetime import date
from types import SimpleNamespace
from contextlib import contextmanager
from urllib.error import HTTPError

import pytest

from lf_paperbot import arxiv, arxiv_search as search


RESULT = '''<li class="arxiv-result">
<span class="tag is-link" data-tooltip="Computer Vision">cs.CV</span>
<p class="title is-5 mathjax">Light <span class="search-hit">Field</span> Denoising</p>
<p class="authors"><span>Authors:</span><a>Alice</a>, <a>Bob</a></p>
<p class="abstract"><span class="abstract-short">Truncated...</span>
<span class="abstract-full mathjax" id="2410.12345v2-abstract-full">We restore <span>light fields</span> using EPI.
<a>Less</a></span></p>
<p class="is-size-7"><span>Submitted</span> 5 January, 2025; <span>v1</span> submitted 21 October, 2024;</p>
<a href="https://doi.org/10.1234/lf">DOI</a></li>'''
PAGE = 'Showing 1&ndash;1 of 1 results' + RESULT


def test_official_search_parser_preserves_full_abstract_authors_and_original_date():
    papers, total = search.parse_results(PAGE)
    assert total == 1
    p = papers[0]
    assert p.arxiv_id == "2410.12345v2"
    assert p.published == "2024-10-21"
    assert p.updated == "2025-01-05"
    assert p.abstract == "We restore light fields using EPI."
    assert p.authors == ["Alice", "Bob"]
    assert p.categories == ["cs.CV"]
    assert p.doi == "10.1234/lf"


def test_search_paginates_until_total_and_keeps_partial_results_on_error(monkeypatch):
    urls = []

    @contextmanager
    def response():
        yield SimpleNamespace(read=lambda: ("Showing 1&ndash;1 of 2 results" + RESULT).encode())

    def open_url(request, **_kwargs):
        urls.append(request.full_url)
        if len(urls) == 2:
            raise TimeoutError()
        return response()

    monkeypatch.setattr(search.urllib.request, "urlopen", open_url)
    monkeypatch.setattr(search.time, "sleep", lambda *_: None)
    with pytest.raises(search.PartialSearchError) as caught:
        search.fetch_search_range(SimpleNamespace(arxiv_user_agent="test"), date(2024, 10, 19), date(2024, 10, 31))
    assert len(caught.value.candidates) == 1
    assert "start=1" in urls[1]


def test_unexpected_search_html_is_not_empty_success():
    with pytest.raises(ValueError):
        search.parse_results("<html>Service temporarily unavailable</html>")
    assert search.parse_results("Sorry, your query returned no results") == ([], 0)


def test_historical_api_failure_uses_official_search(monkeypatch):
    monkeypatch.setattr(arxiv, "_fetch_submitted_range_api", lambda *_: (_ for _ in ()).throw(HTTPError("https://example.test", 429, "limited", {}, None)))
    monkeypatch.setattr(search, "fetch_search_range", lambda *_: search.parse_results(PAGE)[0])
    result = arxiv.fetch_submitted_range(SimpleNamespace(), date(2024, 10, 19), date(2025, 1, 31))
    assert result[0].base_id == "2410.12345"
