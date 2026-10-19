"""Public metadata and open conference adapters; no additional API key required."""
from __future__ import annotations

import html
import calendar
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError

from . import arxiv
from .config import Settings
from .domain import LF_PATTERNS
from .models import Candidate, normalize_doi, normalize_title

CVF_ROOT = "https://openaccess.thecvf.com/"


class PartialSourceError(RuntimeError):
    def __init__(self, candidates: list[Candidate], message: str):
        super().__init__(message)
        self.candidates = candidates


class SourceCandidates(list):
    def __init__(self, items, stats):
        super().__init__(items)
        self.stats = stats


def read_public(url: str, user_agent: str) -> bytes:
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            retry = exc.headers.get("Retry-After", "")
            time.sleep(min(60, int(retry)) if retry.isdigit() else 3 * 2**attempt)
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(3 * 2**attempt)
    raise RuntimeError("public source request exhausted retries")


def plain_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def _crossref_date(item: dict) -> tuple[str, int]:
    for key in ("published", "published-online", "published-print", "issued"):
        parts = item.get(key, {}).get("date-parts", [[]])[0]
        if not parts:
            continue
        # A year or year/month is insufficient evidence for a precise date.
        if len(parts) < 3:
            return "", int(parts[0])
        try:
            return date(*parts[:3]).isoformat(), int(parts[0])
        except (ValueError, TypeError):
            continue
    return "", 0


def parse_crossref(item: dict) -> Candidate | None:
    title = plain_text(" ".join(item.get("title", [])))
    doi = normalize_doi(item.get("DOI", ""))
    abstract = plain_text(item.get("abstract", ""))
    if not title or not doi or not any(p.search(title + " " + abstract) for p in LF_PATTERNS):
        return None
    published, year = _crossref_date(item)
    month = ""
    for key in ("published", "published-online", "published-print", "issued"):
        parts = item.get(key, {}).get("date-parts", [[]])[0]
        if len(parts) >= 2 and 1 <= parts[1] <= 12:
            month = f"{parts[0]:04d}-{parts[1]:02d}"
            break
    # Crossref TDM links are not proof of open access. Only use PDF links
    # associated with an explicit Creative Commons license.
    open_license = any("creativecommons.org/" in x.get("URL", "") for x in item.get("license", []))
    pdf_url = next((x.get("URL", "") for x in item.get("link", [])
                    if open_license and x.get("content-type") == "application/pdf"
                    and x.get("URL", "").startswith("https://")), "")
    return Candidate(
        arxiv_id="", title=title, abstract=abstract,
        authors=[" ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "")
                 for a in item.get("author", [])],
        categories=[], published=published, updated=published, pdf_url=pdf_url,
        source="crossref", source_url=f"https://doi.org/{doi}", doi=doi,
        venue=plain_text(" / ".join(item.get("container-title", []))), publication_year=year,
        publication_month=month,
        date_basis="published" if published else "indexed",
    )


def fetch_crossref(settings: Settings, start: date, end: date, *, historical: bool = False) -> list[Candidate]:
    output: list[Candidate] = []
    limited = False
    # Include newly registered DOIs as well as new publications. Older work
    # registered this week is labelled indexed rather than newly published.
    date_fields = ("pub",) if historical else ("pub", "created")
    for field in date_fields:
        for term in ('"light field"', "plenoptic"):
            cursor = "*"
            page = 0
            fetched = 0
            seen_pages = set()
            page_size = 1000 if historical else 100
            while historical or page < settings.crossref_max_pages:
                params = {
                    "query.title": term, "filter": f"from-{field}-date:{start},until-{field}-date:{end}",
                    "rows": page_size, "cursor": cursor,
                }
                if settings.crossref_mailto:
                    params["mailto"] = settings.crossref_mailto
                url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
                try:
                    message = json.loads(read_public(url, settings.arxiv_user_agent))["message"]
                except Exception as exc:
                    if output:
                        detail = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
                        raise PartialSourceError(output, detail) from exc
                    raise
                items = message.get("items", [])
                signature = hashlib.sha256(json.dumps([x.get("DOI") for x in items]).encode()).hexdigest()
                if items and signature in seen_pages:
                    raise PartialSourceError(output, "Crossref returned a repeated page")
                seen_pages.add(signature)
                for item in items:
                    candidate = parse_crossref(item)
                    if candidate:
                        if field == "created" and not (str(start) <= candidate.published[:10] <= str(end)):
                            candidate.date_basis = "indexed"
                        output.append(candidate)
                next_cursor = message.get("next-cursor")
                fetched += len(items)
                page += 1
                if len(items) < page_size or fetched >= message.get("total-results", float("inf")) or not next_cursor:
                    break
                if not historical and page == settings.crossref_max_pages:
                    limited = True
                    break
                cursor = next_cursor
                time.sleep(1)
            print(f"[CROSSREF] {start}..{end} {field} {term}: pages={page} records={fetched}")
    if limited:
        raise PartialSourceError(output, "result limit reached; increase CROSSREF_MAX_PAGES")
    return output


class CVFPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.links: list[tuple[str, str]] = []
        self.abstract: list[str] = []
        self._abstract_depth = 0
        self._href = ""
        self._label: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name", "").startswith("citation_"):
            self.meta.setdefault(attrs["name"], []).append(attrs.get("content", ""))
        if tag == "div":
            if attrs.get("id") == "abstract":
                self._abstract_depth = 1
            elif self._abstract_depth:
                self._abstract_depth += 1
        if tag == "a":
            self._href = attrs.get("href", "")
            self._label = []

    def handle_data(self, data):
        if self._abstract_depth:
            self.abstract.append(data)
        if self._href:
            self._label.append(data)

    def handle_endtag(self, tag):
        if tag == "div" and self._abstract_depth:
            self._abstract_depth -= 1
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._label).split())))
            self._href = ""


def parse_cvf_page(text: str, url: str, venue: str) -> Candidate:
    page = CVFPage()
    page.feed(text)
    title = page.meta.get("citation_title", [""])[0]
    if not title:
        raise ValueError("CVF paper page missing citation_title")
    raw_date = page.meta.get("citation_publication_date", [""])[0].replace("/", "-")
    try:
        published = date.fromisoformat(raw_date).isoformat()
    except ValueError:
        published = ""
    year_match = re.search(r"\d{4}", raw_date or venue)
    year = int(year_match[0]) if year_match else 0
    month_match = re.search(r"\bmonth\s*=\s*\{([A-Za-z]+)\}", text, re.I)
    months = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
    month = months.get(month_match[1].lower()) if month_match else None
    return Candidate(
        arxiv_id="", title=title, abstract=" ".join(" ".join(page.abstract).split()),
        authors=page.meta.get("citation_author", []), categories=[],
        published=published, updated=published,
        pdf_url=page.meta.get("citation_pdf_url", [""])[0], source="cvf", source_url=url,
        doi=page.meta.get("citation_doi", [""])[0], venue=venue,
        publication_year=year,
        publication_month=f"{year:04d}-{month:02d}" if month else "",
        date_basis="published" if published else "discovered",
    )


def _read_cvf(settings: Settings, url: str) -> str:
    cache_root = getattr(settings, "temp_dir", None)
    cache = (cache_root / "cvf_cache" / (hashlib.sha256(url.encode()).hexdigest() + ".html")) if cache_root else None
    if cache and cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        return cache.read_text(encoding="utf-8")
    text = read_public(url, settings.arxiv_user_agent).decode("utf-8")
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return text


def fetch_cvf(settings: Settings, start: date, end: date, *, historical: bool = False) -> list[Candidate]:
    venues = settings.cvf_venues
    if not venues:
        page = CVFPage()
        page.feed(_read_cvf(settings, CVF_ROOT))
        venues = tuple(dict.fromkeys(
            href.strip("/") for href, _ in page.links
            if re.fullmatch(r"/?(?:CVPR|ICCV|WACV)\d{4}/?", href)
            and (start.year if historical else start.year - 1) <= int(href.strip("/")[-4:]) <= end.year
        ))
        if not venues:
            raise RuntimeError("CVF archive discovery returned no venues")
    output: list[Candidate] = []
    for venue in venues:
        if not re.fullmatch(r"(?:CVPR|ICCV|WACV)\d{4}", venue):
            raise ValueError(f"Unsupported CVF venue: {venue}")
        page = CVFPage()
        page.feed(_read_cvf(settings, f"{CVF_ROOT}{venue}?day=all"))
        paper_links = [(href, title) for href, title in page.links if "/html/" in href]
        if not paper_links:
            raise RuntimeError(f"CVF {venue} archive contains no paper links")
        for href, title in dict(paper_links).items():
            if not any(p.search(title) for p in LF_PATTERNS):
                continue
            url = urllib.parse.urljoin(CVF_ROOT, href)
            if urllib.parse.urlsplit(url).hostname != "openaccess.thecvf.com":
                continue
            time.sleep(1)
            candidate = parse_cvf_page(_read_cvf(settings, url), url, venue)
            # Archives usually only specify the year; let index deduplication
            # identify unseen work. Never invent a publication day from it.
            if historical and candidate.publication_month:
                if not start.strftime("%Y-%m") <= candidate.publication_month <= end.strftime("%Y-%m"):
                    continue
            if not candidate.published or str(start) <= candidate.published <= str(end):
                output.append(candidate)
    return output


