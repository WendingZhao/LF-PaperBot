from __future__ import annotations

import json
import random
import re
import time
import urllib.request
from urllib.error import HTTPError, URLError

from .config import Settings


class ArkError(RuntimeError):
    pass


class ArkClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.endpoint = f"{settings.ark_base_url}/chat/completions"

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        timeout: int = 300,
        retries: int = 3,
    ) -> str:
        if not self.settings.ark_api_key:
            raise ArkError("ARK_API_KEY is required")
        payload = {
            "model": self.settings.ark_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.ark_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "LF-PaperBot/0.1",
        }
        last_error = "unknown error"
        for attempt in range(retries):
            try:
                request = urllib.request.Request(
                    self.endpoint,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    request_id = response.headers.get("x-request-id", "-")
                    data = json.loads(response.read().decode("utf-8"))
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not isinstance(content, str) or not content.strip():
                    raise ArkError(f"empty response (request_id={request_id})")
                return content.strip()
            except HTTPError as exc:
                request_id = exc.headers.get("x-request-id", "-") if exc.headers else "-"
                last_error = f"HTTP {exc.code} (request_id={request_id})"
                if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == retries - 1:
                    raise ArkError(last_error) from exc
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                delay = int(retry_after) if retry_after.isdigit() else 2**attempt + random.random()
                time.sleep(min(delay, 30))
            except (URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, ArkError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt == retries - 1:
                    raise ArkError(last_error) from exc
                time.sleep(min(2**attempt + random.random(), 10))
        raise ArkError(last_error)

    def complete_json(self, prompt: str, **kwargs):
        raw = self.complete(prompt, **kwargs)
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.I)
        candidate = fenced.group(1) if fenced else raw
        start_positions = [pos for pos in (candidate.find("["), candidate.find("{")) if pos >= 0]
        if start_positions:
            candidate = candidate[min(start_positions) :]
        for end_char in ("]", "}"):
            end = candidate.rfind(end_char)
            if end >= 0:
                try:
                    return json.loads(candidate[: end + 1])
                except json.JSONDecodeError:
                    continue
        raise ArkError("model response did not contain valid JSON")
