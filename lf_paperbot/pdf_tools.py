from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image


def require_poppler() -> list[str]:
    return [name for name in ("pdftotext", "pdftoppm") if not shutil.which(name)]


def extract_pdf_text(pdf_path: Path, max_pages: int = 30) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", "-f", "1", "-l", str(max_pages), str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout


def select_context(text: str, limit: int = 24000) -> str:
    compact = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    if len(compact) <= limit:
        return compact
    sections: list[str] = [compact[:6000]]
    headings = (
        "method",
        "approach",
        "network architecture",
        "experiment",
        "evaluation",
        "results",
        "conclusion",
    )
    for heading in headings:
        match = re.search(rf"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*{re.escape(heading)}s?\s*$", compact)
        if match:
            sections.append(compact[match.start() : match.start() + 4500])
    merged = "\n\n".join(dict.fromkeys(sections))
    if len(merged) < limit:
        merged += "\n\n" + compact[-5000:]
    return merged[:limit]


def render_cover_webp(pdf_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = output_path.parent / f".{output_path.stem}-cover"
    result = subprocess.run(
        [
            "pdftoppm",
            "-png",
            "-f",
            "1",
            "-l",
            "1",
            "-scale-to",
            "1600",
            str(pdf_path),
            str(prefix),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    del result
    candidates = sorted(output_path.parent.glob(f"{prefix.name}-*.png"))
    if not candidates:
        raise RuntimeError("pdftoppm did not produce a cover image")
    png = candidates[0]
    with Image.open(png) as image:
        image.convert("RGB").save(output_path, "WEBP", quality=76, method=6)
    png.unlink(missing_ok=True)
    return output_path
