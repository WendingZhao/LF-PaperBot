from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .analysis import classify_with_llm, generate_report, rank_candidates, report_to_markdown
from .arxiv import download_pdf, fetch_by_id, fetch_recent, fetch_submitted_range
from .config import Settings
from .domain import deterministic_classify, deterministic_filter
from .github_store import GitHubStore
from .llm import ArkClient
from .models import Candidate
from .pdf_tools import extract_pdf_text, render_cover_webp, select_context
from .reporting import build_weekly_report, write_daily_report
from .storage import load_index, public_payload, save_index, save_json


def _date_key(settings: Settings, target_date: date | None) -> str:
    return (target_date or datetime.now(settings.timezone).date()).strftime("%Y%m%d")


def _needs_processing(candidate: Candidate, papers: dict, force: bool) -> bool:
    if force:
        return True
    previous = papers.get(candidate.base_id)
    return previous is None or candidate.version > int(previous.get("version", 0))


def _paper_record(
    candidate: Candidate,
    report: dict[str, str],
    issue_url: str,
    issue_number: int,
    cover_url: str,
    date_key: str,
    previous: dict | None,
) -> dict:
    appeared_dates = list(previous.get("appeared_dates", [])) if previous else []
    if date_key not in appeared_dates:
        appeared_dates.append(date_key)
    return {
        "base_id": candidate.base_id,
        "arxiv_id": candidate.arxiv_id,
        "version": candidate.version,
        "title": candidate.title,
        "abstract": candidate.abstract,
        "authors": candidate.authors,
        "categories": candidate.categories,
        "published": candidate.published,
        "updated": candidate.updated,
        "pdf_url": candidate.pdf_url,
        "tasks": candidate.tasks,
        "relevance_score": candidate.relevance_score,
        "research_score": candidate.research_score,
        "experiment_score": candidate.experiment_score,
        "code_score": candidate.code_score,
        "rank_score": candidate.rank_score,
        "evidence": candidate.evidence,
        "report": report,
        "issue_url": issue_url,
        "issue_number": issue_number,
        "cover_url": cover_url,
        "first_seen": previous.get("first_seen", date_key) if previous else date_key,
        "last_seen": date_key,
        "appeared_dates": appeared_dates,
        "is_version_update": bool(previous and candidate.version > int(previous.get("version", 0))),
    }


def process_candidate(
    settings: Settings,
    candidate: Candidate,
    date_key: str,
    index: dict,
    client: ArkClient,
    github: GitHubStore,
) -> dict:
    pdf_path = download_pdf(settings, candidate)
    cover_path = settings.root / "docs" / "assets" / "previews" / f"{candidate.base_id}.webp"
    try:
        render_cover_webp(pdf_path, cover_path)
        context = select_context(extract_pdf_text(pdf_path))
        report = generate_report(candidate, context, client)
        cover_url = (
            f"https://raw.githubusercontent.com/{settings.github_repo}/main/"
            f"docs/assets/previews/{candidate.base_id}.webp"
        )
        body = report_to_markdown(candidate, report, cover_url)
        issue, action = github.upsert_paper_issue(candidate, body, date_key)
        print(f"[ISSUE] {action} #{issue.number} for {candidate.arxiv_id}")
        previous = index["papers"].get(candidate.base_id)
        return _paper_record(
            candidate,
            report,
            issue.html_url,
            issue.number,
            f"assets/previews/{candidate.base_id}.webp",
            date_key,
            previous,
        )
    except Exception:
        cover_path.unlink(missing_ok=True)
        raise
    finally:
        pdf_path.unlink(missing_ok=True)


def run_pipeline(
    settings: Settings,
    target_date: date | None = None,
    force: bool = False,
    *,
    candidates: list[Candidate] | None = None,
    window_start: date | None = None,
) -> dict:
    date_key = _date_key(settings, target_date)
    effective_end = target_date or datetime.now(settings.timezone).date()
    effective_start = window_start or effective_end - timedelta(days=settings.lookback_days - 1)
    index_path = settings.root / "papers" / "index.json"
    index = load_index(index_path)
    original_index = copy.deepcopy(index)
    fetched = list(candidates) if candidates is not None else fetch_recent(settings, target_date)
    hard_filtered = deterministic_filter(fetched)
    pending = [candidate for candidate in hard_filtered if _needs_processing(candidate, index["papers"], force)]
    client = ArkClient(settings)
    classified = classify_with_llm(pending, client)
    selected = rank_candidates(classified, settings.max_daily_papers)
    github = GitHubStore(settings) if selected else None

    processed: list[dict] = []
    failed: list[str] = []
    for candidate in selected:
        try:
            assert github is not None
            record = process_candidate(settings, candidate, date_key, index, client, github)
            index["papers"][candidate.base_id] = record
            processed.append(record)
        except Exception as exc:
            failed.append(candidate.arxiv_id)
            print(f"[ERROR] failed to process {candidate.arxiv_id}: {type(exc).__name__}: {exc}")

    if date_key not in index["report_dates"]:
        index["report_dates"].append(date_key)
        index["report_dates"].sort()
    if index != original_index:
        save_index(index_path, index, datetime.now(settings.timezone))
    save_json(settings.root / "docs" / "data" / "index.json", public_payload(index))
    weekly_papers = [
        paper for paper in index["papers"].values() if date_key in paper.get("appeared_dates", [])
    ]
    weekly_papers.sort(key=lambda item: item.get("rank_score", 0), reverse=True)
    daily = build_weekly_report(
        date_key,
        weekly_papers[: settings.max_daily_papers],
        fetched_count=len(fetched),
        hard_filtered_count=len(hard_filtered),
        failed=failed,
        period_start=effective_start.strftime("%Y%m%d"),
    )
    report_path = write_daily_report(settings.root, date_key, daily)
    print(f"[DONE] {date_key}: {len(processed)} papers, report={report_path}")
    return {"date": date_key, "processed": processed, "failed": failed}


