from __future__ import annotations

import urllib.parse
from datetime import date
from types import SimpleNamespace

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
