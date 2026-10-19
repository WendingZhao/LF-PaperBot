"""Official arXiv HTML search fallback for API outages."""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser

from .models import Candidate


class PartialSearchError(RuntimeError):
    def __init__(self, candidates, message):
        super().__init__(message)
        self.candidates = candidates


class ResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.values = {}
        self.arxiv_id = ""
        self.doi = ""
        self.author_count = self.category_count = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        parent = self.stack[-1][1] if self.stack else ""
        key = parent
        if tag == "p" and "title" in classes:
            key = "title"
        elif "abstract-full" in classes:
            key = "abstract"
            match = re.match(r"(\d{4}\.\d{4,5}v\d+)-abstract-full", attrs.get("id", ""))
            if match:
                self.arxiv_id = match[1]
        elif tag == "p" and "authors" in classes:
            key = "authors"
        elif tag == "a" and parent == "authors":
            self.author_count += 1
            key = f"author{self.author_count}"
        elif "tag" in classes and "data-tooltip" in attrs:
            self.category_count += 1
            key = f"category{self.category_count}"
        elif tag == "p" and classes == ["is-size-7"]:
            key = "date"
        elif tag == "a" and parent == "abstract":
            key = "skip"
        href = attrs.get("href", "")
        if href.startswith("https://doi.org/"):
            self.doi = href.removeprefix("https://doi.org/")
        if tag not in {"br", "hr", "img", "input", "meta", "link"}:
            self.stack.append((tag, key))

    def handle_data(self, data):
        if self.stack:
            key = self.stack[-1][1]
            if key and key not in {"authors", "skip"}:
                self.values.setdefault(key, []).append(data)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def text(self, key):
        return " ".join("".join(self.values.get(key, [])).split())


def parse_results(text: str) -> tuple[list[Candidate], int]:
    total_match = re.search(r"Showing\s+[\d,]+.*?of\s+([\d,]+)\s+results", unescape(text), re.S)
    blocks = re.findall(r'<li\s+class="arxiv-result"\s*>(.*?)</li>', text, re.S)
    if not total_match:
        if not blocks and re.search(r"query returned no results", text, re.I):
            return [], 0
        raise ValueError("arXiv search response has no result count")
    papers = []
    for block in blocks:
        parser = ResultParser()
        parser.feed(block)
        dates = parser.text("date")
        latest = re.search(r"\bSubmitted\s+(\d+\s+[A-Za-z]+,\s+\d{4})", dates, re.I)
        original = re.search(r"\bv1\s+submitted\s+(\d+\s+[A-Za-z]+,\s+\d{4})", dates, re.I)
        if not parser.arxiv_id or not parser.text("title") or not latest:
            raise ValueError("arXiv search result is missing ID, title or submission date")
        def day(value):
            return datetime.strptime(value, "%d %B, %Y").date().isoformat()
        papers.append(Candidate(
            arxiv_id=parser.arxiv_id, title=parser.text("title"), abstract=parser.text("abstract"),
            authors=[parser.text(f"author{i}") for i in range(1, parser.author_count + 1)],
            categories=[parser.text(f"category{i}") for i in range(1, parser.category_count + 1)],
            published=day((original or latest)[1]), updated=day(latest[1]),
            pdf_url=f"https://arxiv.org/pdf/{parser.arxiv_id}", doi=parser.doi,
        ))
    total = int(total_match[1].replace(",", ""))
    if total and not papers:
        raise ValueError("arXiv search response unexpectedly contains no papers")
    return papers, total


def fetch_search_range(settings, start: date, end: date, *, updated: bool = False) -> list[Candidate]:
    from .arxiv import CATEGORY_QUERY
    allowed = set(re.findall(r"cat:([\w.]+)", CATEGORY_QUERY))
    terms = ('"light field" OR "light-field" OR plenoptic OR "spatial-angular" OR '
             '"epipolar plane image" OR "sub-aperture image" OR lenslet')
    offset = 0
    seen_pages = set()
    output = []
    while True:
        params = {"advanced": "1", "terms-0-operator": "AND", "terms-0-term": terms,
                  "terms-0-field": "all", "classification-include_cross_list": "include",
                  "date-filter_by": "date_range", "date-from_date": str(start),
                  "date-to_date": str(end + timedelta(days=1)),
                  "date-date_type": "submitted_date" if updated else "submitted_date_first",
                  "abstracts": "show", "size": "200", "order": "announced_date_first", "start": offset}
        request = urllib.request.Request("https://arxiv.org/search/advanced?" + urllib.parse.urlencode(params),
                                         headers={"User-Agent": settings.arxiv_user_agent, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                papers, total = parse_results(response.read().decode("utf-8"))
            signature = tuple(p.base_id for p in papers)
            if papers and signature in seen_pages:
                raise ValueError("arXiv search repeated a page")
            seen_pages.add(signature)
            output.extend(p for p in papers if set(p.categories) & allowed
                          and str(start) <= (p.updated if updated else p.published) <= str(end))
            offset += len(papers)
            print(f"[ARXIV SEARCH] {offset}/{total} results scanned", flush=True)
            if offset >= total:
                return output
            if not papers:
                raise ValueError("arXiv search pagination ended before total results")
            time.sleep(3)
        except Exception as exc:
            if output:
                raise PartialSearchError(output, type(exc).__name__) from exc
            raise
