from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


SECTION_HEADING_RE = re.compile(r"^##\s+.+$", re.MULTILINE)
HIGH_IMPACT_EVENT_RE = re.compile(
    r"\*\*(\d+)\.\s*(.*?)\*\*\s*\(Impact:\s*(\d+)/10\)\s*"
    r"\n- Time:\s*(.*?)"
    r"\n- Category:\s*([A-Z]+)\s*\|\s*Sentiment:\s*([A-Z]+)\s*"
    r"\n- (.*?)(?=\n\*\*\d+\.\s|\n### All Events|\Z)",
    re.DOTALL,
)
TOP_SOURCE_RE = re.compile(r"^\d+\.\s+(.+?)\s+\((\d+)\s+articles\)", re.MULTILINE)
HEADLINE_RE = re.compile(r"^\d+\.\s+\[[A-Z]+\]\s+(.+)$", re.MULTILINE)
RECENT_ALERT_RE = re.compile(r"^\s*[-\*•]\s+\[[A-Z]+\]\s+(.+?)\s+-\s+(.+?)\s*$", re.MULTILINE)


BUCKET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "regional_cost_surface": (
        "uae",
        "saudi",
        "bahrain",
        "qatar",
        "kuwait",
        "al-dhafra",
        "fujairah",
        "jufair",
        "ali al-salem",
        "al-azraq",
        "launchpad",
        "neighboring countries",
        "neighbor's",
        "regional system",
        "american-linked industrial",
        "ports",
    ),
    "endurance_and_attrition": (
        "interceptor",
        "running critically low",
        "running low",
        "since war began",
        "barrage",
        "sustained",
        "wave 50",
        "wave 51",
        "wave 52",
        "shot down since the start",
        "attrition",
    ),
    "commerce_and_shipping": (
        "kharg",
        "abu musa",
        "hormuz",
        "shipping",
        "merchant vessel",
        "merchant vessels",
        "oil",
        "port",
        "ports",
        "jebel ali",
        "khalifa",
        "fujairah",
        "trade",
        "export",
        "island",
    ),
    "regime_governability": (
        "internet",
        "outage",
        "protest",
        "arrest",
        "civilian factories",
        "schools",
        "hospitals",
        "historic sites",
        "public mobilization",
        "internal",
        "tehran airstrike",
    ),
    "battlefield_attrition": (
        "killed",
        "airstrike",
        "shot down",
        "drones over tehran",
        "air defense",
        "military forces",
        "fighter jets",
        "awacs",
        "refueling tankers",
        "headquarters",
        "base",
        "bases",
    ),
    "diplomatic_pressure": (
        "foreign minister",
        "retaliate",
        "proposal",
        "reviewing",
        "recognize israel",
        "peace negotiations",
        "warned",
        "launchpads",
        "neighboring countries",
        "declaring",
        "framework",
    ),
}


@dataclass
class EvidenceRef:
    id: str
    kind: str
    authority: str
    summary: str
    source_ref: str
    timestamp: str | None
    url: str | None


@dataclass
class SelectedEvent:
    evidence_id: str
    title: str
    impact: int
    timestamp: str | None
    relative_time: str | None
    category: str
    sentiment: str
    summary: str
    bucket: str


@dataclass
class FactPack:
    generated_at: str | None
    overview: dict[str, Any]
    internet_status: dict[str, Any]
    selected_events: list[SelectedEvent]
    event_buckets: dict[str, list[str]]
    evidence_ledger: list[EvidenceRef]
    quality_flags: list[str]
    fact_pack_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "overview": self.overview,
            "internet_status": self.internet_status,
            "selected_events": [asdict(item) for item in self.selected_events],
            "event_buckets": self.event_buckets,
            "evidence_ledger": [asdict(item) for item in self.evidence_ledger],
            "quality_flags": self.quality_flags,
            "fact_pack_hash": self.fact_pack_hash,
        }


def _split_sections(prompt: str) -> dict[str, str]:
    matches = list(SECTION_HEADING_RE.finditer(prompt))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
        heading = match.group(0).strip()
        sections[heading] = prompt[start:end].strip()
    return sections


def _extract_generated_at(prompt: str) -> str | None:
    match = re.search(r"(?im)^generated:\s*(.+?)\s*$", prompt)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return raw


