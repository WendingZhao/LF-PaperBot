from dataclasses import replace
from datetime import date, datetime
import json

import pytest

from lf_paperbot import pipeline
from lf_paperbot.config import load_settings
from lf_paperbot.date_policy import before_cutoff, bounded_start, trim_snapshot
from lf_paperbot.models import Candidate
from lf_paperbot.storage import load_index, save_index, save_json


CUTOFF = date(2025, 6, 1)


@pytest.mark.parametrize("record,excluded", [
    ({"published": "2025-05-31T23:59:59Z", "updated": "2026-10-19"}, True),
    ({"published": "2025-06-01T00:00:00Z"}, False),
    ({"publication_month": "2025-05"}, True),
    ({"publication_month": "2025-06"}, False),
    ({"publication_year": 2024}, True),
    ({"publication_year": 2025}, False),
    ({"published": "invalid", "publication_month": "2025-05"}, True),
    ({}, False),
])
def test_date_precision_and_boundary(record, excluded):
    assert before_cutoff(record, CUTOFF) is excluded


def test_default_cutoff_and_clamped_backfill(monkeypatch):
    monkeypatch.delenv("LF_EARLIEST_DATE", raising=False)
    cfg = load_settings()
    assert cfg.earliest_date == CUTOFF
    assert bounded_start(cfg, date(2024, 10, 19), date(2026, 10, 19)) == CUTOFF
    with pytest.raises(ValueError, match="LF_EARLIEST_DATE"):
        bounded_start(cfg, date(2025, 1, 1), date(2025, 5, 31))


def test_old_version_cannot_be_reingested(monkeypatch, tmp_path):
    cfg = replace(load_settings(), root=tmp_path, earliest_date=CUTOFF)
    old = Candidate(arxiv_id="2505.00001v3", title="Light Field Denoising", abstract="LF denoising",
                    authors=[], categories=[], published="2025-05-31", updated="2026-10-19", pdf_url="")
    monkeypatch.setattr(pipeline, "classify_with_llm", lambda candidates, _: candidates)
    monkeypatch.setattr(pipeline, "GitHubStore", lambda _: pytest.fail("must not create old Issues"))
    result = pipeline.run_pipeline(cfg, date(2026, 10, 19), candidates=[old], all_papers=True)
    assert not result["processed"]
    assert not load_index(tmp_path / "papers/index.json")["papers"]
    with pytest.raises(ValueError, match="predates"):
        pipeline.process_candidate(cfg, old, "20261019", {}, None, None)


def test_snapshot_trim_preserves_source_status_and_real_date_precision():
    snapshot = {"start": "2024-10-19", "end": "2026-10-19",
                "sources": {"cvf": {"status": "partial", "count": 2, "error": "HTTP 429"}},
                "candidates": [{"publication_month": "2025-05", "source": "cvf"},
                               {"publication_year": 2025, "published": "", "source": "cvf"}]}
    trimmed = trim_snapshot(snapshot, CUTOFF)
    assert trimmed["start"] == "2025-06-01"
    assert trimmed["sources"]["cvf"] == {"status": "partial", "count": 1, "error": "HTTP 429"}
    assert trimmed["candidates"] == [snapshot["candidates"][1]]
    assert trimmed["candidates"][0]["published"] == ""
    assert len(snapshot["candidates"]) == 2


def test_cleanup_synchronizes_archives_preserves_uncertain_dates_and_is_idempotent(tmp_path):
    cfg = replace(load_settings(), root=tmp_path, earliest_date=CUTOFF)
    records = {
        "old": {"published": "2025-05-31", "cover_url": "assets/previews/old.webp"},
        "new": {"published": "2025-06-01"},
        "unknown": {"publication_year": 2025, "published": ""},
    }
    for key, record in records.items():
        record.update({"base_id": key, "arxiv_id": key, "title": "Light Field Denoising",
                       "appeared_dates": ["20250531", "20250608"], "rank_score": 1,
                       "issue_url": "https://example.test/issue"})
    index_path = tmp_path / "papers/index.json"
    index = load_index(index_path)
    index.update({"papers": records, "report_dates": ["20250531", "20250608"],
                  "source_runs": {"20250531": {}, "20250608": {}},
                  "unlimited_report_dates": ["20250531", "20250608"]})
    save_index(index_path, index, datetime.now(cfg.timezone))
    old_report = tmp_path / "daily_reports/202505/20250531.md"
    old_report.parent.mkdir(parents=True)
    old_report.write_text("old archive")
    cover = tmp_path / "docs/assets/previews/old.webp"
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"preview")
    other = cover.with_name("unrelated.webp")
    other.write_bytes(b"keep")
    manifest_path = tmp_path / "papers/backfill_status.json"
    save_json(manifest_path, {"batches": {"20250501-20250531": {}, "20250601-20250630": {}},
                              "requested_start": "2024-10-19", "incomplete_batches": ["20250501-20250531"]})
    preview = pipeline.prune_index(cfg, before=CUTOFF)
    assert len(preview["excluded"]) == 1 and old_report.exists() and cover.exists()
    result = pipeline.prune_index(cfg, apply=True, before=CUTOFF)
    assert len(result["excluded"]) == 1
    kept = load_index(index_path)
    assert set(kept["papers"]) == {"new", "unknown"}
    assert kept["report_dates"] == kept["unlimited_report_dates"] == ["20250608"]
    assert list(kept["source_runs"]) == ["20250608"]
    assert all(p["appeared_dates"] == ["20250608"] for p in kept["papers"].values())
    assert not old_report.exists() and not cover.exists() and other.exists()
    assert "最终精选：2 篇" in (tmp_path / "daily_reports/202506/20250608.md").read_text(encoding="utf-8")
    public = json.loads((tmp_path / "docs/data/index.json").read_text(encoding="utf-8"))
    assert {p["base_id"] for p in public["papers"]} == {"new", "unknown"}
    manifest = json.loads(manifest_path.read_text())
    assert manifest["requested_start"] == "2025-06-01"
    assert list(manifest["batches"]) == ["20250601-20250630"]
    again = pipeline.prune_index(cfg, apply=True, before=CUTOFF)
    assert not again["excluded"] and not again["removed_reports"]
