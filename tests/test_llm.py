from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import pytest

from lf_paperbot.config import Settings
from lf_paperbot.llm import ArkClient, ArkError


def settings(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        ark_base_url="https://example.test/api/coding/v3",
        ark_api_key="test-key-placeholder",
        ark_model="ark-code-latest",
        github_token="test-token-placeholder",
        github_repo="owner/repo",
        max_daily_papers=5,
        timezone=ZoneInfo("Asia/Shanghai"),
        lookback_days=3,
        arxiv_api_url="https://example.test/arxiv",
        arxiv_user_agent="test",
        temp_dir=tmp_path / "tmp",
    )


class FakeResponse:
    def __init__(self, content: str):
        self.headers = {"x-request-id": "test-request"}
        self.body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retries_transient_http_errors(monkeypatch, tmp_path, status):
    responses = [
        HTTPError(
            "https://example.test",
            status,
            "transient",
            {"x-request-id": "failed-request", "Retry-After": "0"},
            io.BytesIO(),
        ),
        FakeResponse("ok"),
    ]

    def fake_urlopen(*_args, **_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("lf_paperbot.llm.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("lf_paperbot.llm.time.sleep", lambda _seconds: None)
    assert ArkClient(settings(tmp_path)).complete("test", retries=2) == "ok"
    assert responses == []


def test_extracts_json_from_markdown_fence(monkeypatch, tmp_path):
    client = ArkClient(settings(tmp_path))
    monkeypatch.setattr(client, "complete", lambda *_args, **_kwargs: '```json\n[{"relevant": true}]\n```')
    assert client.complete_json("test") == [{"relevant": True}]


def test_retries_invalid_json_with_zero_temperature(monkeypatch, tmp_path):
    client = ArkClient(settings(tmp_path))
    responses = iter(["not-json", '{"relevant": true}'])
    calls = []

    def fake_complete(*_args, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(client, "complete", fake_complete)
    assert client.complete_json("test") == {"relevant": True}
    assert calls == [{}, {"temperature": 0.0}]


def test_invalid_json_fails_after_bounded_retries(monkeypatch, tmp_path):
    client = ArkClient(settings(tmp_path))
    calls = []

    def fake_complete(*_args, **kwargs):
        calls.append(kwargs)
        return "not-json"

    monkeypatch.setattr(client, "complete", fake_complete)
    with pytest.raises(ArkError, match="valid JSON"):
        client.complete_json("test", json_retries=2)
    assert len(calls) == 2
