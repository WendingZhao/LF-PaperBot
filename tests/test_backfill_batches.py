from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json

from lf_paperbot import backfill_batches as batches
from lf_paperbot.models import Candidate


def test_monthly_windows_cover_two_year_boundary_without_gaps():
    periods = list(batches.monthly_windows(date(2024, 10, 19), date(2026, 10, 19)))
    assert len(periods) == 25
    assert periods[0] == (date(2024, 10, 19), date(2024, 10, 31))
    assert periods[-1] == (date(2026, 10, 1), date(2026, 10, 19))
    assert periods[4] == (date(2025, 2, 1), date(2025, 2, 28))


def test_monthly_resume_skips_completed_months_and_retries_partial(monkeypatch, tmp_path):
    cfg = SimpleNamespace(root=tmp_path, timezone=ZoneInfo("Asia/Shanghai"))
    calls = []

    def fake_backfill(_cfg, start, end, **kwargs):
        calls.append((start, end, kwargs))
        return {"processed": 2, "failed": 0, "sources": {"arxiv": {"status": "ok", "count": 2}}}

    monkeypatch.setattr(batches, "run_backfill", fake_backfill)
    first = batches.run_monthly_backfill(cfg, date(2025, 1, 1), date(2025, 2, 28), all_papers=True)
    assert first["processed"] == 4
    second = batches.run_monthly_backfill(cfg, date(2025, 1, 1), date(2025, 2, 28), all_papers=True)
    assert second["processed"] == 0
    assert len(calls) == 2
    assert all(c[2]["all_papers"] for c in calls)


def test_snapshot_assigns_month_precision_only_once_and_invalidates_resume_on_change(monkeypatch, tmp_path):
    cfg = SimpleNamespace(root=tmp_path, timezone=ZoneInfo("Asia/Shanghai"))
    paper = Candidate(arxiv_id="", source="cvf", title="Light Field Denoising", abstract="A", authors=[],
                      categories=[], published="", updated="", pdf_url="", publication_year=2025,
                      publication_month="2025-02", date_basis="discovered")
    path = tmp_path / "snapshot.json"
    snapshot = {"start": "2025-01-01", "end": "2025-03-31", "sources": {"cvf": {"status": "ok", "count": 1}},
                "candidates": [paper.to_dict()]}
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    calls = []

    def backfill(_cfg, start, end, **kwargs):
        calls.append((start.month, len(kwargs["candidates"])))
        return {"processed": 0, "failed": 0, "sources": kwargs["candidates"].stats}

    monkeypatch.setattr(batches, "run_backfill", backfill)
    batches.run_monthly_backfill(cfg, date(2025, 1, 1), date(2025, 3, 31), all_papers=True, candidate_file=path)
    assert calls == [(1, 0), (2, 1), (3, 0)]
    batches.run_monthly_backfill(cfg, date(2025, 1, 1), date(2025, 3, 31), all_papers=True, candidate_file=path)
    assert len(calls) == 3
    snapshot["updated_at"] = "changed"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    batches.run_monthly_backfill(cfg, date(2025, 1, 1), date(2025, 3, 31), all_papers=True, candidate_file=path)
    assert len(calls) == 6


def test_incomplete_sources_are_retried_and_not_claimed_complete(monkeypatch, tmp_path):
    cfg = SimpleNamespace(root=tmp_path, timezone=ZoneInfo("Asia/Shanghai"))
    calls = []

    def backfill(*_args, **_kwargs):
        calls.append(1)
        return {"processed": 0, "failed": 0, "sources": {"arxiv": {"status": "failed", "count": 0}}}

    monkeypatch.setattr(batches, "run_backfill", backfill)
    monkeypatch.setattr(batches.time, "sleep", lambda *_: None)
    result = batches.run_monthly_backfill(cfg, date(2025, 1, 1), date(2025, 1, 31), all_papers=True)
    assert len(calls) == 2
    assert result["incomplete_batches"] == ["20250101-20250131"]


def test_incomplete_snapshot_is_not_retried_as_if_it_were_a_live_source(monkeypatch, tmp_path):
    cfg = SimpleNamespace(root=tmp_path, timezone=ZoneInfo("Asia/Shanghai"))
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"start": "2025-01-01", "end": "2025-01-31", "candidates": [],
                               "sources": {"arxiv": {"status": "failed", "count": 0}}}), encoding="utf-8")
    calls = []

    def run(*_a, **_kw):
        calls.append(1)
        return {"processed": 0, "failed": 0, "sources": {"arxiv": {"status": "failed", "count": 0}}}

    monkeypatch.setattr(batches, "run_backfill", run)
    result = batches.run_monthly_backfill(cfg, date(2025, 1, 1), date(2025, 1, 31), candidate_file=path)
    assert len(calls) == 1
    assert result["incomplete_batches"] == ["20250101-20250131"]
