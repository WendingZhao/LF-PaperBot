from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from lf_paperbot import public_sources as sources
from lf_paperbot.models import Candidate


def cfg(**kwargs):
    return SimpleNamespace(arxiv_user_agent="test", lookback_days=7, crossref_max_pages=2, crossref_mailto="",
                           cvf_venues=("CVPR2026",), sources=("arxiv", "crossref", "cvf"), **kwargs)


def metadata(**kwargs):
    return dict({"DOI": "10.1234/LF.1", "title": ["Light Field Denoising"],
                 "abstract": "<jats:p>Restore spatial-angular images.</jats:p>",
                 "author": [{"given": "A", "family": "B"}],
                 "published": {"date-parts": [[2026, 10, 15]]},
                 "container-title": ["Vision Journal"],
                 "link": [{"content-type": "application/pdf", "URL": "https://publisher.test/paper.pdf"}]}, **kwargs)


def test_crossref_preserves_doi_and_does_not_assume_tdm_is_open():
    paper = sources.parse_crossref(metadata())
    assert paper.doi == "10.1234/lf.1"
    assert paper.abstract == "Restore spatial-angular images."
    assert paper.pdf_url == ""
    assert paper.source == "crossref"
    assert "/" not in paper.base_id
    item = metadata(license=[{"URL": "https://creativecommons.org/licenses/by/4.0/"}])
    assert sources.parse_crossref(item).pdf_url == "https://publisher.test/paper.pdf"


def test_crossref_rejects_unrelated_results_and_does_not_invent_date():
    assert sources.parse_crossref(metadata(title=["Single Image Denoising"], abstract="")) is None
    paper = sources.parse_crossref(metadata(published={"date-parts": [[2026]]}))
    assert paper.published == ""
    assert paper.publication_year == 2026


def test_crossref_paginates_and_searches_both_publication_and_registration(monkeypatch):
    urls = []

    def read(url, _agent):
        urls.append(parse_qs(urlsplit(url).query))
        page = 1 if urls[-1]["cursor"] == ["*"] else 2
        items = [metadata()] * (100 if page == 1 else 1)
        return json.dumps({"message": {"items": items, "next-cursor": "next"}}).encode()

    monkeypatch.setattr(sources, "read_public", read)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    result = sources.fetch_crossref(cfg(), date(2026, 10, 12), date(2026, 10, 18))
    assert len(urls) == 8
    assert len(sources.deduplicate(result)) == 1
    assert any("from-created-date:2026-10-12" in x["filter"][0] for x in urls)
    assert any(x["cursor"] == ["next"] for x in urls)


CVF_PAPER = '''<meta name="citation_title" content="Light Field Denoising">
<meta name="citation_author" content="A, B"><meta name="citation_publication_date" content="2026">
<meta name="citation_pdf_url" content="https://openaccess.thecvf.com/content/test.pdf">
<div id="abstract">Restore <b>spatial-angular</b> images.</div>'''


def test_cvf_discovers_only_lf_papers_and_marks_year_only_dates(monkeypatch):
    urls = []

    def read(url, _agent):
        urls.append(url)
        if "?day=all" in url:
            return b'<a href="/content/CVPR2026/html/a.html">Light Field Denoising</a><a href="/content/CVPR2026/html/b.html">Object Detection</a>'
        return CVF_PAPER.encode()

    monkeypatch.setattr(sources, "read_public", read)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    items = sources.fetch_cvf(cfg(), date(2026, 10, 12), date(2026, 10, 18))
    assert len(urls) == 2
    assert items[0].published == ""
    assert items[0].publication_year == 2026
    assert items[0].date_basis == "discovered"
    assert items[0].abstract == "Restore spatial-angular images."


def test_cvf_archive_format_change_is_not_silent_empty_success(monkeypatch):
    monkeypatch.setattr(sources, "read_public", lambda *_: b'<html>Not an archive</html>')
    with pytest.raises(RuntimeError, match="no paper links"):
        sources.fetch_cvf(cfg(), date(2026, 10, 12), date(2026, 10, 18))


def arxiv_paper():
    return Candidate(arxiv_id="2610.12345v2", title="Light-Field Denoising!", abstract="A", authors=[],
                     categories=[], published="2026-10-15", updated="2026-10-16", pdf_url="https://arxiv.org/pdf/2610.12345v2")


