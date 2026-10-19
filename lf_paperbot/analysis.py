from __future__ import annotations

import json
import re
from collections.abc import Iterable

from .domain import fallback_score
from .llm import ArkClient, ArkError
from .models import Candidate


ALLOWED_TASKS = {
    "空间超分",
    "角度超分",
    "去噪",
    "去模糊",
    "低光增强",
    "去遮挡",
    "去雨去雾",
    "重建与插值",
    "深度与视差估计",
    "重聚焦",
    "压缩恢复",
    "质量增强",
}


def _score(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1:
        number /= 100
    return max(0.0, min(1.0, number))


def _classification_prompt(candidates: list[Candidate]) -> str:
    compact = [
        {
            "arxiv_id": item.arxiv_id,
            "title": item.title,
            "abstract": item.abstract[:1800],
            "hard_filter_tasks": item.tasks,
        }
        for item in candidates
    ]
    return f"""你是光场图像底层视觉论文筛选专家。请判断候选论文是否应进入每周精选。

纳入普通相机或标准微透镜/多相机阵列采集的光场图像底层视觉，包括空间/角度超分、去噪、去模糊、低光增强、去遮挡、去雨去雾、稠密光场重建与视图插值、深度/视差估计、重聚焦、压缩伪影去除和质量增强。
深度或视差估计必须明确利用光场的多视角、EPI、焦点堆栈或空间—角度结构；通用单幅/双目深度方法不纳入。
排除事件相机光场、光场显微、声学/瞬态/X 射线光场等非普通图像模态，以及分类分割、光场显示、通用 NeRF、3DGS、神经渲染和以通用新视点生成为主要目标的论文。
去遮挡必须以恢复遮挡内容、利用多视角互补或改善遮挡区域质量为主；仅将遮挡作为其他任务中的常规机制时不要标记“去遮挡”。

返回严格 JSON 数组，每项字段如下：
- arxiv_id: 字符串
- relevant: 布尔值
- tasks: 仅从 {sorted(ALLOWED_TASKS)} 中选择
- relevance_score, research_score, experiment_score, code_score: 0 到 1
- evidence: 标题或摘要中的直接证据，中文一句话
- exclude_reason: 排除时填写中文原因，否则为空字符串

不要输出 Markdown 或额外说明。候选：
{json.dumps(compact, ensure_ascii=False)}"""


def classify_with_llm(candidates: list[Candidate], client: ArkClient) -> list[Candidate]:
    if not candidates:
        return []
    if len(candidates) > 10:
        return [item for start in range(0, len(candidates), 10)
                for item in classify_with_llm(candidates[start:start + 10], client)]
    by_id = {candidate.arxiv_id: candidate for candidate in candidates}
    try:
        payload = client.complete_json(_classification_prompt(candidates), max_tokens=3000, timeout=180)
        if not isinstance(payload, list):
            raise ArkError("classification response must be a JSON array")
    except ArkError as exc:
        print(f"[WARN] LLM classification failed; deterministic fallback enabled: {exc}")
        return candidates

    seen: set[str] = set()
    accepted: list[Candidate] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        candidate = by_id.get(str(item.get("arxiv_id", "")))
        if not candidate:
            continue
        seen.add(candidate.arxiv_id)
        tasks = [str(task) for task in item.get("tasks", []) if str(task) in ALLOWED_TASKS]
        candidate.relevance_score = _score(item.get("relevance_score"))
        candidate.research_score = _score(item.get("research_score"))
        candidate.experiment_score = _score(item.get("experiment_score"))
        candidate.code_score = _score(item.get("code_score"))
        candidate.evidence = str(item.get("evidence", "")).strip()[:500]
        candidate.exclude_reason = str(item.get("exclude_reason", "")).strip()[:500]
        if item.get("relevant") is True and tasks and candidate.relevance_score >= 0.65:
            candidate.tasks = tasks
            accepted.append(candidate)

    for candidate in candidates:
        if candidate.arxiv_id not in seen:
            fallback_score(candidate)
            accepted.append(candidate)
    return accepted


def rank_candidates(candidates: Iterable[Candidate], limit: int) -> list[Candidate]:
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        current = unique.get(candidate.base_id)
        if current is None or (candidate.version, candidate.rank_score) > (current.version, current.rank_score):
            unique[candidate.base_id] = candidate
    return sorted(
        unique.values(),
        key=lambda item: (item.rank_score, item.relevance_score, item.updated),
        reverse=True,
    )[:limit]


REPORT_FIELDS = (
    "tldr",
    "problem",
    "modeling",
    "method",
    "occlusion",
    "experiments",
    "resources",
    "limitations",
    "insight",
)


def generate_report(candidate: Candidate, context: str, client: ArkClient, *, content_scope: str = "full_text") -> dict[str, str]:
    prompt = f"""你是光场图像底层视觉研究专家。根据论文材料生成精炼、可核验的中文分析。

要求：
1. 只依据材料，不得编造数据、代码链接或结论；缺失信息明确写“论文材料未说明”。
2. 总长度约 1200–1800 中文字。
3. 实验部分尽量给出数据集、PSNR、SSIM、LPIPS、参数量和速度等原文结果。
4. 如果任务涉及去遮挡，说明视角互补、几何先验、遮挡掩码或遮挡区域恢复机制；不涉及则写“不适用”。
5. 如果任务涉及深度/视差估计，说明 EPI、焦点线索、遮挡边界、代价体或空间—角度对应关系，并报告常用误差指标。
6. 返回严格 JSON 对象，所有值均为字符串，字段必须为：{list(REPORT_FIELDS)}。
7. 材料范围为 {content_scope}。如果是 abstract_only，仅写摘要支持的事实；方法细节、实验数值和复现信息未说明时直接标注，不为凑字数补写。首句必须说明“仅基于公开摘要，未读取全文”。

论文元信息：
标题：{candidate.title}
作者：{', '.join(candidate.authors)}
任务：{'、'.join(candidate.tasks)}
摘要：{candidate.abstract}

论文正文节选：
{context}
"""
    payload = client.complete_json(prompt, max_tokens=5000, timeout=360)
    if not isinstance(payload, dict):
        raise ArkError("report response must be a JSON object")
    report = {field: str(payload.get(field, "")).strip() for field in REPORT_FIELDS}
    missing = [field for field, value in report.items() if not value]
    if missing:
        raise ArkError(f"report missing fields: {', '.join(missing)}")
    return report


def report_to_markdown(candidate: Candidate, report: dict[str, str], image_url: str, *, content_scope: str = "full_text") -> str:
    authors = ", ".join(candidate.authors) or "论文材料未说明"
    image = f"![论文首页]({image_url})" if image_url else "无公开全文首页预览。"
    version = f"v{candidate.version}" if candidate.source == "arxiv" else "正式发表版"
    source_link = f"[{candidate.source}]({candidate.paper_url})"
    if candidate.pdf_url:
        source_link += f" · [PDF]({candidate.pdf_url})"
    scope = {"full_text": "全文节选", "abstract_only": "仅公开摘要，未读取全文", "metadata_only": "仅题录，未获取摘要或全文"}[content_scope]
    return f"""# {candidate.title}

## 基础信息

| 项目 | 内容 |
|---|---|
| 来源 | {source_link} |
| DOI | {candidate.doi or '未提供'} |
| 会议/期刊 | {candidate.venue or '未提供'} |
| 分析依据 | {scope} |
| 版本 | {version} |
| 作者 | {authors} |
| 发布时间 | {candidate.published[:10] or candidate.publication_year or '未提供精确日期'} |
| 收录依据 | {candidate.date_basis} |
| 更新时间 | {candidate.updated[:10]} |
| 任务 | {'、'.join(candidate.tasks)} |
| 综合分数 | {candidate.rank_score:.2f} |

## 一句话结论

{report['tldr']}

## 任务与退化模型

{report['problem']}

## 输入输出与空间—角度建模

{report['modeling']}

## 核心方法与创新

{report['method']}

## 去遮挡机制

{report['occlusion']}

## 实验、数据集与指标

{report['experiments']}

## 代码、模型与数据

{report['resources']}

## 局限与复现风险

{report['limitations']}

## 研究启发

{report['insight']}

## 论文首页

{image}

---

由 LF-PaperBot 自动生成。报告可能存在模型误判，请以论文原文为准。
"""
