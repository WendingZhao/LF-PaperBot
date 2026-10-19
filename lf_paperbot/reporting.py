from __future__ import annotations

from pathlib import Path


def build_weekly_report(
    date_key: str,
    papers: list[dict],
    *,
    fetched_count: int,
    hard_filtered_count: int,
    failed: list[str] | None = None,
    period_start: str | None = None,
    source_stats: dict | None = None,
) -> str:
    failed = failed or []
    period_start = period_start or date_key
    lines = [
        f"# 光场底层视觉周报 {period_start} — {date_key}",
        "",
        "> 聚焦普通光场图像的超分、恢复、重建、深度与视差估计及相关底层视觉任务。",
        "",
        "## 本周概况",
        "",
        f"- 统计周期：{period_start} 至 {date_key}",
        f"- 多来源抓取（去重后）：{fetched_count} 篇",
        f"- 关键词硬筛：{hard_filtered_count} 篇",
        f"- 最终精选：{len(papers)} 篇",
    ]
    for source, info in (source_stats or {}).items():
        status = {"ok": "成功", "failed": "不可用", "partial": "部分结果"}.get(info["status"], info["status"])
        lines.append(f"- 来源 {source}：{info['count']} 条，{status}" + (f"（{info['error']}）" if info.get("error") else ""))
    if any(x.get("status") != "ok" for x in (source_stats or {}).values()):
        lines.append("- 部分来源未完整获取，本期结果不代表完整检索。")
    if failed:
        lines.append(f"- 处理失败：{len(failed)} 篇（{'、'.join(failed)}）")
    lines.extend(["", "## 精选论文", ""])
    if not papers:
        lines.append("本周候选处理失败，尚无可发布论文。" if failed else "本周未检索到符合条件并通过质量检查的论文。")
    for number, paper in enumerate(papers, 1):
        update = " · **版本更新**" if paper.get("is_version_update") else ""
        tasks = " / ".join(paper.get("tasks", []))
        source = paper.get("source", "arxiv")
        url = paper.get("source_url") or f"https://arxiv.org/abs/{paper['arxiv_id']}"
        links = f"[{source}]({url})"
        if paper.get("pdf_url"):
            links += f" · [PDF]({paper['pdf_url']})"
        lines.extend(
            [
                f"### {number}. {paper['title']}",
                "",
                f"- **任务**：{tasks}",
                f"- **来源**：{' / '.join(paper.get('sources', [source]))}",
                f"- **材料范围**：{ {'abstract_only': '仅公开摘要', 'metadata_only': '仅题录'}.get(paper.get('content_scope'), '全文节选') }",
                f"- **收录依据**：{paper.get('date_basis', 'published')}（discovered 为首次发现，indexed 为新登记；不等于本周发表）",
                f"- **TL;DR**：{paper.get('report', {}).get('tldr', '暂无')}",
                f"- **入选理由**：{paper.get('evidence', '符合光场底层视觉筛选规则')}",
                f"- **综合分数**：{paper.get('rank_score', 0):.2f}{update}",
                f"- **链接**：{links} · [深度报告]({paper['issue_url']})",
                "",
            ]
        )
    lines.extend(
        [
            "---",
            "",
            "由 [LF-PaperBot](https://github.com/WendingZhao/LF-PaperBot) 自动生成。",
            "",
        ]
    )
    return "\n".join(lines)


build_daily_report = build_weekly_report


def write_daily_report(root: Path, date_key: str, content: str) -> Path:
    path = root / "daily_reports" / date_key[:6] / f"{date_key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
