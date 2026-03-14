import asyncio
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import yaml

from shared.base_agent import BaseAgent
from shared.schemas import AgentMessage

SOURCES_PATH = Path("/config/sources.yaml") if Path("/config/sources.yaml").exists() else Path("config/sources.yaml")
PROPOSALS_PATH = Path("/memory/source_proposals.json") if Path("/memory").exists() else Path("memory/source_proposals.json")

CANDIDATE_POOL = {
    "telegram": [
        {"channel": "IntelSlava", "notes": "Russian-linked aggregator, useful for proxy theater, high skepticism"},
        {"channel": "IranObserver", "notes": "Iran-focused, moderate reliability"},
        {"channel": "ArabicanewsChannel", "notes": "Arabic-language aggregator, use for regional framing"},
        {"channel": "Qassam_English", "notes": "Hamas-affiliated - primary source bias, useful for faction messaging"},
        {"channel": "AlMayadeenEnglish", "notes": "Hezbollah-aligned Lebanese outlet - useful for axis messaging"},
        {"channel": "IsraeliPM", "notes": "Official Israeli government channel"},
        {"channel": "khamenei_ir", "notes": "Official Khamenei channel - primary source for regime messaging"},
        {"channel": "IranMOFA", "notes": "Iran Ministry of Foreign Affairs - official positions"},
    ],
    "rss": [
        {"url": "https://www.middleeasteye.net/rss", "outlet": "Middle East Eye", "reliability": 0.75},
        {"url": "https://english.alaraby.co.uk/rss.xml", "outlet": "Al-Araby Al-Jadeed", "reliability": 0.7},
        {
            "url": "https://carnegieendowment.org/rss/solr/articles/?fa=middle-east",
            "outlet": "Carnegie Endowment",
            "reliability": 0.85,
        },
        {"url": "https://www.stimson.org/feed/", "outlet": "Stimson Center", "reliability": 0.8},
        {"url": "https://iranprimer.usip.org/rss.xml", "outlet": "Iran Primer (USIP)", "reliability": 0.9},
    ],
    "x": [
        {"handle": "AAhronheim", "notes": "Jerusalem Post military correspondent"},
        {"handle": "hxhassan", "notes": "Hassan Hassan - Syria/ISIS/Iran analyst"},
        {"handle": "jonathanschanzer", "notes": "FDD analyst, hawkish but well-sourced on Iran finance"},
        {"handle": "KhaledElgindy", "notes": "Middle East Institute, Palestinian affairs"},
    ],
}

logger = logging.getLogger(__name__)
STREAM_LINE_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s"
    r"\[(?P<significance>[A-Z]+)\]\s"
    r"\[(?P<platform>[^\]]+)\]\s"
    r"\[(?P<outlet>[^\]]+)\]"
)


