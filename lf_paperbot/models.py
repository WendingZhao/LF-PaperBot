from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


VERSION_RE = re.compile(r"^(?P<base>\d{4}\.\d{4,5})(?:v(?P<version>\d+))?$")


def split_arxiv_id(arxiv_id: str) -> tuple[str, int]:
    value = arxiv_id.rsplit("/", 1)[-1].strip()
    match = VERSION_RE.match(value)
    if not match:
        return value, 1
    return match.group("base"), int(match.group("version") or 1)


@dataclass
class Candidate:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    published: str
    updated: str
    pdf_url: str
    base_id: str = ""
    version: int = 1
    tasks: list[str] = field(default_factory=list)
    relevance_score: float = 0.0
    research_score: float = 0.0
    experiment_score: float = 0.0
    code_score: float = 0.0
    evidence: str = ""
    exclude_reason: str = ""

    def __post_init__(self) -> None:
        if not self.base_id:
            self.base_id, self.version = split_arxiv_id(self.arxiv_id)

    @property
    def rank_score(self) -> float:
        return round(
            0.60 * self.relevance_score
            + 0.20 * self.research_score
            + 0.15 * self.experiment_score
            + 0.05 * self.code_score,
            4,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["rank_score"] = self.rank_score
        return data
