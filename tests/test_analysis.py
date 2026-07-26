from __future__ import annotations

from lf_paperbot.analysis import classify_with_llm
from lf_paperbot.domain import deterministic_filter
from lf_paperbot.models import Candidate


def paper() -> Candidate:
    return Candidate(
        arxiv_id="2607.12345v1",
        title="Occlusion Removal for Light Field Images",
        abstract="We restore occluded regions using complementary angular observations.",
        authors=["A"],
        categories=["cs.CV"],
        published="2026-07-25T00:00:00Z",
        updated="2026-07-25T00:00:00Z",
        pdf_url="https://arxiv.org/pdf/2607.12345v1",
    )


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def complete_json(self, _prompt, **_kwargs):
        if self.error:
            raise self.error
        return self.payload


def test_semantic_classification_updates_scores():
    item = deterministic_filter([paper()])[0]
    result = classify_with_llm(
        [item],
        FakeClient(
            [
                {
                    "arxiv_id": item.arxiv_id,
                    "relevant": True,
                    "tasks": ["去遮挡"],
                    "relevance_score": 96,
                    "research_score": 0.8,
                    "experiment_score": 0.7,
                    "code_score": 0.4,
                    "evidence": "恢复被遮挡区域",
                    "exclude_reason": "",
                }
            ]
        ),
    )
    assert result == [item]
    assert item.relevance_score == 0.96
    assert item.tasks == ["去遮挡"]


def test_semantic_classification_can_reject_candidate():
    item = deterministic_filter([paper()])[0]
    result = classify_with_llm(
        [item],
        FakeClient(
            [
                {
                    "arxiv_id": item.arxiv_id,
                    "relevant": False,
                    "tasks": [],
                    "relevance_score": 0.2,
                    "exclude_reason": "主要任务是深度估计",
                }
            ]
        ),
    )
    assert result == []