def deduplicate(candidates: list[Candidate], existing: dict | None = None) -> list[Candidate]:
    """Merge DOI/title/ID matches, including aliases already in the index."""
    output: list[Candidate] = []
    aliases: dict[str, Candidate] = {}
    known: dict[str, str] = {}

    def keys(item):
        get = item.get if isinstance(item, dict) else lambda k, d="": getattr(item, k, d)
        return list(filter(None, [
            "id:" + get("base_id") if get("base_id") else "",
            "doi:" + normalize_doi(get("doi")) if get("doi") else "",
            "title:" + normalize_title(get("title")) if normalize_title(get("title")) else "",
        ]))

    for base_id, record in (existing or {}).items():
        for key in keys(record):
            known[key] = base_id
    # Prefer arXiv version tracking, then the CVF full text, then metadata.
    for candidate in sorted(candidates, key=lambda c: ({"arxiv": 0, "cvf": 1}.get(c.source, 2), -c.version)):
        candidate_keys = keys(candidate)
        current = next((aliases[k] for k in candidate_keys if k in aliases), None)
        if current:
            current.sources = list(dict.fromkeys([*current.sources, *candidate.sources]))
            current.doi = current.doi or candidate.doi
            current.venue = current.venue or candidate.venue
            current.alternate_pdf_urls = list(dict.fromkeys([
                *current.alternate_pdf_urls, *candidate.alternate_pdf_urls,
                *([candidate.pdf_url] if candidate.pdf_url and candidate.pdf_url != current.pdf_url else []),
            ]))
            if not current.pdf_url and candidate.pdf_url:
                current.pdf_url = candidate.pdf_url
            for key in candidate_keys:
                aliases[key] = current
            continue
        previous_id = next((known[k] for k in candidate_keys if k in known), None)
        if previous_id:
            candidate.base_id = previous_id
            previous = existing[previous_id]
            candidate.sources = list(dict.fromkeys([*candidate.sources, *previous.get("sources", [previous.get("source", "arxiv")])]))
            candidate.doi = candidate.doi or previous.get("doi", "")
        output.append(candidate)
        for key in candidate_keys:
            aliases[key] = candidate
    return output


def fetch_sources(settings: Settings, target_date: date | None = None, *,
                  start_date: date | None = None, historical: bool = False,
                  require_any: bool = True) -> tuple[list[Candidate], dict]:
    end = target_date or datetime.now(settings.timezone).date()
    start = start_date or end - timedelta(days=settings.lookback_days - 1)
    adapters = {
        "arxiv": lambda: arxiv.fetch_submitted_range(settings, start, end) if historical else arxiv.fetch_recent(settings, end),
        "crossref": lambda: fetch_crossref(settings, start, end, historical=historical),
        "cvf": lambda: fetch_cvf(settings, start, end, historical=True) if historical else fetch_cvf(settings, start, end),
    }
    if not settings.sources or set(settings.sources) - adapters.keys():
        raise ValueError("LF_SOURCES must contain arxiv, crossref and/or cvf")
    candidates: list[Candidate] = []
    stats = {}
    for name in dict.fromkeys(settings.sources):
        print(f"[SOURCE START] {name}: {start}..{end}", flush=True)
        try:
            items = adapters[name]()
            candidates.extend(items)
            stats[name] = {"status": "ok", "count": len(items)}
            print(f"[SOURCE] {name}: {len(items)} candidates")
        except PartialSourceError as exc:
            candidates.extend(exc.candidates)
            stats[name] = {"status": "partial", "count": len(exc.candidates), "error": str(exc)}
            print(f"[WARN] source {name}: {exc}")
        except Exception as exc:
            # Only log a short type/status, never a full upstream response.
            detail = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
            stats[name] = {"status": "failed", "count": 0, "error": detail}
            print(f"[WARN] source {name} unavailable: {detail}")
    if require_any and all(x["status"] == "failed" for x in stats.values()):
        raise RuntimeError("All paper sources failed; no empty report will be published")
    return deduplicate(candidates), stats


def fetch_recent(settings: Settings, target_date: date | None = None) -> SourceCandidates:
    items, stats = fetch_sources(settings, target_date)
    return SourceCandidates(items, stats)


def fetch_submitted_range(settings: Settings, start: date, end: date) -> SourceCandidates:
    items, stats = fetch_sources(settings, end, start_date=start, historical=True)
    return SourceCandidates(items, stats)
