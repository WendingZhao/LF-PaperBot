from __future__ import annotations

import pytest

from lf_paperbot.analysis import rank_candidates
from lf_paperbot.domain import deterministic_classify, deterministic_filter
from lf_paperbot.models import Candidate, split_arxiv_id


def candidate(title: str, abstract: str = "") -> Candidate:
    return Candidate(
        arxiv_id="2607.12345v1",
        title=title,
        abstract=abstract,
        authors=["A. Author"],
        categories=["cs.CV"],
        published="2026-07-25T00:00:00Z",
        updated="2026-07-25T00:00:00Z",
        pdf_url="https://arxiv.org/pdf/2607.12345v1",
    )


@pytest.mark.parametrize(
    ("title", "task"),
    [
        ("Light Field Image Super-Resolution with Angular Priors", "空间超分"),
        ("Spatial-Angular Light Field Denoising", "去噪"),
        ("Light-Field Deblurring under Camera Motion", "去模糊"),
        ("Low-Light Light Field Enhancement", "低光增强"),
        ("Occlusion Removal for Light Field Images", "去遮挡"),
        ("De-occlusion via Multi-view Complementarity in Light Fields", "去遮挡"),
        ("Light Field Dehazing and Quality Enhancement", "去雨去雾"),
        ("Artifact Removal for Compressed Light Fields", "压缩恢复"),
    ],
)
def test_accepts_supported_light_field_restoration_tasks(title, task):
    tasks, reason = deterministic_classify(candidate(title))
    assert task in tasks
    assert reason == ""


@pytest.mark.parametrize(
    "title",
    [
        "Single Image Super-Resolution with Transformers",
        "Occlusion-Aware Light Field Depth Estimation",
        "Semantic Segmentation for Light Field Images with Restoration Features",
        "NeRF for Light Field Novel View Synthesis and Reconstruction",
        "A Holographic Light Field Display with Quality Enhancement",
    ],
)
def test_rejects_out_of_scope_papers(title):
    tasks, reason = deterministic_classify(candidate(title))
    assert tasks == []
    assert reason


def test_depth_is_allowed_only_when_restoration_is_primary():
    item = candidate(
        "Light Field De-occlusion with Disparity Guidance",
        "We restore occluded regions using disparity as an auxiliary geometric prior.",
    )
    tasks, reason = deterministic_classify(item)
    assert "去遮挡" in tasks
    assert reason == ""


def test_arxiv_version_normalization():
    assert split_arxiv_id("2607.12345v3") == ("2607.12345", 3)
    assert split_arxiv_id("https://arxiv.org/abs/2607.12345") == ("2607.12345", 1)


def test_ranking_deduplicates_base_id_and_limits_results():
    items = []
    for index in range(7):
        item = candidate(f"Light Field Denoising {index}")
        item.arxiv_id = f"2607.{12000 + index}v1"
        item.base_id, item.version = split_arxiv_id(item.arxiv_id)
        item.tasks = ["去噪"]
        item.relevance_score = 0.8 + index / 100
        item.research_score = 0.5
        items.append(item)
    duplicate = candidate("Light Field Denoising Updated")
    duplicate.arxiv_id = "2607.12000v2"
    duplicate.base_id, duplicate.version = split_arxiv_id(duplicate.arxiv_id)
    duplicate.tasks = ["去噪"]
    duplicate.relevance_score = 1.0
    duplicate.research_score = 0.9
    items.append(duplicate)
    selected = rank_candidates(deterministic_filter(items), 5)
    assert len(selected) == 5
    assert len({item.base_id for item in selected}) == 5
    assert next(item for item in selected if item.base_id == "2607.12000").version == 2
