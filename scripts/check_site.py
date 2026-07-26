from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Parser(HTMLParser):
    def error(self, message):
        raise RuntimeError(message)


def main() -> int:
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    Parser().feed(html)
    data = json.loads((ROOT / "docs" / "data" / "index.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert isinstance(data["papers"], list)
    assert "LF-PaperBot" in html
    assert "去遮挡" in html
    print("Static site structure is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
