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


def test_non_arxiv_abstract_report_uses_real_source_and_no_pdf(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from lf_paperbot.analysis import REPORT_FIELDS
    item = candidate()
    item.source = "crossref"
    item.source_url = "https://doi.org/10.1234/lf"
    item.pdf_url = ""
    item.doi = "10.1234/lf"
    scopes = []

    def fake_report(_candidate, _context, _client, *, content_scope):
        scopes.append(content_scope)
        return {k: "仅基于公开摘要" for k in REPORT_FIELDS}

    class Store:
        def upsert_paper_issue(self, _candidate, body, _date):
            assert "https://doi.org/10.1234/lf" in body
            assert "仅公开摘要，未读取全文" in body
            assert "arxiv.org/abs" not in body
            return SimpleNamespace(number=1, html_url="https://github.com/test/issues/1"), "created"

    def no_download(*_args):
        raise AssertionError("No PDF URL must not download")

    monkeypatch.setattr(pipeline, "generate_report", fake_report)
    monkeypatch.setattr(pipeline, "download_pdf", no_download)
    record = pipeline.process_candidate(settings(tmp_path), item, "20261018", {"papers": {}}, object(), Store())
    assert scopes == ["abstract_only"]
    assert record["content_scope"] == "abstract_only"
    assert record["cover_url"] == ""
    assert record["doi"] == item.doi


def test_pdf_download_failure_can_fall_back_to_abstract(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from lf_paperbot.analysis import REPORT_FIELDS
    monkeypatch.setattr(pipeline, "download_pdf", lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 406")))
    scopes = []

    def report(_candidate, _context, _client, *, content_scope):
        scopes.append(content_scope)
        return {k: "论文材料未说明" for k in REPORT_FIELDS}

    monkeypatch.setattr(pipeline, "generate_report", report)
    store = SimpleNamespace(upsert_paper_issue=lambda *_: (SimpleNamespace(number=1, html_url="https://example.test/1"), "created"))
    result = pipeline.process_candidate(settings(tmp_path), candidate(), "20261018", {"papers": {}}, object(), store)
    assert result["content_scope"] == "abstract_only"
    assert scopes == ["abstract_only"]


def test_history_metadata_only_does_not_invent_a_model_report(monkeypatch, tmp_path):
    from types import SimpleNamespace
    item = candidate()
    item.abstract = item.pdf_url = ""
    monkeypatch.setattr(pipeline, "generate_report", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("no source text")))

    def upsert(_candidate, body, _date):
        assert "仅题录，未获取摘要或全文" in body
        assert "无法核实" in body
        return SimpleNamespace(number=1, html_url="https://example.test/1"), "created"

    store = SimpleNamespace(upsert_paper_issue=upsert)
    record = pipeline.process_candidate(settings(tmp_path), item, "20261019", {"papers": {}}, object(), store, allow_metadata=True)
    assert record["content_scope"] == "metadata_only"
    assert record["cover_url"] == ""


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


def test_all_history_removes_five_paper_limit_and_is_idempotent(monkeypatch, tmp_path):
    from dataclasses import replace
    items = [replace(candidate(), arxiv_id=f"2501.{n:05d}v1", base_id="", title=f"Light Field Denoising Method {n}") for n in range(8)]
    monkeypatch.setattr(pipeline, "classify_with_llm", lambda items, _client: items)
    monkeypatch.setattr(pipeline, "GitHubStore", lambda _cfg: object())
    calls = []

    def process(_cfg, selected, date_key, index, *_args, **kwargs):
        calls.append((selected.base_id, kwargs["allow_metadata"]))
        return {"base_id": selected.base_id, "arxiv_id": selected.arxiv_id, "version": 1,
                "title": selected.title, "tasks": selected.tasks, "pdf_url": selected.pdf_url,
                "rank_score": 1, "appeared_dates": [date_key], "issue_url": "https://example.test/issue"}

    monkeypatch.setattr(pipeline, "process_candidate", process)
    cfg = settings(tmp_path)
    first = pipeline.run_pipeline(cfg, date(2025, 1, 5), candidates=items, all_papers=True)
    assert len(first["processed"]) == 8
    assert len(calls) == 8
    content = (tmp_path / "daily_reports/202501/20250105.md").read_text(encoding="utf-8")
    assert "最终精选：8 篇" in content
    second = pipeline.run_pipeline(cfg, date(2025, 1, 5), candidates=items, all_papers=True)
    assert not second["processed"]
    pipeline.reconcile_date(cfg, "20250105")
    assert "最终精选：8 篇" in (tmp_path / "daily_reports/202501/20250105.md").read_text(encoding="utf-8")
    historical = pipeline.run_pipeline(cfg, date(2024, 12, 29), candidates=items, all_papers=True)
    assert not historical["processed"]
    assert len(calls) == 8
    assert "最终精选：8 篇" in (tmp_path / "daily_reports/202412/20241229.md").read_text(encoding="utf-8")


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
