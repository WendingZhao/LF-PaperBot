from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from lf_paperbot.config import Settings
from lf_paperbot.models import Candidate
from lf_paperbot import pipeline


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
    second = pipeline.run_pipeline(cfg, date(2026, 7, 26))
    assert len(first["processed"]) == 1
    assert len(second["processed"]) == 0
    assert calls == ["2607.12345v1"]
    assert (tmp_path / "daily_reports" / "202607" / "20260726.md").exists()
    assert (tmp_path / "docs" / "data" / "index.json").exists()