def _parse_current_assessment(section: str) -> dict[str, Any]:
    overview: dict[str, Any] = {}
    patterns = {
        "news_volume_trend": r"News Volume Trend \(7d\):\s*(.+)",
        "social_media_activity": r"Social Media Activity:\s*(.+)",
        "internet_status": r"Internet Status:\s*(.+)",
        "dominant_sentiment": r"Dominant Sentiment:\s*(.+)",
        "high_impact_events": r"High-Impact Events:\s*(.+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, section)
        if match:
            overview[key] = match.group(1).strip()
    return overview


def _parse_relative_age_hours(raw: str) -> float | None:
    text = raw.strip().lower()
    match = re.match(r"(\d+)\s*([mhdw])\s+ago", text)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return value / 60.0
    if unit == "h":
        return float(value)
    if unit == "d":
        return float(value * 24)
    if unit == "w":
        return float(value * 24 * 7)
    return None


def _parse_internet_status(section: str) -> tuple[dict[str, Any], list[str]]:
    flags: list[str] = []
    status: dict[str, Any] = {"summary": ""}

    current_match = re.search(r"Current Status:\s*(.+)", section)
    outage_match = re.search(r"Ongoing outage:\s*(.+)", section)
    alerts_match = re.search(r"Total alerts \(7d\):\s*(\d+)", section)
    critical_match = re.search(r"Critical alerts:\s*(\d+)", section)
    blocking_match = re.search(r"Blocking rate \|\s*(.+?)\s*\|", section)

    if current_match:
        status["current_status"] = current_match.group(1).strip()
    if outage_match:
        status["ongoing_outage"] = outage_match.group(1).strip().upper().startswith("YES")
    if alerts_match:
        status["total_alerts_7d"] = int(alerts_match.group(1))
    if critical_match:
        status["critical_alerts"] = int(critical_match.group(1))
    if blocking_match:
        status["blocking_rate"] = blocking_match.group(1).strip()

    kept_alerts: list[str] = []
    stale_count = 0
    for name, age_text in RECENT_ALERT_RE.findall(section):
        hours = _parse_relative_age_hours(age_text)
        if hours is None or hours <= 72:
            kept_alerts.append(f"{name.strip()} ({age_text.strip()})")
        else:
            stale_count += 1
    if stale_count:
        flags.append("internet_alerts_stale_suppressed")
    status["recent_alerts"] = kept_alerts

    if status.get("ongoing_outage"):
        status["summary"] = "Internet disruption is active, which matters as a wartime control and governability signal."
    elif kept_alerts:
        status["summary"] = "Connectivity looks mostly monitor-state rather than acute disruption, with only recent alert residue."
    else:
        status["summary"] = "No current outage signal; internet data is low-priority supporting context."

    return status, flags


def _parse_news_quality(section: str) -> list[str]:
    flags: list[str] = []
    corrupt_age = False
    for days in re.findall(r"\|\s*(\d+)d ago\s*\|", section):
        if int(days) > 365:
            corrupt_age = True
            break
    if corrupt_age:
        flags.append("headline_age_corrupt")

    headlines = [item.strip() for item in HEADLINE_RE.findall(section)]
    if headlines:
        normalized = [re.sub(r"\W+", " ", item.lower()).strip() for item in headlines]
        duplicates = len(normalized) - len(set(normalized))
        if duplicates / max(1, len(normalized)) >= 0.4:
            flags.append("headline_duplication_high")

    sources = [name.strip() for name, _ in TOP_SOURCE_RE.findall(section)]
    if sources:
        counts = [int(count) for _, count in TOP_SOURCE_RE.findall(section)]
        if counts and max(counts) >= max(12, sum(counts) * 0.7):
            flags.append("source_count_skewed")

    return flags


def _parse_event_timestamp(raw_time: str) -> str | None:
    match = re.search(r"\((\d{1,2}/\d{1,2}/\d{4},\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M)\)", raw_time)
    if not match:
        return None
    try:
        parsed = datetime.strptime(match.group(1), "%m/%d/%Y, %I:%M:%S %p")
        return parsed.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _bucket_event(title: str, summary: str, category: str) -> str:
    text = f"{title} {summary} {category}".lower()
    scores: dict[str, int] = {}
    for bucket, keywords in BUCKET_KEYWORDS.items():
        scores[bucket] = sum(1 for keyword in keywords if keyword in text)

    if category.upper() == "DIPLOMACY":
        scores["diplomatic_pressure"] += 2
    if category.upper() == "CONFLICT":
        scores["battlefield_attrition"] += 1

    best_bucket = "battlefield_attrition"
    best_score = -1
    priority = [
        "regional_cost_surface",
        "commerce_and_shipping",
        "endurance_and_attrition",
        "diplomatic_pressure",
        "regime_governability",
        "battlefield_attrition",
    ]
    for bucket in priority:
        score = scores.get(bucket, 0)
        if score > best_score:
            best_bucket = bucket
            best_score = score
    return best_bucket


def _parse_high_impact_events(section: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _, title, impact, raw_time, category, sentiment, summary in HIGH_IMPACT_EVENT_RE.findall(section):
        events.append(
            {
                "title": re.sub(r"\s+", " ", title).strip(),
                "impact": int(impact),
                "raw_time": raw_time.strip(),
                "timestamp": _parse_event_timestamp(raw_time),
                "relative_time": raw_time.split("(")[0].strip(),
                "category": category.strip(),
                "sentiment": sentiment.strip(),
                "summary": re.sub(r"\s+", " ", summary).strip(),
            }
        )
    return events


def _event_sort_key(event: dict[str, Any]) -> tuple[int, datetime]:
    timestamp = event.get("timestamp")
    if timestamp:
        try:
            parsed = datetime.fromisoformat(str(timestamp))
        except ValueError:
            parsed = datetime(1970, 1, 1, tzinfo=timezone.utc)
    else:
        parsed = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return int(event.get("impact", 0)), parsed


def _select_events(events: list[dict[str, Any]]) -> tuple[list[SelectedEvent], dict[str, list[str]], list[EvidenceRef]]:
    bucket_counts = {bucket: 0 for bucket in BUCKET_KEYWORDS}
    selected_raw: list[dict[str, Any]] = []

    eights = sorted([item for item in events if int(item.get("impact", 0)) >= 8], key=_event_sort_key, reverse=True)
    sevens = sorted([item for item in events if int(item.get("impact", 0)) == 7], key=_event_sort_key, reverse=True)

    for pool in (eights, sevens):
        for item in pool:
            bucket = str(item.get("bucket"))
            if bucket_counts.get(bucket, 0) >= 2:
                continue
            selected_raw.append(item)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            if len(selected_raw) >= 8:
                break
        if len(selected_raw) >= 8:
            break

    selected_events: list[SelectedEvent] = []
    evidence_ledger: list[EvidenceRef] = []
    event_buckets: dict[str, list[str]] = {}
    for index, item in enumerate(selected_raw, start=1):
        evidence_id = f"E{index}"
        event = SelectedEvent(
            evidence_id=evidence_id,
            title=str(item["title"]),
            impact=int(item["impact"]),
            timestamp=item.get("timestamp"),
            relative_time=item.get("relative_time"),
            category=str(item["category"]),
            sentiment=str(item["sentiment"]),
            summary=str(item["summary"]),
            bucket=str(item["bucket"]),
        )
        selected_events.append(event)
        evidence_ledger.append(
            EvidenceRef(
                id=evidence_id,
                kind="event",
                authority="high",
                summary=f"{event.title} {event.summary}".strip(),
                source_ref="iranmonitor:key_events_timeline",
                timestamp=event.timestamp,
                url=None,
            )
        )
        event_buckets.setdefault(event.bucket, []).append(evidence_id)

    return selected_events, event_buckets, evidence_ledger


def build_fact_pack(source_prompt: str) -> FactPack:
    sections = _split_sections(source_prompt)
    situation = sections.get("## SITUATION OVERVIEW", "")
    news = sections.get("## 1. NEWS MEDIA ANALYSIS", "")
    internet = sections.get("## 3. INTERNET CONNECTIVITY STATUS", "")
    key_events = sections.get("## 4. KEY EVENTS TIMELINE", "")

    quality_flags: list[str] = []
    quality_flags.extend(_parse_news_quality(news))
    internet_status, internet_flags = _parse_internet_status(internet)
    quality_flags.extend(internet_flags)

    raw_events = _parse_high_impact_events(key_events)
    for item in raw_events:
        item["bucket"] = _bucket_event(str(item["title"]), str(item["summary"]), str(item["category"]))

    selected_events, event_buckets, evidence_ledger = _select_events(raw_events)
    overview = _parse_current_assessment(situation)
    overview["event_count_selected"] = len(selected_events)
    overview["event_buckets"] = sorted(bucket for bucket, ids in event_buckets.items() if ids)

    materialized = {
        "generated_at": _extract_generated_at(source_prompt),
        "overview": overview,
        "internet_status": internet_status,
        "selected_events": [asdict(item) for item in selected_events],
        "event_buckets": event_buckets,
        "evidence_ledger": [asdict(item) for item in evidence_ledger],
        "quality_flags": sorted(set(quality_flags)),
    }
    fact_pack_hash = hashlib.sha256(json.dumps(materialized, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return FactPack(
        generated_at=materialized["generated_at"],
        overview=materialized["overview"],
        internet_status=materialized["internet_status"],
        selected_events=selected_events,
        event_buckets=event_buckets,
        evidence_ledger=evidence_ledger,
        quality_flags=materialized["quality_flags"],
        fact_pack_hash=fact_pack_hash,
    )
