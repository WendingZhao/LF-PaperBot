from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Candidate


TASK_PATTERNS: dict[str, tuple[str, ...]] = {
    "空间超分": (r"spatial super[- ]resolution", r"light[- ]field super[- ]resolution", r"\bsuper[- ]resolution\b"),
    "角度超分": (
        r"angular super[- ]resolution",
        r"angular resolution (?:enhancement|reconstruction)",
        r"view interpolation",
        r"sparse[- ]to[- ]dense (?:view|light[- ]field)",
    ),
    "去噪": (r"denois", r"noise removal", r"noisy light[- ]field"),
    "去模糊": (r"deblur", r"blur removal", r"motion blur"),
    "低光增强": (r"low[- ]light", r"illumination enhancement", r"dark light[- ]field"),
    "去遮挡": (
        r"occlusion removal",
        r"de[- ]?occlusion",
        r"disocclusion restoration",
        r"occlusion[- ]aware restoration",
        r"occluded light[- ]field reconstruction",
        r"restore[^.]{0,80}occlud",
    ),
    "去雨去雾": (r"dehaz", r"derain", r"fog removal", r"rain removal"),
    "重建与插值": (
        r"light[- ]field reconstruction",
        r"light[- ]field interpolation",
        r"sparse[- ]view reconstruction",
        r"dense light[- ]field synthesis",
        r"light[- ]field completion",
        r"sub[- ]aperture view synthesis",
    ),
    "深度与视差估计": (
        r"light[- ]field depth estimation",
        r"light[- ]field disparity estimation",
        r"\bdepth estimation\b",
        r"\bdisparity estimation\b",
        r"depth (?:estimation )?from light[- ]fields?",
        r"disparity (?:estimation )?from light[- ]fields?",
        r"depth map estimation[^.]{0,80}light[- ]field",
    ),
    "重聚焦": (r"light[- ]field refocus", r"light[- ]field refocusing", r"digital refocusing"),
    "压缩恢复": (r"compression artifact", r"light[- ]field compression", r"compressed light[- ]field"),
    "质量增强": (r"light[- ]field enhancement", r"quality enhancement", r"light[- ]field restoration"),
}

LF_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\blight[- ]field(?:s)?\b",
        r"\bplenoptic\b",
        r"\bspatial[- ]angular\b",
        r"\bangular dimension\b",
        r"\bepipolar plane image\b",
        r"\blenslet(?: camera| image)?\b",
        r"\bmicro[- ]lens array\b",
        r"\bsub[- ]aperture (?:image|view)s?\b",
    )
)

TASK_REGEX = {
    task: tuple(re.compile(pattern, re.I) for pattern in patterns)
    for task, patterns in TASK_PATTERNS.items()
}

HARD_EXCLUSIONS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\bclassification\b",
        r"\bsemantic segmentation\b",
        r"\bobject detection\b",
        r"\blight[- ]field display\b",
        r"\bholographic display\b",
    )
)

NON_STANDARD_LF = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\bevent[- ]based\b",
        r"\bevent camera\b",
        r"\bevent stream\b",
        r"\bneuromorphic\b",
        r"\blight[- ]field microscopy\b",
        r"\bmicroscopic light[- ]field\b",
        r"\bplenoptic microscopy\b",
        r"\bacoustic light[- ]field\b",
        r"\btransient light[- ]field\b",
        r"\bx[- ]ray\b",
        r"\bcomputed tomography\b",
    )
)

GENERIC_3D = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"\bneural radiance field",
        r"\bNeRF\b",
        r"\b3D Gaussian Splatting\b",
        r"\bnovel view synthesis\b",
        r"\bneural rendering\b",
    )
)


def _any(patterns: Iterable[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def deterministic_classify(candidate: Candidate) -> tuple[list[str], str]:
    text = f"{candidate.title}\n{candidate.abstract}"
    if not _any(LF_PATTERNS, text):
        return [], "缺少明确光场成像证据"

    tasks = [task for task, patterns in TASK_REGEX.items() if _any(patterns, text)]
    if not tasks:
        return [], "缺少普通光场图像底层视觉任务证据"

    if _any(HARD_EXCLUSIONS, text):
        return [], "论文主要任务属于识别、分割、检测或显示"

    if _any(NON_STANDARD_LF, text):
        return [], "论文对象不是普通相机采集的光场图像"
    if _any(GENERIC_3D, text):
        return [], "论文主要任务是通用 NeRF、3DGS 或新视点生成"

    return tasks, ""


def fallback_score(candidate: Candidate) -> Candidate:
    tasks, reason = deterministic_classify(candidate)
    candidate.tasks = tasks
    candidate.exclude_reason = reason
    if tasks:
        candidate.relevance_score = min(1.0, 0.78 + 0.04 * min(len(tasks), 4))
        candidate.research_score = 0.55
        candidate.experiment_score = 0.50
        candidate.code_score = 0.35 if re.search(r"github\.com|code (?:is|will be)", candidate.abstract, re.I) else 0.1
        candidate.evidence = f"标题或摘要明确命中：{'、'.join(tasks)}"
    return candidate


def deterministic_filter(candidates: Iterable[Candidate]) -> list[Candidate]:
    accepted: list[Candidate] = []
    for candidate in candidates:
        fallback_score(candidate)
        if candidate.tasks:
            accepted.append(candidate)
    return accepted
