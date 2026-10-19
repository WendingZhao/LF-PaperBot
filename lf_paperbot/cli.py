from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import fields, replace
from pathlib import Path
from datetime import datetime

from .analysis import classify_with_llm, rank_candidates
from .public_sources import fetch_recent
from .config import load_settings
from .domain import deterministic_filter
from .llm import ArkClient, ArkError
from .pdf_tools import require_poppler
from .pipeline import process_single, prune_index, reconcile_date, run_backfill, run_pipeline


def _parse_date(value: str | None):
    return datetime.strptime(value, "%Y%m%d").date() if value else None


def doctor_command(_args) -> int:
    settings = load_settings()
    checks: list[tuple[str, bool, str]] = [
        ("Python", sys.version_info >= (3, 10), sys.version.split()[0]),
        ("DEEPSEEK_API_KEY", bool(settings.ark_api_key), "set" if settings.ark_api_key else "missing"),
        ("GITHUB_TOKEN", bool(settings.github_token), "set" if settings.github_token else "missing"),
        ("DEEPSEEK_BASE_URL", settings.ark_base_url.startswith("https://"), settings.ark_base_url),
    ]
    for binary in ("pdftotext", "pdftoppm"):
        location = shutil.which(binary)
        checks.append((binary, bool(location), location or "missing"))
    try:
        import github  # noqa: F401
        github_ok = True
    except ModuleNotFoundError:
        github_ok = False
    checks.append(("PyGithub", github_ok, "installed" if github_ok else "missing"))

    api_ok = False
    api_detail = "skipped because DEEPSEEK_API_KEY is missing"
    if settings.ark_api_key:
        try:
            reply = ArkClient(settings).complete(
                "只回复字符串 LF-PAPERBOT-OK，不要输出其他内容。",
                max_tokens=512,
                timeout=60,
                retries=2,
            )
            api_ok = "LF-PAPERBOT-OK" in reply.upper()
            api_detail = "compatible response received" if api_ok else "unexpected response"
        except ArkError as exc:
            api_detail = str(exc)
    checks.append(("Ark API", api_ok, api_detail))

    for name, ok, detail in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def fetch_command(args) -> int:
    settings = load_settings()
    candidates = fetch_recent(settings, _parse_date(args.date))
    filtered = deterministic_filter(candidates)
    if settings.ark_api_key and not args.no_llm:
        filtered = classify_with_llm(filtered, ArkClient(settings))
    selected = rank_candidates(filtered, settings.max_daily_papers)
    print(f"fetched={len(candidates)} hard_filtered={len(filtered)} selected={len(selected)}")
    for item in selected:
        print(
            json.dumps(
                {
                    "arxiv_id": item.arxiv_id,
                    "source": item.source,
                    "source_url": item.paper_url,
                    "doi": item.doi,
                    "title": item.title,
                    "tasks": item.tasks,
                    "rank_score": item.rank_score,
                    "evidence": item.evidence,
                },
                ensure_ascii=False,
            )
        )
    return 0


def run_command(args) -> int:
    settings = load_settings()
    missing = require_poppler()
    if missing:
        raise RuntimeError(f"missing system dependencies: {', '.join(missing)}")
    if not settings.ark_api_key or not settings.github_token:
        raise RuntimeError("DEEPSEEK_API_KEY and GITHUB_TOKEN are required")
    result = run_pipeline(settings, _parse_date(args.date), force=args.force)
    if result["failed"]:
        print(f"WARN: {len(result['failed'])} paper(s) failed; successful artifacts were preserved")
    return 0


def backfill_command(args) -> int:
    settings = load_settings()
    missing = require_poppler()
    if missing:
        raise RuntimeError(f"missing system dependencies: {', '.join(missing)}")
    if not settings.ark_api_key or not settings.github_token:
        raise RuntimeError("DEEPSEEK_API_KEY and GITHUB_TOKEN are required")
    start_date = _parse_date(args.start)
    end_date = _parse_date(args.end) or datetime.now(settings.timezone).date()
    if args.monthly:
        from .backfill_batches import run_monthly_backfill
        result = run_monthly_backfill(settings, start_date, end_date, force=args.force,
                                      all_papers=args.all_papers, commit=args.commit,
                                      candidate_file=Path(args.candidate_file) if args.candidate_file else None)
    else:
        if args.commit or args.candidate_file:
            raise ValueError("--commit and --candidate-file require --monthly")
        result = run_backfill(settings, start_date, end_date, force=args.force, all_papers=args.all_papers)
    print(
        f"backfill={result['start']}..{result['end']} periods={len(result['periods'])} "
        f"processed={result['processed']} failed={result['failed']}"
    )
    if result["failed"]:
        print(f"WARN: {result['failed']} paper(s) failed; successful artifacts were preserved")
    if result.get("incomplete_batches"):
        print("INCOMPLETE_BATCHES=" + ",".join(result["incomplete_batches"]))
        return 1
    return 0


