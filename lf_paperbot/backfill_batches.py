"""Resumable monthly history runs with an optional Git checkpoint per month."""
from __future__ import annotations

import calendar
import json
import hashlib
from dataclasses import fields
import subprocess
import time
from datetime import date, datetime, timedelta

from .config import Settings
from .pipeline import run_backfill
from .models import Candidate
from .public_sources import SourceCandidates
from .storage import save_json


def monthly_windows(start: date, end: date):
    if start > end:
        raise ValueError("start date must not be after end date")
    current = start
    while current <= end:
        last = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
        period_end = min(last, end)
        yield current, period_end
        current = period_end + timedelta(days=1)


def commit_checkpoint(settings: Settings, message: str) -> None:
    def git(*args, **kwargs):
        return subprocess.run(["git", *args], cwd=settings.root, check=True, text=True, **kwargs)

    git("add", "papers/index.json", "papers/backfill_status.json", "daily_reports", "docs/data", "docs/assets/previews")
    changes = git("diff", "--cached", "--name-only", capture_output=True).stdout
    if not changes.strip():
        return
    git("commit", "-m", message)
    git("pull", "--rebase", "origin", "main")
    git("push", "origin", "HEAD:main")


def run_monthly_backfill(settings: Settings, start: date, end: date, *,
                         force: bool = False, all_papers: bool = False, commit: bool = False,
                         candidate_file=None) -> dict:
    snapshot = None
    fingerprint = "live"
    if candidate_file:
        raw = candidate_file.read_bytes()
        fingerprint = hashlib.sha256(raw).hexdigest()
        snapshot = json.loads(raw)
        if snapshot["start"] > str(start) or snapshot["end"] < str(end):
            raise ValueError("Candidate snapshot does not cover the requested date range")
    candidate_fields = {f.name for f in fields(Candidate)}
    manifest_path = settings.root / "papers" / "backfill_status.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"batches": {}}
    manifest.update({"requested_start": str(start), "requested_end": str(end), "all_papers": all_papers})
    processed = failed = 0
    incomplete = []
    for period_start, period_end in monthly_windows(start, end):
        batch_key = f"{period_start:%Y%m%d}-{period_end:%Y%m%d}"
        previous = manifest["batches"].get(batch_key, {})
        if (not force and previous.get("status") == "complete" and previous.get("all_papers") == all_papers
                and previous.get("candidate_fingerprint", "live") == fingerprint):
            print(f"[BATCH] {batch_key}: already complete; skipping")
            continue
        summary = {"status": "running", "all_papers": all_papers, "candidate_fingerprint": fingerprint}
        batch_processed = 0
        manifest["batches"][batch_key] = summary
        save_json(manifest_path, manifest)
        # Retry incomplete source retrieval once. Completed papers are skipped
        # by the index, so this does not create duplicate Issues or reports.
        for attempt in range(2):
            try:
                print(f"[BATCH] {batch_key}: attempt={attempt + 1}", flush=True)
                kwargs = {}
                if snapshot is not None:
                    items = []
                    for record in snapshot["candidates"]:
                        candidate = Candidate(**{k: v for k, v in record.items() if k in candidate_fields})
                        if candidate.published:
                            paper_day = date.fromisoformat(candidate.published[:10])
                        elif candidate.publication_month:
                            year, month = map(int, candidate.publication_month.split("-"))
                            paper_day = date(year, month, calendar.monthrange(year, month)[1])
                            paper_day = min(paper_day, end)
                        elif candidate.publication_year:
                            paper_day = min(date(candidate.publication_year, 12, 31), end)
                        else:
                            paper_day = end
                        if period_start <= paper_day <= period_end:
                            items.append(candidate)
                    stats = {name: {**info, "count": sum(name in c.sources for c in items)}
                             for name, info in snapshot["sources"].items()}
                    kwargs["candidates"] = SourceCandidates(items, stats)
                result = run_backfill(settings, period_start, period_end, force=force and attempt == 0,
                                      all_papers=all_papers, **kwargs)
                batch_processed += result["processed"]
                source_stats = result.get("sources", {})
                complete = not result["failed"] and all(x["status"] == "ok" for x in source_stats.values())
                summary.update({"status": "complete" if complete else "partial", "sources": source_stats,
                                "processed": batch_processed, "failed": result["failed"],
                                "attempt": attempt + 1})
                processed += result["processed"]
                if complete:
                    break
                if snapshot is not None and not result["failed"]:
                    # Re-reading an incomplete immutable snapshot cannot repair
                    # the upstream source. Refresh discovery before retrying.
                    break
            except Exception as exc:
                summary.update({"status": "failed", "error": type(exc).__name__, "attempt": attempt + 1})
                print(f"[BATCH ERROR] {batch_key}: {type(exc).__name__}", flush=True)
            summary["updated_at"] = datetime.now(settings.timezone).isoformat()
            save_json(manifest_path, manifest)
            if commit:
                commit_checkpoint(settings, f"chore: checkpoint LF history {batch_key}")
            if attempt == 0:
                time.sleep(15)
        summary["updated_at"] = datetime.now(settings.timezone).isoformat()
        save_json(manifest_path, manifest)
        if summary["status"] != "complete":
            incomplete.append(batch_key)
            failed += summary.get("failed", 0)
        if commit:
            commit_checkpoint(settings, f"chore: backfill LF history {batch_key}")
        print(f"[BATCH DONE] {batch_key}: {summary['status']}", flush=True)
    manifest["incomplete_batches"] = incomplete
    manifest["updated_at"] = datetime.now(settings.timezone).isoformat()
    save_json(manifest_path, manifest)
    if commit:
        commit_checkpoint(settings, "chore: save LF history backfill summary")
    return {"start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
            "periods": list(manifest["batches"].values()), "processed": processed, "failed": failed,
            "incomplete_batches": incomplete}
