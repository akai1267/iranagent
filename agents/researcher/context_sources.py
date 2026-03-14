import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

SearchFn = Callable[[str], Awaitable[list[dict]]]

_COVERAGE_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
    flags=re.IGNORECASE,
)

_STREAM_LINE_RE = re.compile(
    r"^\[(?P<stamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s+"
    r"\[(?P<level>LOW|MEDIUM|HIGH|CRITICAL)\]\s+"
    r"\[(?P<platform>[^\]]+)\]\s+"
    r"\[(?P<outlet>[^\]]+)\]\s+"
    r"(?P<body>.+)$"
)

_CT_BOILERPLATE_PATTERNS = (
    "data cutoff",
    "publishing two updates daily",
    "morning update will focus",
    "evening update will be more comprehensive",
    "{{region_detail.text}}",
    "{{person_detail.text}}",
    "{{organization_detail.text}}",
    "{{series.description",
)


@dataclass
class ContextDocumentCandidate:
    provider: str
    doc_kind: str
    title: str
    canonical_url: str
    body: str
    fetched_at: str
    cycle: str | None = None
    coverage_date: str | None = None
    published_at: str | None = None
    meta: dict[str, Any] | None = None


class SourceParseError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned = parsed._replace(fragment="")
    return urlunparse(cleaned)


def parse_datetime_guess(raw: str | None) -> str | None:
    if not raw:
        return None

    value = raw.strip()
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue

    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return None


