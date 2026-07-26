from __future__ import annotations

import re

from .config import Settings
from .models import Candidate


MARKER = "<!-- lf-paperbot:arxiv={base_id} -->"
LABEL_COLORS = {
    "paper": "1f6feb",
    "空间超分": "8250df",
    "角度超分": "a371f7",
    "去噪": "2da44e",
    "去模糊": "bf8700",
    "低光增强": "d4a72c",
    "去遮挡": "cf222e",
    "去雨去雾": "0969da",
    "重建与插值": "1b7c83",
    "压缩恢复": "6e7781",
    "质量增强": "57606a",
}


class GitHubStore:
    def __init__(self, settings: Settings):
        if not settings.github_token:
            raise RuntimeError("GITHUB_TOKEN is required")
        try:
            from github import Auth, Github
        except ModuleNotFoundError as exc:
            raise RuntimeError("PyGithub is not installed; run pip install -r requirements.txt") from exc
        self.settings = settings
        self.client = Github(auth=Auth.Token(settings.github_token), timeout=30, retry=2)
        self.repo = self.client.get_repo(settings.github_repo)
        self._labels_ready = False

    def ensure_labels(self, date_key: str | None = None) -> None:
        if self._labels_ready and not date_key:
            return
        existing = {label.name for label in self.repo.get_labels()}
        for name, color in LABEL_COLORS.items():
            if name not in existing:
                self.repo.create_label(name=name, color=color)
                existing.add(name)
        if date_key and date_key not in existing:
            self.repo.create_label(name=date_key, color="d8dee4", description="LF-PaperBot report date")
        self._labels_ready = True

    def find_issue(self, base_id: str):
        marker = MARKER.format(base_id=base_id)
        for issue in self.repo.get_issues(state="all", sort="updated", direction="desc"):
            if marker in (issue.body or ""):
                return issue
            if re.search(rf"arxiv\.org/abs/{re.escape(base_id)}(?:v\d+)?\b", issue.body or "", re.I):
                return issue
        return None

    def upsert_paper_issue(self, candidate: Candidate, body: str, date_key: str):
        self.ensure_labels(date_key)
        issue = self.find_issue(candidate.base_id)
        labels = ["paper", date_key, *candidate.tasks]
        title = f"[{date_key}] {candidate.title}"
        marked_body = f"{MARKER.format(base_id=candidate.base_id)}\n{body}"
        if issue:
            date_labels = [label.name for label in issue.labels if re.fullmatch(r"\d{8}", label.name)]
            issue.edit(title=title, body=marked_body, labels=list(dict.fromkeys([*date_labels, *labels])))
            return issue, "updated"
        return self.repo.create_issue(title=title, body=marked_body, labels=labels), "created"
