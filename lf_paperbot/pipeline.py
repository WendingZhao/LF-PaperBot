from __future__ import annotations

import copy
from datetime import date, datetime
from pathlib import Path

from .analysis import classify_with_llm, generate_report, rank_candidates, report_to_markdown
from .arxiv import download_pdf, fetch_by_id, fetch_recent
from .config import Settings
from .domain import deterministic_filter
from .github_store import GitHubStore
from .llm import ArkClient
from .models import Candidate
from .pdf_tools import extract_pdf_text, render_cover_webp, select_context
from .reporting import build_daily_report, write_daily_report
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


def run_pipeline(settings: Settings, target_date: date | None = None, force: bool = False) -> dict:
    date_key = _date_key(settings, target_date)
    index_path = settings.root / "papers" / "index.json"
    index = load_index(index_path)
    original_index = copy.deepcopy(index)
    fetched = fetch_recent(settings, target_date)
    hard_filtered = deterministic_filter(fetched)
    pending = [candidate for candidate in hard_filtered if _needs_processing(candidate, index["papers"], force)]
    client = ArkClient(settings)
    classified = classify_with_llm(pending, client)
    selected = rank_candidates(classified, settings.max_daily_papers)
    github = GitHubStore(settings)

    processed: list[dict] = []
    failed: list[str] = []
    for candidate in selected:
        try:
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
    daily = build_daily_report(
        date_key,
        processed,
        fetched_count=len(fetched),
        hard_filtered_count=len(hard_filtered),
        failed=failed,
    )
    report_path = write_daily_report(settings.root, date_key, daily)
    print(f"[DONE] {date_key}: {len(processed)} papers, report={report_path}")
    return {"date": date_key, "processed": processed, "failed": failed}


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
    content = build_daily_report(
        date_key,
        papers[: settings.max_daily_papers],
        fetched_count=len(papers),
        hard_filtered_count=len(papers),
    )
    return write_daily_report(settings.root, date_key, content)
