"""Publication-date limits shared by discovery, ingestion and cleanup."""
from __future__ import annotations

import calendar
from datetime import date
from typing import Mapping

from .models import Candidate


def before_cutoff(paper: Candidate | Mapping, cutoff: date | None) -> bool:
    """Exclude only when the entire known publication interval is too old.

    Discovery/update dates do not replace publication dates. A year-only 2025
    record may be after June, so it must not be silently assigned January 1.
    """
    if cutoff is None:
        return False
    values = paper.to_dict() if isinstance(paper, Candidate) else paper
    published = values.get("published", "")
    if published:
        try:
            return date.fromisoformat(published[:10]) < cutoff
        except ValueError:
            pass
    month = values.get("publication_month", "")
    if month:
        try:
            year, month_number = map(int, month.split("-"))
            return date(year, month_number, calendar.monthrange(year, month_number)[1]) < cutoff
        except (ValueError, calendar.IllegalMonthError):
            pass
    year = values.get("publication_year", 0)
    if year:
        try:
            return date(int(year), 12, 31) < cutoff
        except (ValueError, TypeError):
            pass
    return False


def bounded_start(settings, start: date, end: date) -> date:
    cutoff = getattr(settings, "earliest_date", None)
    start = max(start, cutoff) if cutoff else start
    if start > end:
        raise ValueError("Requested date range ends before LF_EARLIEST_DATE or start date")
    return start


def trim_snapshot(snapshot: dict, cutoff: date) -> dict:
    """Narrow a discovery snapshot without re-fetching public metadata."""
    if date.fromisoformat(snapshot["end"]) < cutoff:
        raise ValueError("Snapshot ends before cutoff")
    candidates = [c for c in snapshot["candidates"] if not before_cutoff(c, cutoff)]
    return {
        **snapshot,
        "start": max(snapshot["start"], str(cutoff)),
        "candidates": candidates,
        "sources": {
            name: {**info, "count": sum(name in c.get("sources", [c.get("source", "arxiv")]) for c in candidates)}
            for name, info in snapshot["sources"].items()
        },
    }
