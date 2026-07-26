from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "Ark API key": re.compile(r"ark-[A-Za-z0-9][A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
}


def tracked_files() -> list[Path]:
    try:
        output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        return [ROOT / item.decode() for item in output.split(b"\0") if item]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [path for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.parts]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if not path.exists() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: possible {name}")
    if findings:
        print("\n".join(findings))
        return 1
    print("No credential-like strings found in tracked text files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
