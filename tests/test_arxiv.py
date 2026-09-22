from __future__ import annotations

import urllib.parse
from datetime import date
from types import SimpleNamespace
from urllib.error import HTTPError
import io

from lf_paperbot import arxiv


ATOM_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>https://arxiv.org/abs/2601.00001v1</id>
    <updated>2026-01-02T00:00:00Z</updated>
    <published>2026-01-02T00:00:00Z</published>
    <title>Light Field Denoising</title>
    <summary>Spatial-angular restoration.</summary>
    <author><name>A</name></author>
    <category term="cs.CV" />
    <link title="pdf" href="https://arxiv.org/pdf/2601.00001v1" />
  </entry>
</feed>
"""


def test_fetch_submitted_range_uses_server_date_query(monkeypatch):
    captured = []

    def fake_read(url, _user_agent):
        captured.append(urllib.parse.unquote(url))
        return ATOM_FEED

    monkeypatch.setattr(arxiv, "_read_url", fake_read)
    settings = SimpleNamespace(arxiv_api_url="https://example.test/query", arxiv_user_agent="test")
    papers = arxiv.fetch_submitted_range(settings, date(2026, 1, 1), date(2026, 1, 31))
    assert [paper.arxiv_id for paper in papers] == ["2601.00001v1"]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(captured[0]).query)["search_query"][0]
    assert "submittedDate:[202601010000 TO 202601312359]" in query
    assert "cat:cs.GR" in query
    assert 'all:"sub-aperture image"' in query


def test_read_url_retries_transient_406_and_sets_atom_headers(monkeypatch):
    responses = [
        HTTPError("https://example.test", 406, "not acceptable", {}, io.BytesIO()),
        type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: False,
            "read": lambda self: b"ok",
        })(),
    ]
    captured = {}

    def fake_urlopen(request, **_kwargs):
        captured.update(request.headers)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(arxiv.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(arxiv.time, "sleep", lambda _seconds: None)
    assert arxiv._read_url("https://example.test", "LF-PaperBot/test", retries=2) == b"ok"
    assert captured["Accept"].startswith("application/atom+xml")
    assert captured["Accept-encoding"] == "identity"


def test_read_url_uses_http_export_fallback_after_https_406(monkeypatch):
    calls = []
    responses = [
        HTTPError("https://export.arxiv.org/api/query", 406, "not acceptable", {}, io.BytesIO()),
        type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: False,
            "read": lambda self: b"ok",
        })(),
    ]

    def fake_urlopen(request, **_kwargs):
        calls.append(request.full_url)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(arxiv.urllib.request, "urlopen", fake_urlopen)
    assert arxiv._read_url("https://export.arxiv.org/api/query?start=0", "test", retries=2) == b"ok"
    assert calls == [
        "https://export.arxiv.org/api/query?start=0",
        "http://export.arxiv.org/api/query?start=0",
    ]
