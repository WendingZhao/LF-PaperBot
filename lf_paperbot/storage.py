from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "updated_at": None, "papers": {}, "report_dates": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("papers"), dict):
        raise RuntimeError(f"unsupported paper index schema: {path}")
    data.setdefault("report_dates", [])
    if not isinstance(data["report_dates"], list):
        raise RuntimeError(f"unsupported paper index report dates: {path}")
    return data


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def save_index(path: Path, index: dict[str, Any], updated_at: datetime) -> None:
    index["schema_version"] = SCHEMA_VERSION
    index["updated_at"] = updated_at.isoformat()
    save_json(path, index)


def public_payload(index: dict[str, Any]) -> dict[str, Any]:
    papers = sorted(
        index.get("papers", {}).values(),
        key=lambda item: (item.get("last_seen", ""), item.get("rank_score", 0)),
        reverse=True,
    )
    reports: dict[str, list[str]] = {date_key: [] for date_key in index.get("report_dates", [])}
    for paper in papers:
        for date_key in paper.get("appeared_dates", []):
            reports.setdefault(date_key, []).append(paper["base_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": index.get("updated_at"),
        "papers": papers,
        "reports": reports,
    }
