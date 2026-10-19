import json
from types import SimpleNamespace
from dataclasses import replace

from lf_paperbot import cli, public_sources
from lf_paperbot.config import load_settings
from lf_paperbot.models import Candidate


def test_source_retry_merges_snapshot_without_losing_complete_sources(monkeypatch, tmp_path):
    path = tmp_path / "history.json"
    paper = Candidate(arxiv_id="2501.00001v1", title="Light Field Denoising", abstract="Restore images",
                      authors=[], categories=[], published="2025-01-01", updated="2025-01-01", pdf_url="")
    path.write_text(json.dumps({"start": "2025-01-01", "end": "2025-12-31",
                               "sources": {"arxiv": {"status": "ok", "count": 1},
                                           "cvf": {"status": "ok", "count": 1}},
                               "candidates": [paper.to_dict()]}), encoding="utf-8")
    settings = replace(load_settings(), root=tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(public_sources, "fetch_sources", lambda *_a, **_kw:
                        ([], {"arxiv": {"status": "failed", "count": 0, "error": "HTTP 429"}}))
    args = SimpleNamespace(start="20250101", end="20251231", sources="arxiv", output=str(path))
    assert cli.discover_command(args) == 0
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["sources"]["arxiv"]["status"] == "ok"
    assert result["sources"]["cvf"]["status"] == "ok"
    assert len(result["candidates"]) == 1