def parse_coverage_date(title: str) -> str | None:
    match = _COVERAGE_DATE_RE.search(title or "")
    if not match:
        return None
    raw = match.group(0)
    try:
        return datetime.strptime(raw, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def classify_cycle(text: str) -> str | None:
    lower = (text or "").lower()
    if "morning special report" in lower:
        return "morning"
    if "evening special report" in lower:
        return "evening"
    return None


def _body_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class HtmlFetcher:
    def __init__(self, timeout_sec: int = 20):
        self.timeout_sec = timeout_sec

    async def get_text(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout_sec, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            return response.text


class CriticalThreatsIranUpdateAdapter:
    def __init__(
        self,
        timeout_sec: int = 20,
        morning_pattern: str = "Iran Update Morning Special Report",
        evening_pattern: str = "Iran Update Evening Special Report",
    ):
        self.fetcher = HtmlFetcher(timeout_sec=timeout_sec)
        self.base_url = "https://www.criticalthreats.org"
        self.morning_pattern = morning_pattern
        self.evening_pattern = evening_pattern

    async def fetch_latest(
        self,
        allow_tavily_fallback: bool = False,
        tavily_search: SearchFn | None = None,
    ) -> list[ContextDocumentCandidate]:
        candidates = await self._discover_homepage_candidates()

        if not candidates and allow_tavily_fallback and tavily_search is not None:
            candidates = await self._discover_tavily_candidates(tavily_search)

        if not candidates:
            return []

        parsed: list[ContextDocumentCandidate] = []
        for url, hinted_title in candidates[:10]:
            try:
                doc = await self._fetch_document(url, hinted_title)
            except Exception:  # noqa: BLE001
                continue
            if doc is not None:
                parsed.append(doc)

        if not parsed:
            return []

        latest_morning = self._pick_latest([doc for doc in parsed if doc.cycle == "morning"])
        latest_evening = self._pick_latest([doc for doc in parsed if doc.cycle == "evening"])

        selected = [doc for doc in (latest_morning, latest_evening) if doc is not None]
        return selected

    async def _discover_homepage_candidates(self) -> list[tuple[str, str]]:
        html = await self.fetcher.get_text(self.base_url)
        soup = BeautifulSoup(html, "lxml")

        options: list[tuple[str, str]] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            if not href:
                continue
            text = normalize_space(anchor.get_text(" ", strip=True))
            hay = f"{text} {href}".lower()
            if "iran update" not in hay:
                continue
            if "morning special report" not in hay and "evening special report" not in hay:
                continue

            absolute = canonicalize_url(urljoin(self.base_url, href))
            if absolute in seen:
                continue
            seen.add(absolute)
            options.append((absolute, text))

        return options

    async def _discover_tavily_candidates(self, tavily_search: SearchFn) -> list[tuple[str, str]]:
        queries = [
            f"site:criticalthreats.org {self.morning_pattern}",
            f"site:criticalthreats.org {self.evening_pattern}",
        ]

        options: list[tuple[str, str]] = []
        seen: set[str] = set()
        for query in queries:
            try:
                results = await tavily_search(query)
            except Exception:  # noqa: BLE001
                continue
            for item in results:
                url = canonicalize_url(str(item.get("url", "")).strip())
                title = normalize_space(str(item.get("title", "")).strip())
                if not url:
                    continue
                hay = f"{title} {url}".lower()
                if "iran update" not in hay:
                    continue
                if "morning special report" not in hay and "evening special report" not in hay:
                    continue
                if url in seen:
                    continue
                seen.add(url)
                options.append((url, title))

        return options

    async def _fetch_document(self, url: str, hinted_title: str = "") -> ContextDocumentCandidate | None:
        html = await self.fetcher.get_text(url)
        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup) or hinted_title or url
        cycle = classify_cycle(title) or classify_cycle(hinted_title) or classify_cycle(url)
        if cycle not in {"morning", "evening"}:
            return None

        canonical = self._extract_canonical(soup, url)
        published = self._extract_published_at(soup) or parse_datetime_guess(parse_coverage_date(title))
        body = self._extract_article_body(soup)
        if len(body) < 300:
            return None

        return ContextDocumentCandidate(
            provider="critical_threats",
            doc_kind="iran_update",
            cycle=cycle,
            coverage_date=parse_coverage_date(title),
            title=title,
            canonical_url=canonical,
            published_at=published,
            fetched_at=utc_now_iso(),
            body=body,
            meta={"content_hash": _body_hash(body)},
        )

    @staticmethod
    def _is_boilerplate_paragraph(text: str) -> bool:
        low = text.lower()
        return any(token in low for token in _CT_BOILERPLATE_PATTERNS)

    def _extract_article_body(self, soup: BeautifulSoup) -> str:
        selectors = (
            "article",
            "div.entry-content",
            "div.post-content",
            "div.field-name-body",
            "div.node-content",
            "main",
        )
        chunks: list[str] = []
        seen: set[str] = set()

        for selector in selectors:
            for node in soup.select(selector):
                for p in node.find_all("p"):
                    text = normalize_space(p.get_text(" ", strip=True))
                    if not text:
                        continue
                    if self._is_boilerplate_paragraph(text):
                        continue
                    key = text.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    chunks.append(text)
            if len(chunks) >= 8:
                break

        if not chunks:
            for p in soup.find_all("p"):
                text = normalize_space(p.get_text(" ", strip=True))
                if not text:
                    continue
                if self._is_boilerplate_paragraph(text):
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                chunks.append(text)

        return "\n\n".join(chunks)

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            return normalize_space(str(og.get("content")))
        h1 = soup.find("h1")
        if h1:
            text = normalize_space(h1.get_text(" ", strip=True))
            if text:
                return text
        if soup.title:
            return normalize_space(soup.title.get_text(" ", strip=True))
        return ""

    @staticmethod
    def _extract_canonical(soup: BeautifulSoup, fallback_url: str) -> str:
        link = soup.find("link", rel=lambda value: value and "canonical" in str(value).lower())
        if link and link.get("href"):
            return canonicalize_url(str(link.get("href")))
        return canonicalize_url(fallback_url)

    @staticmethod
    def _extract_published_at(soup: BeautifulSoup) -> str | None:
        meta_candidates = [
            ("property", "article:published_time"),
            ("name", "article:published_time"),
            ("name", "pubdate"),
            ("property", "og:updated_time"),
        ]
        for key, value in meta_candidates:
            tag = soup.find("meta", attrs={key: value})
            if tag and tag.get("content"):
                parsed = parse_datetime_guess(str(tag.get("content")))
                if parsed:
                    return parsed

        time_tag = soup.find("time")
        if time_tag:
            if time_tag.get("datetime"):
                parsed = parse_datetime_guess(str(time_tag.get("datetime")))
                if parsed:
                    return parsed
            parsed = parse_datetime_guess(time_tag.get_text(" ", strip=True))
            if parsed:
                return parsed

        return None

    @staticmethod
    def _pick_latest(documents: list[ContextDocumentCandidate]) -> ContextDocumentCandidate | None:
        if not documents:
            return None

        def score(doc: ContextDocumentCandidate) -> tuple[datetime, int, datetime]:
            published = parse_datetime_guess(doc.published_at)
            pub_dt = datetime.fromisoformat(published) if published else datetime(1970, 1, 1, tzinfo=timezone.utc)
            coverage = doc.coverage_date or "1970-01-01"
            try:
                coverage_dt = datetime.fromisoformat(coverage).replace(tzinfo=timezone.utc)
            except ValueError:
                coverage_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
            domain_rank = 1 if "criticalthreats.org" in (doc.canonical_url or "") else 0
            return pub_dt, domain_rank, coverage_dt

        return sorted(documents, key=score, reverse=True)[0]


class IranMonitorStructuralAdapter:
    def __init__(self, url: str = "https://www.iranmonitor.org/whats-happening-in-iran", timeout_sec: int = 20):
        self.url = url
        self.fetcher = HtmlFetcher(timeout_sec=timeout_sec)

    async def fetch_latest(self) -> list[ContextDocumentCandidate]:
        html = await self.fetcher.get_text(self.url)
        soup = BeautifulSoup(html, "lxml")

        title = normalize_space(soup.title.get_text(" ", strip=True) if soup.title else "What's Happening in Iran")
        paragraphs = [normalize_space(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
        body = "\n\n".join(p for p in paragraphs if p)
        if len(body) < 300:
            raise SourceParseError("Iran Monitor structural page body too short")

        return [
            ContextDocumentCandidate(
                provider="iran_monitor",
                doc_kind="structural_overview",
                title=title,
                canonical_url=canonicalize_url(self.url),
                published_at=None,
                fetched_at=utc_now_iso(),
                body=body,
                meta={"content_hash": _body_hash(body)},
            )
        ]


class IranMonitorBriefingAdapter:
    def __init__(self, timeout_sec: int = 20):
        self.base_url = "https://www.iranmonitor.org/"
        self.fetcher = HtmlFetcher(timeout_sec=timeout_sec)

    async def fetch_latest(
        self,
        allow_tavily_fallback: bool = False,
        tavily_search: SearchFn | None = None,
    ) -> list[ContextDocumentCandidate]:
        home = await self.fetcher.get_text(self.base_url)
        soup = BeautifulSoup(home, "lxml")

        candidate_urls = self._discover_links(soup)
        if not candidate_urls and allow_tavily_fallback and tavily_search is not None:
            candidate_urls = await self._discover_tavily_links(tavily_search)

        if not candidate_urls:
            candidate_urls = [self.base_url]

        for url in candidate_urls[:5]:
            try:
                doc = await self._fetch_briefing_doc(url)
            except Exception:  # noqa: BLE001
                continue
            if doc is not None:
                return [doc]

        return []

    def _discover_links(self, soup: BeautifulSoup) -> list[str]:
        hits: list[str] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            text = normalize_space(anchor.get_text(" ", strip=True)).lower()
            hay = f"{text} {href}".lower()
            if "brief" not in hay and "recap" not in hay:
                continue

            url = canonicalize_url(urljoin(self.base_url, href))
            if "iranmonitor.org" not in url:
                continue
            if "dashboard" in url.lower():
                continue
            if url in seen:
                continue
            seen.add(url)
            hits.append(url)

        scripts = "\n".join(tag.get_text("\n", strip=True) for tag in soup.find_all("script"))
        for raw in re.findall(r"https?://[^\"'\s]+", scripts):
            if "iranmonitor.org" not in raw:
                continue
            lower = raw.lower()
            if "brief" not in lower and "recap" not in lower:
                continue
            if "dashboard" in lower:
                continue
            url = canonicalize_url(raw)
            if url in seen:
                continue
            seen.add(url)
            hits.append(url)

        return hits

    async def _discover_tavily_links(self, tavily_search: SearchFn) -> list[str]:
        queries = [
            "site:iranmonitor.org daily briefing iran",
            "site:iranmonitor.org recap iran",
        ]

        hits: list[str] = []
        seen: set[str] = set()
        for query in queries:
            try:
                results = await tavily_search(query)
            except Exception:  # noqa: BLE001
                continue
            for item in results:
                url = canonicalize_url(str(item.get("url", "")).strip())
                if not url or "iranmonitor.org" not in url:
                    continue
                lower = url.lower()
                title = str(item.get("title", "")).lower()
                if not any(token in f"{lower} {title}" for token in ("brief", "recap")):
                    continue
                if "dashboard" in lower:
                    continue
                if url in seen:
                    continue
                seen.add(url)
                hits.append(url)

        return hits

    async def _fetch_briefing_doc(self, url: str) -> ContextDocumentCandidate | None:
        url_lower = url.lower()
        if "dashboard" in url_lower:
            return None
        html = await self.fetcher.get_text(url)
        soup = BeautifulSoup(html, "lxml")

        title = normalize_space(soup.title.get_text(" ", strip=True) if soup.title else "Iran Monitor Briefing")
        title_lower = title.lower()
        if "brief" not in title_lower and "recap" not in title_lower and "brief" not in url_lower and "recap" not in url_lower:
            return None
        paragraphs = [normalize_space(p.get_text(" ", strip=True)) for p in soup.find_all("p")]
        body = "\n\n".join(p for p in paragraphs if p)
        if len(body) < 200:
            return None

        published = None
        meta_candidates = [
            ("property", "article:published_time"),
            ("name", "article:published_time"),
            ("property", "og:updated_time"),
            ("name", "pubdate"),
        ]
        for key, value in meta_candidates:
            tag = soup.find("meta", attrs={key: value})
            if tag and tag.get("content"):
                published = parse_datetime_guess(str(tag.get("content")))
                if published:
                    break

        time_tag = soup.find("time")
        if not published and time_tag:
            published = parse_datetime_guess(str(time_tag.get("datetime") or time_tag.get_text(" ", strip=True)))
        if not published:
            coverage = parse_coverage_date(title)
            if coverage:
                published = parse_datetime_guess(f"{coverage} 00:00:00")
        if not published:
            return None
        published_dt = parse_datetime_guess(published)
        parsed_dt = datetime.fromisoformat(published_dt) if published_dt else None
        if parsed_dt and (datetime.now(timezone.utc) - parsed_dt) > timedelta(hours=48):
            return None

        return ContextDocumentCandidate(
            provider="iran_monitor",
            doc_kind="daily_briefing",
            title=title,
            canonical_url=canonicalize_url(url),
            published_at=published,
            fetched_at=utc_now_iso(),
            body=body,
            meta={"content_hash": _body_hash(body)},
        )


class StreamDeltaExtractor:
    def __init__(self, stream_path: Path):
        self.stream_path = stream_path

    @staticmethod
    def _parse_line(line: str) -> dict[str, Any] | None:
        match = _STREAM_LINE_RE.match(line.strip())
        if not match:
            return None

        stamp = match.group("stamp")
        try:
            dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

        level = match.group("level").upper()
        if level not in {"MEDIUM", "HIGH", "CRITICAL"}:
            return None

        body = match.group("body")
        headline = body
        why = ""
        url = ""
        if " — " in body:
            left, why, url = body.rsplit(" — ", 2)
            headline = left

        return {
            "timestamp": dt.isoformat(),
            "significance": level.lower(),
            "platform": normalize_space(match.group("platform")),
            "outlet": normalize_space(match.group("outlet")),
            "headline": normalize_space(headline),
            "why": normalize_space(why),
            "url": normalize_space(url),
        }

    @staticmethod
    def _to_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None

    def extract(self, after_ts: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        if not self.stream_path.exists():
            return []

        after_dt = self._to_dt(after_ts)
        deltas: list[dict[str, Any]] = []

        for raw in self.stream_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            parsed = self._parse_line(raw)
            if parsed is None:
                continue
            item_dt = self._to_dt(parsed.get("timestamp"))
            if after_dt is not None and item_dt is not None and item_dt <= after_dt:
                continue
            deltas.append(parsed)

        deltas.sort(key=lambda item: item.get("timestamp", ""))
        if limit > 0:
            deltas = deltas[-limit:]
        return deltas

    def extract_since_hours(self, hours: int = 24, limit: int = 12) -> list[dict[str, Any]]:
        after = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
        return self.extract(after_ts=after.isoformat(), limit=limit)
