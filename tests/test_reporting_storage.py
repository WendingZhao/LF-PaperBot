from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from lf_paperbot.reporting import build_daily_report
from lf_paperbot.storage import load_index, public_payload, save_index


def test_empty_daily_report_is_explicit():
    report = build_daily_report("20260726", [], fetched_count=12, hard_filtered_count=0)
    assert "最终精选：0 篇" in report
    assert "当日未检索到" in report


def test_index_round_trip_and_public_report_map(tmp_path: Path):
    path = tmp_path / "papers" / "index.json"
    index = load_index(path)
    index["papers"]["2607.12345"] = {
        "base_id": "2607.12345",
        "last_seen": "20260726",
        "rank_score": 0.9,
        "appeared_dates": ["20260726"],
    }
    save_index(path, index, datetime(2026, 7, 26, tzinfo=ZoneInfo("Asia/Shanghai")))
    loaded = load_index(path)
    public = public_payload(loaded)
    assert public["reports"] == {"20260726": ["2607.12345"]}
    assert public["papers"][0]["base_id"] == "2607.12345"