def weekly_windows(start_date: date, end_date: date):
    if start_date > end_date:
        raise ValueError("start date must not be after end date")
    current = start_date
    while current <= end_date:
        sunday = current + timedelta(days=6 - current.weekday())
        period_end = min(sunday, end_date)
        yield current, period_end
        current = period_end + timedelta(days=1)


def run_backfill(settings: Settings, start_date: date, end_date: date, force: bool = False) -> dict:
    candidates = fetch_submitted_range(settings, start_date, end_date)
    dated: list[tuple[date, Candidate]] = []
    for candidate in candidates:
        try:
            published_day = datetime.fromisoformat(candidate.published.replace("Z", "+00:00")).astimezone(
                timezone.utc
            ).date()
        except ValueError:
            continue
        dated.append((published_day, candidate))

    periods: list[dict] = []
    total_processed = 0
    total_failed = 0
    for period_start, period_end in weekly_windows(start_date, end_date):
        period_candidates = [
            candidate for published_day, candidate in dated if period_start <= published_day <= period_end
        ]
        result = run_pipeline(
            settings,
            period_end,
            force=force,
            candidates=period_candidates,
            window_start=period_start,
        )
        total_processed += len(result["processed"])
        total_failed += len(result["failed"])
        periods.append(result)
        print(
            f"[BACKFILL] {period_start:%Y%m%d}-{period_end:%Y%m%d}: "
            f"candidates={len(period_candidates)} processed={len(result['processed'])}"
        )
    return {
        "start": start_date.strftime("%Y%m%d"),
        "end": end_date.strftime("%Y%m%d"),
        "periods": periods,
        "processed": total_processed,
        "failed": total_failed,
    }


def process_single(settings: Settings, arxiv_id: str, force: bool = True) -> dict:
    candidate = fetch_by_id(settings, arxiv_id)
    accepted = deterministic_filter([candidate])
    if not accepted:
        raise RuntimeError("paper does not match light-field low-level vision rules")
    client = ArkClient(settings)
    classified = classify_with_llm(accepted, client)
    if not classified:
        raise RuntimeError("paper was rejected by semantic classification")
    date_key = datetime.now(settings.timezone).strftime("%Y%m%d")
    index_path = settings.root / "papers" / "index.json"
    index = load_index(index_path)
    if not _needs_processing(candidate, index["papers"], force):
        return index["papers"][candidate.base_id]
    github = GitHubStore(settings)
    record = process_candidate(settings, classified[0], date_key, index, client, github)
    index["papers"][candidate.base_id] = record
    now = datetime.now(settings.timezone)
    save_index(index_path, index, now)
    save_json(settings.root / "docs" / "data" / "index.json", public_payload(index))
    return record


def reconcile_date(settings: Settings, date_key: str) -> Path:
    index = load_index(settings.root / "papers" / "index.json")
    papers = [paper for paper in index["papers"].values() if date_key in paper.get("appeared_dates", [])]
    papers.sort(key=lambda item: item.get("rank_score", 0), reverse=True)
    target_date = datetime.strptime(date_key, "%Y%m%d").date()
    period_start = (target_date - timedelta(days=target_date.weekday())).strftime("%Y%m%d")
    content = build_weekly_report(
        date_key,
        papers[: settings.max_daily_papers],
        fetched_count=len(papers),
        hard_filtered_count=len(papers),
        period_start=period_start,
    )
    return write_daily_report(settings.root, date_key, content)


def prune_index(settings: Settings, apply: bool = False) -> dict:
    index_path = settings.root / "papers" / "index.json"
    index = load_index(index_path)
    excluded: list[dict[str, str]] = []
    affected_dates: set[str] = set()

    for base_id, record in list(index["papers"].items()):
        candidate = Candidate(
            arxiv_id=record.get("arxiv_id", base_id),
            title=record.get("title", ""),
            abstract=record.get("abstract", ""),
            authors=list(record.get("authors", [])),
            categories=list(record.get("categories", [])),
            published=record.get("published", ""),
            updated=record.get("updated", ""),
            pdf_url=record.get("pdf_url", ""),
        )
        tasks, reason = deterministic_classify(candidate)
        if tasks:
            continue
        excluded.append({"base_id": base_id, "title": candidate.title, "reason": reason})
        if not apply:
            continue

        affected_dates.update(record.get("appeared_dates", []))
        del index["papers"][base_id]
        cover_name = Path(record.get("cover_url", "")).name
        if cover_name:
            (settings.root / "docs" / "assets" / "previews" / cover_name).unlink(missing_ok=True)

    if apply and excluded:
        now = datetime.now(settings.timezone)
        save_index(index_path, index, now)
        save_json(settings.root / "docs" / "data" / "index.json", public_payload(index))
        for date_key in sorted(affected_dates):
            reconcile_date(settings, date_key)

    return {"apply": apply, "excluded": excluded, "affected_dates": sorted(affected_dates)}