def test_cross_source_dedup_merges_provenance_and_keeps_arxiv_version():
    crossref = sources.parse_crossref(metadata())
    cvf = sources.parse_cvf_page(CVF_PAPER, "https://openaccess.thecvf.com/a.html", "CVPR2026")
    items = sources.deduplicate([crossref, cvf, arxiv_paper()])
    assert len(items) == 1
    assert items[0].arxiv_id == "2610.12345v2"
    assert items[0].doi == "10.1234/lf.1"
    assert set(items[0].sources) == {"arxiv", "crossref", "cvf"}


def test_title_alias_matches_existing_index_and_doi_matches_changed_title():
    record = {"base_id": "2610.12345", "title": "Light Field Denoising", "doi": "10.1234/lf.1"}
    item = sources.parse_crossref(metadata(title=["A New Light Field Denoising Title"]))
    result = sources.deduplicate([item], {record["base_id"]: record})
    assert result[0].base_id == record["base_id"]


def test_individual_source_outage_does_not_lose_work_and_all_outages_raise(monkeypatch):
    def fail(*_args, **_kwargs):
        raise HTTPError("https://example.test", 406, "error", {}, None)

    monkeypatch.setattr(sources.arxiv, "fetch_recent", fail)
    monkeypatch.setattr(sources, "fetch_crossref", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sources, "fetch_cvf", lambda *_args: [arxiv_paper()])
    items, stats = sources.fetch_sources(cfg(), date(2026, 10, 18))
    assert len(items) == 1
    assert stats["arxiv"] == {"status": "failed", "count": 0, "error": "HTTP 406"}
    monkeypatch.setattr(sources, "fetch_crossref", fail)
    monkeypatch.setattr(sources, "fetch_cvf", fail)
    with pytest.raises(RuntimeError, match="All paper sources failed"):
        sources.fetch_sources(cfg(), date(2026, 10, 18))


def test_rate_limit_retries_public_requests(monkeypatch):
    from contextlib import contextmanager
    calls = []

    @contextmanager
    def response():
        yield SimpleNamespace(read=lambda: b"ok")

    def request(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError("https://example.test", 429, "limited", {"Retry-After": "1"}, None)
        return response()

    waits = []
    monkeypatch.setattr(sources.urllib.request, "urlopen", request)
    monkeypatch.setattr(sources.time, "sleep", waits.append)
    assert sources.read_public("https://example.test", "test") == b"ok"
    assert waits == [1]


def test_partial_query_keeps_candidates_and_records_incomplete_status(monkeypatch):
    def partial(*_args, **_kwargs):
        raise sources.PartialSourceError([sources.parse_crossref(metadata())], "result limit reached")
    monkeypatch.setattr(sources.arxiv, "fetch_recent", lambda *_: [])
    monkeypatch.setattr(sources, "fetch_crossref", partial)
    monkeypatch.setattr(sources, "fetch_cvf", lambda *_: [])
    items, stats = sources.fetch_sources(cfg(), date(2026, 10, 18))
    assert len(items) == 1
    assert stats["crossref"]["status"] == "partial"


def test_history_crossref_uses_large_pages_and_has_no_weekly_page_cap(monkeypatch):
    urls = []

    def read(url, _agent):
        query = parse_qs(urlsplit(url).query)
        urls.append(query)
        if query["query.title"] == ["plenoptic"]:
            items = []
        elif query["cursor"] == ["*"]:
            items = [metadata(DOI=f"10.1234/p{i}") for i in range(1000)]
        else:
            items = [metadata(DOI="10.1234/last")]
        return json.dumps({"message": {"items": items, "next-cursor": "next", "total-results": 1001}}).encode()

    monkeypatch.setattr(sources, "read_public", read)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    c = cfg()
    c.crossref_max_pages = 1
    items = sources.fetch_crossref(c, date(2025, 1, 1), date(2025, 1, 31), historical=True)
    assert len(items) == 1001
    assert all(q["rows"] == ["1000"] for q in urls)
    assert len(urls) == 3


def test_cvf_bibtex_month_preserves_precision_without_fake_publication_day():
    item = sources.parse_cvf_page(CVF_PAPER + '\nmonth = {June}', "https://example.test/cvf", "CVPR2026")
    assert item.publication_month == "2026-06"
    assert item.published == ""
