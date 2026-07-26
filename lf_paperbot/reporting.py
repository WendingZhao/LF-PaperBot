from __future__ import annotations

from pathlib import Path


def build_daily_report(
    date_key: str,
    papers: list[dict],
    *,
    fetched_count: int,
    hard_filtered_count: int,
    failed: list[str] | None = None,
) -> str:
    failed = failed or []
    lines = [
        f"# 光场底层视觉日报 {date_key}",
        "",
        "> 聚焦光场超分、去噪、去模糊、低光增强、去遮挡及相关恢复增强任务。",
        "",
        "## 今日概况",
        "",
        f"- arXiv 抓取：{fetched_count} 篇",
        f"- 关键词硬筛：{hard_filtered_count} 篇",
        f"- 最终精选：{len(papers)} 篇",
    ]
    if failed:
        lines.append(f"- 处理失败：{len(failed)} 篇（{'、'.join(failed)}）")
    lines.extend(["", "## 精选论文", ""])
    if not papers:
        lines.append("当日未检索到符合条件并通过质量检查的论文。")
    for number, paper in enumerate(papers, 1):
        update = " · **版本更新**" if paper.get("is_version_update") else ""
        tasks = " / ".join(paper.get("tasks", []))
        lines.extend(
            [
                f"### {number}. {paper['title']}",
                "",
                f"- **任务**：{tasks}",
                f"- **TL;DR**：{paper.get('report', {}).get('tldr', '暂无')} ",
                f"- **入选理由**：{paper.get('evidence', '符合光场底层视觉筛选规则')}",
                f"- **综合分数**：{paper.get('rank_score', 0):.2f}{update}",
                f"- **链接**：[arXiv](https://arxiv.org/abs/{paper['arxiv_id']}) · [PDF]({paper['pdf_url']}) · [深度报告]({paper['issue_url']})",
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


def write_daily_report(root: Path, date_key: str, content: str) -> Path:
    path = root / "daily_reports" / date_key[:6] / f"{date_key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