class SourceMonitorAgent(BaseAgent):
    def __init__(self, redis_url: str, groq_key: str):
        resources_path = "/config/resources.yaml" if Path("/config/resources.yaml").exists() else "config/resources.yaml"
        super().__init__("source_monitor", redis_url, groq_key, resources_path=resources_path)
        self.proposals_path = PROPOSALS_PATH
        self.stream_path = Path("/memory/stream.md") if Path("/memory/stream.md").exists() else Path("memory/stream.md")
        self.check_interval = self._env_int("SOURCE_MONITOR_CHECK_INTERVAL_SEC", 3600 * 6, minimum=300)
        jitter_max = self._env_int("SOURCE_MONITOR_STARTUP_JITTER_SEC", 60, minimum=20)
        self.startup_jitter_max = max(20, jitter_max)
        self._last_health_state_key = "last_health_check_success"

    async def start(self) -> None:
        self.proposals_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.proposals_path.exists():
            self.proposals_path.write_text("[]", encoding="utf-8")

        await self.init_runtime()
        await asyncio.gather(self.consume_loop(), self.heartbeat_loop(), self.health_check_loop())

    async def health_check_loop(self) -> None:
        startup_jitter = random.uniform(20, float(self.startup_jitter_max))
        await asyncio.sleep(startup_jitter)

        while True:
            wait = await self._seconds_until_next_health_check()
            if wait > 0:
                await asyncio.sleep(min(wait, 300))
                continue
            try:
                await self.check_source_health()
                await self.set_agent_state(self._last_health_state_key, datetime.now(timezone.utc).isoformat())
            except Exception as exc:  # noqa: BLE001
                logger.exception("source_monitor health check error")
                await self.observe("decide", f"Source health check failed: {exc}")
                await asyncio.sleep(min(self.check_interval, 300))

    async def _seconds_until_next_health_check(self) -> float:
        last_raw = await self.get_agent_state(self._last_health_state_key)
        if not last_raw:
            return 0.0
        try:
            last = datetime.fromisoformat(last_raw)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except ValueError:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return max(0.0, float(self.check_interval) - elapsed)

    async def check_source_health(self) -> None:
        await self.observe("decide", "Running source health check")
        if not self.stream_path.exists():
            return

        lines = self.stream_path.read_text(encoding="utf-8").splitlines()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

        source_stats: dict[str, dict[str, int]] = {}
        platform_stats: dict[str, dict[str, int]] = {}
        for line in lines:
            match = STREAM_LINE_RE.match(line)
            if not match:
                continue
            try:
                ts = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if ts < cutoff:
                continue

            significance = match.group("significance").strip().lower()
            platform = match.group("platform").strip()
            outlet = match.group("outlet").strip()

            if outlet not in source_stats:
                source_stats[outlet] = {"total": 0, "signal": 0}
            source_stats[outlet]["total"] += 1
            if significance in {"high", "critical"}:
                source_stats[outlet]["signal"] += 1

            if platform not in platform_stats:
                platform_stats[platform] = {"total": 0, "signal": 0}
            platform_stats[platform]["total"] += 1
            if significance in {"high", "critical"}:
                platform_stats[platform]["signal"] += 1

        if not source_stats:
            await self.observe("decide", "Not enough stream data for health check yet")
            return

        health_summary = []
        for outlet, stats in source_stats.items():
            if stats["total"] == 0:
                continue
            ratio = stats["signal"] / stats["total"]
            status = "good" if ratio > 0.15 else "low_signal" if stats["total"] > 5 else "insufficient_data"
            health_summary.append(
                {
                    "outlet": outlet,
                    "total_items": stats["total"],
                    "signal_ratio": round(ratio, 2),
                    "status": status,
                }
            )

        health_summary.sort(key=lambda item: item["signal_ratio"])
        worst_sources = [item for item in health_summary if item["status"] != "good"][:20]
        if not worst_sources:
            worst_sources = health_summary[:20]
        platform_summary = [
            {"platform": platform, "total_items": stats["total"], "signal_items": stats["signal"]}
            for platform, stats in sorted(platform_stats.items())
        ]

        await self.observe(
            "decide",
            f"Source health: {len(health_summary)} sources assessed",
            detail=json.dumps(worst_sources, indent=2),
        )

        sources_yaml = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")) or {}
        tracked_sources = {
            "telegram": [source.get("channel") for source in sources_yaml.get("telegram_channels", []) if source.get("channel")],
            "x": [source.get("handle") for source in sources_yaml.get("x_accounts", []) if source.get("handle")],
            "rss": [source.get("outlet") or source.get("url") for source in sources_yaml.get("rss_feeds", []) if source.get("url")],
        }
        candidate_compact = {
            "telegram": [item.get("channel") for item in CANDIDATE_POOL.get("telegram", []) if item.get("channel")],
            "x": [item.get("handle") for item in CANDIDATE_POOL.get("x", []) if item.get("handle")],
            "rss": [item.get("outlet") or item.get("url") for item in CANDIDATE_POOL.get("rss", []) if item.get("url")],
        }

        result = await self.llm(
            f"""You monitor source quality for an Iran conflict intelligence system.

Worst/weakest tracked sources over last 48 hours (max 20):
{json.dumps(worst_sources, indent=2)}

Platform-level totals over last 48 hours:
{json.dumps(platform_summary, indent=2)}

Currently tracked source counts:
telegram={len(tracked_sources["telegram"])}, x={len(tracked_sources["x"])}, rss={len(tracked_sources["rss"])}

Candidate identifiers (for optional proposals only):
{json.dumps(candidate_compact, indent=2)}

Tasks:
1. Flag any currently-tracked sources with worrying health (low signal, gone quiet, suspicious activity)
2. Suggest 0-2 candidates from the pool that would meaningfully improve coverage gaps
   - Only suggest if there's a genuine gap the current set doesn't cover
   - If current coverage is adequate, suggest nothing (0 proposals is fine)

Return JSON:
{{
  "flags": [{{"source": "str", "concern": "str", "action": "monitor|reduce_priority|remove"}}],
  "proposals": [{{"type": "telegram|rss|x", "identifier": "str", "reason": "str"}}]
}}""",
            model="fast",
            max_tokens=180,
            lane="background",
        )

        flags = result.get("flags", [])
        proposals = result.get("proposals", [])

        if flags:
            await self.observe("decide", f"Source flags: {len(flags)}", detail=json.dumps(flags, indent=2))

        if not proposals:
            await self.observe("decide", "Source health check complete - no new proposals")
            return

        existing = json.loads(self.proposals_path.read_text(encoding="utf-8"))
        seen = {(item.get("type"), item.get("identifier"), item.get("status")) for item in existing}

        added = 0
        for proposal in proposals:
            proposal_type = proposal.get("type")
            identifier = proposal.get("identifier")
            if not proposal_type or not identifier:
                continue
            if (proposal_type, identifier, "pending") in seen:
                continue

            existing.append(
                {
                    "id": str(uuid4()),
                    "type": proposal_type,
                    "identifier": identifier,
                    "reason": proposal.get("reason", ""),
                    "proposed_at": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",
                }
            )
            added += 1

        self.proposals_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        await self.observe(
            "decide",
            f"Proposed {added} new sources - pending human review at GET /source-proposals",
            detail=json.dumps(proposals, indent=2),
        )

    async def handle(self, message: AgentMessage) -> None:
        if message.type == "approve_source":
            await self.approve_proposal(message.payload)
        elif message.type == "reject_source":
            await self.reject_proposal(message.payload)

    async def approve_proposal(self, payload: dict) -> None:
        proposal_id = payload.get("id")
        proposals = json.loads(self.proposals_path.read_text(encoding="utf-8"))
        proposal = next((item for item in proposals if item.get("id") == proposal_id), None)
        if not proposal:
            return

        sources = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
        source_type = proposal.get("type")

        if source_type == "telegram":
            sources.setdefault("telegram_channels", []).append(
                {
                    "channel": proposal["identifier"],
                    "skepticism": "medium",
                    "reliability": 0.55,
                    "priority": "medium",
                    "added_by": "source_monitor",
                    "added_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        elif source_type == "x":
            sources.setdefault("x_accounts", []).append(
                {
                    "handle": proposal["identifier"],
                    "priority": "medium",
                    "reliability": 0.55,
                    "added_by": "source_monitor",
                    "added_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        elif source_type == "rss":
            sources.setdefault("rss_feeds", []).append(
                {
                    "url": proposal["identifier"],
                    "outlet": proposal.get("outlet", proposal["identifier"]),
                    "type": "news_wire",
                    "reliability": 0.6,
                    "added_by": "source_monitor",
                    "added_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        SOURCES_PATH.write_text(yaml.safe_dump(sources, sort_keys=False), encoding="utf-8")

        for item in proposals:
            if item.get("id") == proposal_id:
                item["status"] = "approved"
        self.proposals_path.write_text(json.dumps(proposals, indent=2), encoding="utf-8")

        await self.observe("decide", f"Source approved and added: {proposal['identifier']}")
        await self.publish("orchestrator", "reload_sources", {"source": "source_monitor"})

    async def reject_proposal(self, payload: dict) -> None:
        proposal_id = payload.get("id")
        proposals = json.loads(self.proposals_path.read_text(encoding="utf-8"))
        for item in proposals:
            if item.get("id") == proposal_id:
                item["status"] = "rejected"
        self.proposals_path.write_text(json.dumps(proposals, indent=2), encoding="utf-8")
        await self.observe("decide", f"Source proposal rejected: {proposal_id}")
