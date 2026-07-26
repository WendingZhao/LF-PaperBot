from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    root: Path
    ark_base_url: str
    ark_api_key: str
    ark_model: str
    github_token: str
    github_repo: str
    max_daily_papers: int
    timezone: ZoneInfo
    lookback_days: int
    arxiv_api_url: str
    arxiv_user_agent: str
    temp_dir: Path


def load_settings() -> Settings:
    base_url = _env("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3").rstrip("/")
    return Settings(
        root=ROOT,
        ark_base_url=base_url,
        ark_api_key=_env("ARK_API_KEY"),
        ark_model=_env("ARK_MODEL", "ark-code-latest"),
        github_token=_env("GITHUB_TOKEN"),
        github_repo=_env("LF_GITHUB_REPO", "WendingZhao/LF-PaperBot"),
        max_daily_papers=max(1, min(20, int(_env("LF_MAX_DAILY_PAPERS", "5")))),
        timezone=ZoneInfo(_env("LF_TIMEZONE", "Asia/Shanghai")),
        lookback_days=max(1, min(14, int(_env("LF_LOOKBACK_DAYS", "7")))),
        arxiv_api_url=_env("ARXIV_API_URL", "https://export.arxiv.org/api/query"),
        arxiv_user_agent=_env(
            "ARXIV_USER_AGENT",
            "LF-PaperBot/0.1 (+https://github.com/WendingZhao/LF-PaperBot)",
        ),
        temp_dir=ROOT / "tmp",
    )
