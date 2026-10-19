from __future__ import annotations

import re
import hashlib
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any


VERSION_RE = re.compile(r"^(?P<base>\d{4}\.\d{4,5})(?:v(?P<version>\d+))?$")


def normalize_title(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def normalize_doi(value: str) -> str:
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I).lower()


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
    source: str = "arxiv"
    source_url: str = ""
    doi: str = ""
    venue: str = ""
    publication_year: int = 0
    date_basis: str = "published"
    sources: list[str] = field(default_factory=list)
    alternate_pdf_urls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.doi = normalize_doi(self.doi)
        if self.source != "arxiv" and not self.arxiv_id:
            identity = self.doi or self.source_url or normalize_title(self.title)
            self.arxiv_id = f"{self.source}-{hashlib.sha256(identity.encode()).hexdigest()[:20]}"
        if not self.base_id:
            self.base_id, self.version = split_arxiv_id(self.arxiv_id)
        if not self.source_url and self.source == "arxiv":
            self.source_url = f"https://arxiv.org/abs/{self.arxiv_id}"
        self.sources = list(dict.fromkeys([self.source, *self.sources]))

    @property
    def paper_url(self) -> str:
        return self.source_url or (f"https://doi.org/{self.doi}" if self.doi else "")

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
