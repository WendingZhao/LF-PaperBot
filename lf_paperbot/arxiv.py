from __future__ import annotations

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

from .config import Settings
from .models import Candidate


ATOM = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
LIGHT_FIELD_QUERY = (
    'all:"light field" OR all:"light-field" OR all:plenoptic OR '
    'all:"spatial-angular" OR all:"epipolar plane image" OR '
    'all:"sub-aperture image" OR all:lenslet'
)
CATEGORY_QUERY = (
    "cat:cs.CV OR cat:cs.GR OR cat:cs.MM OR cat:eess.IV OR cat:eess.SP OR cat:physics.optics"
)


def _read_url(url: str, user_agent: str, timeout: int = 90, retries: int = 4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                raise
            retry_after = exc.headers.get("Retry-After", "")
            delay = int(retry_after) if retry_after.isdigit() else min(60, 3 * 2**attempt)
            time.sleep(delay)
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == retries - 1:
                raise
            time.sleep(min(30, 2 * 2**attempt))
    raise RuntimeError(f"request failed: {last_error}")


def _text(node: ET.Element, path: str) -> str:
    return " ".join((node.findtext(path, default="", namespaces=ATOM) or "").split())


def _parse_entry(entry: ET.Element) -> Candidate:
    arxiv_id = _text(entry, "atom:id").rsplit("/", 1)[-1]
    authors = [_text(author, "atom:name") for author in entry.findall("atom:author", ATOM)]
    categories = [item.attrib.get("term", "") for item in entry.findall("atom:category", ATOM)]
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    for link in entry.findall("atom:link", ATOM):
        if link.attrib.get("title") == "pdf":
            pdf_url = link.attrib.get("href", pdf_url)
            break
    return Candidate(
        arxiv_id=arxiv_id,
        title=_text(entry, "atom:title"),
        abstract=_text(entry, "atom:summary"),
        authors=[author for author in authors if author],
        categories=[category for category in categories if category],
        published=_text(entry, "atom:published"),
        updated=_text(entry, "atom:updated"),
        pdf_url=pdf_url,
    )


def fetch_recent(settings: Settings, target_date: date | None = None) -> list[Candidate]:
    query = f"({CATEGORY_QUERY}) AND ({LIGHT_FIELD_QUERY})"
    params = {
        "search_query": query,
        "start": 0,
        "max_results": 300,
        "sortBy": "lastUpdatedDate",
        "sortOrder": "descending",
    }
    url = f"{settings.arxiv_api_url}?{urllib.parse.urlencode(params)}"
    root = ET.fromstring(_read_url(url, settings.arxiv_user_agent))
    if target_date:
        earliest = target_date - timedelta(days=settings.lookback_days - 1)
        latest = target_date
    else:
        latest = datetime.now(settings.timezone).date()
        earliest = latest - timedelta(days=settings.lookback_days - 1)

    output: list[Candidate] = []
    for entry in root.findall("atom:entry", ATOM):
        candidate = _parse_entry(entry)
        stamp = candidate.updated or candidate.published
        try:
            updated_day = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc).date()
        except ValueError:
            continue
        if earliest <= updated_day <= latest:
            output.append(candidate)
    return output


def fetch_submitted_range(settings: Settings, start_date: date, end_date: date) -> list[Candidate]:
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    submitted = f"submittedDate:[{start_date:%Y%m%d}0000 TO {end_date:%Y%m%d}2359]"
    query = f"({CATEGORY_QUERY}) AND ({LIGHT_FIELD_QUERY}) AND {submitted}"
    page_size = 300
    start = 0
    output: list[Candidate] = []
    while True:
        params = {
            "search_query": query,
            "start": start,
            "max_results": page_size,
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }
        url = f"{settings.arxiv_api_url}?{urllib.parse.urlencode(params)}"
        root = ET.fromstring(_read_url(url, settings.arxiv_user_agent))
        entries = root.findall("atom:entry", ATOM)
        for entry in entries:
            candidate = _parse_entry(entry)
            try:
                published_day = datetime.fromisoformat(
                    candidate.published.replace("Z", "+00:00")
                ).astimezone(timezone.utc).date()
            except ValueError:
                continue
            if start_date <= published_day <= end_date:
                output.append(candidate)
        start += len(entries)
        total_text = root.findtext("opensearch:totalResults", default="0", namespaces=ATOM)
        total = int(total_text) if total_text.isdigit() else start
        if not entries or len(entries) < page_size or start >= total:
            break
        time.sleep(3)
    return output


def fetch_by_id(settings: Settings, arxiv_id: str) -> Candidate:
    params = {"id_list": arxiv_id, "max_results": 1}
    url = f"{settings.arxiv_api_url}?{urllib.parse.urlencode(params)}"
    root = ET.fromstring(_read_url(url, settings.arxiv_user_agent))
    entry = root.find("atom:entry", ATOM)
    if entry is None:
        raise LookupError(f"arXiv paper not found: {arxiv_id}")
    return _parse_entry(entry)


def download_pdf(settings: Settings, candidate: Candidate) -> Path:
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    path = settings.temp_dir / f"{candidate.arxiv_id}.pdf"
    data = _read_url(candidate.pdf_url, settings.arxiv_user_agent, timeout=120, retries=4)
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"downloaded content is not a PDF for {candidate.arxiv_id}")
    path.write_bytes(data)
    return path