def paper_command(args) -> int:
    record = process_single(load_settings(), args.arxiv_id, force=not args.no_force)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def discover_command(args) -> int:
    from .public_sources import deduplicate, fetch_sources
    from .models import Candidate
    from .storage import save_json
    settings = load_settings()
    if args.sources:
        settings = replace(settings, sources=tuple(x.strip() for x in args.sources.split(",") if x.strip()))
    start = _parse_date(args.start)
    end = _parse_date(args.end) or datetime.now(settings.timezone).date()
    allowed = {f.name for f in fields(Candidate)}
    if getattr(args, "import_file", None):
        incoming = json.loads(Path(args.import_file).read_text(encoding="utf-8"))
        if incoming.get("start") != str(start) or incoming.get("end") != str(end):
            raise ValueError("Imported discovery file has a different date range")
        candidates = [Candidate(**{k: v for k, v in record.items() if k in allowed})
                      for record in incoming["candidates"]]
        stats = incoming["sources"]
    else:
        candidates, stats = fetch_sources(settings, end, start_date=start, historical=True, require_any=False)
    output = Path(args.output)
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous.get("start") != str(start) or previous.get("end") != str(end):
            raise ValueError("Existing discovery file has a different date range; choose another output path")
        old_candidates = [Candidate(**{k: v for k, v in record.items() if k in allowed})
                          for record in previous.get("candidates", [])]
        candidates = deduplicate([*old_candidates, *candidates])
        old_stats = previous.get("sources", {})
        for name, info in stats.items():
            if old_stats.get(name, {}).get("status") == "ok" and info["status"] != "ok":
                continue
            old_stats[name] = info
        stats = old_stats
    save_json(Path(args.output), {"start": str(start), "end": str(end),
                                 "sources": stats, "candidates": [c.to_dict() for c in candidates]})
    print(f"[DISCOVERY] {len(candidates)} candidates saved to {args.output}")
    return 0 if all(s["status"] == "ok" for s in stats.values()) else 1


def reconcile_command(args) -> int:
    path = reconcile_date(load_settings(), args.date)
    print(path)
    return 0


def prune_command(args) -> int:
    result = prune_index(load_settings(), apply=args.apply)
    mode = "applied" if args.apply else "preview"
    print(f"prune={mode} excluded={len(result['excluded'])}")
    for item in result["excluded"]:
        print(json.dumps(item, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LF-PaperBot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="检查运行环境和方舟接口")
    doctor.set_defaults(func=doctor_command)

    fetch = subparsers.add_parser("fetch", help="抓取并预览候选")
    fetch.add_argument("--dry-run", action="store_true", help="兼容参数；fetch 始终不写入远端")
    fetch.add_argument("--date", help="目标日期 YYYYMMDD")
    fetch.add_argument("--no-llm", action="store_true", help="只运行确定性筛选")
    fetch.set_defaults(func=fetch_command)

    run = subparsers.add_parser("run", help="执行每周完整流水线")
    run.add_argument("--date", help="目标日期 YYYYMMDD")
    run.add_argument("--force", action="store_true", help="强制重新处理已有版本")
    run.set_defaults(func=run_command)

    backfill = subparsers.add_parser("backfill", help="按自然周回填历史论文")
    backfill.add_argument("--start", default="20260101", help="起始日期 YYYYMMDD")
    backfill.add_argument("--end", help="结束日期 YYYYMMDD，默认今天")
    backfill.add_argument("--force", action="store_true", help="强制重新处理已有版本")
    backfill.add_argument("--all", dest="all_papers", action="store_true", help="历史全量收录，取消每周精选数量上限，保留仅题录论文")
    backfill.add_argument("--monthly", action="store_true", help="按月分批检索并保存断点，重跑时跳过已完成月份")
    backfill.add_argument("--commit", action="store_true", help="每月完成后提交和推送生成数据（需 --monthly）")
    backfill.add_argument("--candidate-file", help="使用已保存的公开元数据快照（需 --monthly），避免重复抓取")
    backfill.set_defaults(func=backfill_command)

    discover = subparsers.add_parser("discover", help="无 Key 抓取历史公开元数据并保存快照")
    discover.add_argument("--start", required=True, help="YYYYMMDD")
    discover.add_argument("--end", help="YYYYMMDD，默认今天")
    discover.add_argument("--output", required=True, help="候选快照 JSON 输出文件")
    discovery_mode = discover.add_mutually_exclusive_group()
    discovery_mode.add_argument("--sources", help="只重试指定来源，如 arxiv 或 crossref,cvf；自动合并同范围现有快照")
    discovery_mode.add_argument("--import-file", help="合并同范围的公开题录快照，不重新请求网络")
    discover.set_defaults(func=discover_command)

    paper = subparsers.add_parser("paper", help="处理单篇 arXiv 论文")
    paper.add_argument("arxiv_id")
    paper.add_argument("--no-force", action="store_true")
    paper.set_defaults(func=paper_command)

    reconcile = subparsers.add_parser("reconcile", help="根据索引重建指定周报")
    reconcile.add_argument("--date", required=True, help="YYYYMMDD")
    reconcile.set_defaults(func=reconcile_command)

    prune = subparsers.add_parser("prune", help="按当前领域规则检查并清理历史索引")
    prune.add_argument("--apply", action="store_true", help="应用清理；默认只预览")
    prune.set_defaults(func=prune_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
