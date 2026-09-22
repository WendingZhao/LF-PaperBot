from __future__ import annotations

from lf_paperbot.config import load_settings


def test_deepseek_environment_takes_precedence_over_legacy_ark(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setenv("ARK_API_KEY", "legacy-key")
    monkeypatch.setenv("ARK_BASE_URL", "https://legacy.example")
    monkeypatch.setenv("ARK_MODEL", "legacy-model")

    settings = load_settings()

    assert settings.ark_api_key == "deepseek-test-key"
    assert settings.ark_base_url == "https://api.deepseek.com"
    assert settings.ark_model == "deepseek-flash"
