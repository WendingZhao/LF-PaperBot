from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lf_paperbot.config import Settings
from lf_paperbot.models import Candidate
from lf_paperbot import pipeline
from lf_paperbot.storage import load_index, save_index


def settings(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        ark_base_url="https://example.test/v3",
        ark_api_key="test-placeholder-not-a-real-key",
        ark_model="test-model",
        github_token="test-placeholder",
        github_repo="owner/repo",
        max_daily_papers=5,
        timezone=ZoneInfo("Asia/Shanghai"),
        lookback_days=3,
        arxiv_api_url="https://example.test/arxiv",
        arxiv_user_agent="test",
        temp_dir=tmp_path / "tmp",
    )


def candidate() -> Candidate:
    return Candidate(
        arxiv_id="2607.12345v1",
        title="Light Field Denoising",
        abstract="We denoise spatial-angular light fields.",
        authors=["A"],
        categories=["cs.CV"],
        published="2026-07-26T00:00:00Z",
        updated="2026-07-26T00:00:00Z",
        pdf_url="https://example.test/paper.pdf",
    )


def test_pipeline_orchestrates_and_is_idempotent(monkeypatch, tmp_path):
    item = candidate()
    monkeypatch.setattr(pipeline, "fetch_recent", lambda *_args, **_kwargs: [item])
    monkeypatch.setattr(pipeline, "classify_with_llm", lambda items, _client: items)
    monkeypatch.setattr(pipeline, "GitHubStore", lambda _settings: object())

    calls = []

    def fake_process(_settings, selected, date_key, index, _client, _github):
        calls.append(selected.arxiv_id)
        return {
            "base_id": selected.base_id,
            "arxiv_id": selected.arxiv_id,
            "version": selected.version,
            "title": selected.title,
            "pdf_url": selected.pdf_url,
            "tasks": selected.tasks,
            "rank_score": selected.rank_score,
            "evidence": selected.evidence,
            "report": {"tldr": "测试"},
            "issue_url": "https://github.com/owner/repo/issues/1",
            "last_seen": date_key,
            "appeared_dates": [date_key],
            "is_version_update": False,
        }

    monkeypatch.setattr(pipeline, "process_candidate", fake_process)
    cfg = settings(tmp_path)
    first = pipeline.run_pipeline(cfg, date(2026, 7, 26))
    private_after_first = (tmp_path / "papers" / "index.json").read_text(encoding="utf-8")
    public_after_first = (tmp_path / "docs" / "data" / "index.json").read_text(encoding="utf-8")
    report_path = tmp_path / "daily_reports" / "202607" / "20260726.md"
    report_after_first = report_path.read_text(encoding="utf-8")
    second = pipeline.run_pipeline(cfg, date(2026, 7, 26))
    assert len(first["processed"]) == 1
    assert len(second["processed"]) == 0
    assert calls == ["2607.12345v1"]
    assert (tmp_path / "papers" / "index.json").read_text(encoding="utf-8") == private_after_first
    assert (tmp_path / "docs" / "data" / "index.json").read_text(encoding="utf-8") == public_after_first
    assert report_path.read_text(encoding="utf-8") == report_after_first
    assert "Light Field Denoising" in report_after_first
    assert (tmp_path / "docs" / "data" / "index.json").exists()


def test_backfill_groups_candidates_by_natural_week(monkeypatch, tmp_path):
    first = candidate()
    first.published = "2026-01-02T00:00:00Z"
    second = candidate()
    second.arxiv_id = "2601.54321v1"
    second.published = "2026-01-06T00:00:00Z"
    monkeypatch.setattr(pipeline, "fetch_submitted_range", lambda *_args: [first, second])
    calls = []

    def fake_run(_settings, period_end, force=False, *, candidates=None, window_start=None):
        calls.append((window_start, period_end, [item.arxiv_id for item in candidates], force))
        return {"date": period_end.strftime("%Y%m%d"), "processed": [], "failed": []}

    monkeypatch.setattr(pipeline, "run_pipeline", fake_run)
    result = pipeline.run_backfill(settings(tmp_path), date(2026, 1, 1), date(2026, 1, 11))
    assert calls == [
        (date(2026, 1, 1), date(2026, 1, 4), ["2607.12345v1"], False),
        (date(2026, 1, 5), date(2026, 1, 11), ["2601.54321v1"], False),
    ]
    assert len(result["periods"]) == 2


def test_reconcile_uses_natural_week_start(monkeypatch, tmp_path):
    record = {
        "title": "Light Field Denoising",
        "arxiv_id": "2603.12345v1",
        "pdf_url": "https://example.test/paper.pdf",
        "tasks": ["去噪"],
        "rank_score": 0.9,
        "report": {"tldr": "测试"},
        "issue_url": "https://github.com/owner/repo/issues/1",
        "appeared_dates": ["20260322"],
    }
    monkeypatch.setattr(
        pipeline,
        "load_index",
        lambda _path: {"papers": {"2603.12345": record}, "report_dates": ["20260322"]},
    )

    report_path = pipeline.reconcile_date(settings(tmp_path), "20260322")
    content = report_path.read_text(encoding="utf-8")
    assert content.startswith("# 光场底层视觉周报 20260316 — 20260322")
    assert "Light Field Denoising" in content


def test_prune_removes_nonstandard_light_field_records(tmp_path):
    cfg = settings(tmp_path)
    index_path = tmp_path / "papers" / "index.json"
    index = load_index(index_path)
    index["report_dates"] = ["20260301", "20260322"]
    index["papers"] = {
        "2602.22620": {
            "base_id": "2602.22620",
            "arxiv_id": "2602.22620v1",
            "title": "Event-Based Light Field Reconstruction",
            "abstract": "We use an event camera and event stream to reconstruct a light field.",
            "authors": [],
            "categories": ["cs.CV"],
            "published": "2026-02-26T00:00:00Z",
            "updated": "2026-02-26T00:00:00Z",
            "pdf_url": "https://example.test/event.pdf",
            "cover_url": "assets/previews/2602.22620.webp",
            "appeared_dates": ["20260301"],
        },
        "2603.16243": {
            "base_id": "2603.16243",
            "arxiv_id": "2603.16243v1",
            "title": "Light Field Super-Resolution",
            "abstract": "Spatial-angular image super-resolution.",
            "authors": [],
            "categories": ["cs.CV"],
            "published": "2026-03-20T00:00:00Z",
            "updated": "2026-03-20T00:00:00Z",
            "pdf_url": "https://example.test/sr.pdf",
            "cover_url": "assets/previews/2603.16243.webp",
            "appeared_dates": ["20260322"],
        },
    }
    save_index(index_path, index, datetime(2026, 3, 22, tzinfo=ZoneInfo("Asia/Shanghai")))
    preview = tmp_path / "docs" / "assets" / "previews" / "2602.22620.webp"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"preview")

    preview_result = pipeline.prune_index(cfg)
    assert [item["base_id"] for item in preview_result["excluded"]] == ["2602.22620"]
    assert preview.exists()

    applied = pipeline.prune_index(cfg, apply=True)
    assert applied["affected_dates"] == ["20260301"]
    assert set(load_index(index_path)["papers"]) == {"2603.16243"}
    assert not preview.exists()
    report = (tmp_path / "daily_reports" / "202603" / "20260301.md").read_text(encoding="utf-8")
    assert "最终精选：0 篇" in report
