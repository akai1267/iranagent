import asyncio
import hashlib
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml
from telethon import TelegramClient
from telethon.sessions import StringSession

from shared.base_agent import BaseAgent
from shared.schemas import AgentMessage, Signal

logger = logging.getLogger(__name__)

SOCIAL_SKEPTICISM = {
    "x": "Unconfirmed, social source — ",
    "telegram": "Telegram channel, unconfirmed — ",
}

DEFAULT_NITTER_BASES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
]
DEFAULT_SOCIAL_RELEVANCE_KEYWORDS = [
    "iran",
    "tehran",
    "israel",
    "idf",
    "irgc",
    "hezbollah",
    "houthi",
    "hamas",
    "gaza",
    "nuclear",
    "iaea",
    "centcom",
    "strait of hormuz",
    "persian gulf",
    "sanctions",
]


class MonitorAgent(BaseAgent):
    def __init__(self, redis_url: str, groq_key: str):
        resources_path = "/config/resources.yaml" if Path("/config/resources.yaml").exists() else "config/resources.yaml"
        super().__init__("monitor", redis_url, groq_key, resources_path=resources_path)

        self.sources_path = Path("/config/sources.yaml") if Path("/config/sources.yaml").exists() else Path("config/sources.yaml")

        self.stream_path = Path("/memory/stream.md")
        if not self.stream_path.parent.exists():
            self.stream_path = Path("memory/stream.md")
        self.noise_stream_path = Path("/memory/stream_noise.md")
        if not self.noise_stream_path.parent.exists():
            self.noise_stream_path = Path("memory/stream_noise.md")

        self.resources = yaml.safe_load(Path(resources_path).read_text(encoding="utf-8"))
        self.poll_intervals = self.resources.get("poll_intervals", {"full": 300, "light": 900, "minimal": 3600})
        self.stream_cfg = self.resources.get("stream", {"max_age_hours": 48, "wipe_interval_hours": 6})

        default_mode = os.environ.get("DEFAULT_MODE", "full").strip().lower()
        self.mode = default_mode if default_mode in {"full", "light", "minimal"} else "full"
        self.poll_interval = int(self.poll_intervals.get(self.mode, 300))
        self.max_rss_items = self._env_int("MAX_RSS_ITEMS_PER_SOURCE", 3)
        self.max_x_items = self._env_int("MAX_X_ITEMS_PER_ACCOUNT", 3)
        self.max_tg_messages = self._env_int("MAX_TG_MESSAGES_PER_CHANNEL", 2)
        self.max_x_accounts_light = self._env_int("MAX_X_ACCOUNTS_PER_POLL_LIGHT", 2, minimum=1)
        self.max_tg_channels_light = self._env_int("MAX_TG_CHANNELS_PER_POLL_LIGHT", 2, minimum=1)
        self.telegram_retry_cooldown = self._env_int("TELEGRAM_RETRY_COOLDOWN_SEC", 3600, minimum=60)
        self._telegram_disabled_until = 0.0
        keyword_source = os.environ.get("SOCIAL_RELEVANCE_KEYWORDS", "")
        if keyword_source.strip():
            self.social_relevance_keywords = [token.strip().lower() for token in keyword_source.split(",") if token.strip()]
        else:
            self.social_relevance_keywords = list(DEFAULT_SOCIAL_RELEVANCE_KEYWORDS)
        configured_nitter = os.environ.get("NITTER_RSS_BASES", "")
        self.nitter_bases = [
            base.strip().rstrip("/")
            for base in configured_nitter.split(",")
            if base.strip()
        ] or DEFAULT_NITTER_BASES
        self.monitor_tick_sec = self._env_int("MONITOR_TICK_SEC", 60, minimum=10)
        self.monitor_tick_jitter_sec = self._env_int("MONITOR_TICK_JITTER_SEC", 10, minimum=0)
        self.max_rss_sources_per_tick = {
            "full": self._env_int("MAX_RSS_SOURCES_PER_TICK_FULL", 2, minimum=1),
            "light": self._env_int("MAX_RSS_SOURCES_PER_TICK_LIGHT", 1, minimum=1),
            "minimal": self._env_int("MAX_RSS_SOURCES_PER_TICK_MINIMAL", 1, minimum=1),
        }
        self.max_x_sources_per_tick = {
            "full": self._env_int("MAX_X_SOURCES_PER_TICK_FULL", 1, minimum=1),
            "light": self._env_int("MAX_X_SOURCES_PER_TICK_LIGHT", 1, minimum=1),
            "minimal": 0,
        }
        self.max_tg_sources_per_tick = {
            "full": self._env_int("MAX_TG_SOURCES_PER_TICK_FULL", 1, minimum=1),
            "light": self._env_int("MAX_TG_SOURCES_PER_TICK_LIGHT", 1, minimum=1),
            "minimal": 0,
        }
        self.max_source_delay_sec = self._env_int("MONITOR_MAX_SOURCE_DELAY_SEC", 600, minimum=30)
        self._rss_due_at: dict[str, float] = {}
        self._x_due_at: dict[str, float] = {}
        self._tg_due_at: dict[str, float] = {}

        self.sources_config = {}
        self.rss_sources = []
        self.x_sources = []
        self.telegram_sources = []
        self.load_sources()

    @staticmethod
    def _env_int(name: str, default: int, minimum: int = 0) -> int:
        value = os.environ.get(name)
        if value is None:
            return max(minimum, default)
        try:
            return max(minimum, int(value))
        except ValueError:
            return max(minimum, default)

    def _tick_sleep(self) -> float:
        if self.monitor_tick_jitter_sec <= 0:
            return float(self.monitor_tick_sec)
        return float(self.monitor_tick_sec) + random.uniform(0.0, float(self.monitor_tick_jitter_sec))

    def _source_delay(self) -> float:
        # Keep pacing smooth: mode can reduce breadth, but should not create hour-long silence windows.
        capped_interval = min(float(self.poll_interval), float(self.max_source_delay_sec))
        base = max(capped_interval, float(self.monitor_tick_sec))
        jitter = random.uniform(0.0, float(self.monitor_tick_jitter_sec)) if self.monitor_tick_jitter_sec > 0 else 0.0
        return base + jitter

    @staticmethod
    def _source_key(source: dict, preferred_key: str, prefix: str) -> str:
        value = str(source.get(preferred_key) or "").strip().lower()
        if not value:
            fallback = str(source.get("url") or source.get("outlet") or source.get("channel") or source.get("handle") or "").strip()
            value = fallback.lower()
        if value:
            return value
        source_fingerprint = repr(sorted(source.items()))
        return f"{prefix}:{hashlib.md5(source_fingerprint.encode('utf-8')).hexdigest()}"

    def _sync_due_map(self, due_map: dict[str, float], keys: list[str]) -> None:
        keep = set(keys)
        for existing in list(due_map.keys()):
            if existing not in keep:
                due_map.pop(existing, None)

        now = time.monotonic()
        startup_spread = max(float(self.monitor_tick_sec), min(float(self.poll_interval), 180.0))
        for key in keys:
            if key not in due_map:
                due_map[key] = now + random.uniform(0.0, startup_spread)

    def _mode_cap(self, caps: dict[str, int]) -> int:
        if self.mode in caps:
            return max(0, int(caps[self.mode]))
        return max(0, int(caps.get("light", 1)))

    def _due_sources(
        self,
        sources: list[dict],
        due_map: dict[str, float],
        preferred_key: str,
        prefix: str,
        limit: int,
    ) -> list[tuple[str, dict]]:
        if limit <= 0 or not sources:
            return []
        now = time.monotonic()
        candidates: list[tuple[float, str, dict]] = []
        for source in sources:
            key = self._source_key(source, preferred_key, prefix)
            if due_map.get(key, now) <= now:
                candidates.append((due_map.get(key, now), key, source))
        candidates.sort(key=lambda item: item[0])
        return [(key, source) for _, key, source in candidates[:limit]]

    def load_sources(self) -> None:
        if not self.sources_path.exists():
            logger.warning("sources.yaml not found at %s", self.sources_path)
            self.sources_config = {}
            self.rss_sources = []
            self.x_sources = []
            self.telegram_sources = []
            return

        self.sources_config = yaml.safe_load(self.sources_path.read_text(encoding="utf-8")) or {}
        self.rss_sources = self.sources_config.get("rss_feeds", [])
        self.x_sources = self.sources_config.get("x_accounts", [])
        self.telegram_sources = self.sources_config.get("telegram_channels", [])
        logger.info("Loaded %d RSS, %d X, %d Telegram sources", len(self.rss_sources), len(self.x_sources), len(self.telegram_sources))

    async def start(self) -> None:
        self.stream_path.parent.mkdir(parents=True, exist_ok=True)
        self.stream_path.touch(exist_ok=True)
        self.noise_stream_path.parent.mkdir(parents=True, exist_ok=True)
        self.noise_stream_path.touch(exist_ok=True)
        self.wipe_old_stream_entries()

        await asyncio.gather(
            super().start(),
            self.poll_loop(),
            self.poll_x_loop(),
            self.poll_telegram_loop(),
            self.stream_wipe_loop(),
        )

    async def poll_loop(self) -> None:
        while True:
            if not self.rss_sources:
                await self.observe_throttled(
                    "monitor:rss:no_sources",
                    "decide",
                    "No RSS sources configured",
                    throttle_seconds=1800,
                )
                await asyncio.sleep(self._tick_sleep())
                continue

            source_keys = [self._source_key(source, "url", "rss") for source in self.rss_sources]
            self._sync_due_map(self._rss_due_at, source_keys)
            due_sources = self._due_sources(
                self.rss_sources,
                self._rss_due_at,
                "url",
                "rss",
                self._mode_cap(self.max_rss_sources_per_tick),
            )
            for key, source in due_sources:
                try:
                    await self.process_rss_feed(source)
                except Exception as exc:  # noqa: BLE001
                    await self.observe("decide", f"RSS error [{source.get('outlet', '?')}]: {exc}")
                finally:
                    self._rss_due_at[key] = time.monotonic() + self._source_delay()
            await asyncio.sleep(self._tick_sleep())

    async def process_rss_feed(self, source: dict) -> None:
        feed = await asyncio.to_thread(feedparser.parse, source["url"])
        for entry in feed.entries[: self.max_rss_items]:
            link = getattr(entry, "link", "")
            if not link:
                continue

            url_hash = hashlib.md5(link.encode("utf-8")).hexdigest()
            if await self.redis.exists(f"seen:{url_hash}"):
                continue
            await self.redis.setex(f"seen:{url_hash}", 604800, "1")

            title = getattr(entry, "title", "(untitled)")
            snippet = getattr(entry, "summary", "")[:200]
            reliability = float(source.get("reliability", 0.7))

            await self.observe("read", f"[{source.get('outlet', 'RSS')}] {title}", detail=link)

            prompt = f"""Is this item significant to the Iran conflict?

Headline: {title}
Snippet: {snippet}
Source: {source.get('outlet', 'Unknown')} ({source.get('type', 'news_wire')})
Source reliability: {reliability}/1.0

Return JSON only: {{"significance": "low|medium|high|critical", "why": "one sentence max"}}

critical = major escalation, strike, nuclear event, war declaration
high = significant military/diplomatic/nuclear development
medium = relevant development worth tracking
low = unrelated, minor, background

Adjust threshold by reliability: {reliability} reliability source needs {'strong evidence' if reliability < 0.7 else 'normal evidence'} for HIGH."""

            result = await self.llm(prompt, model="fast", max_tokens=100, lane="background")
            significance = str(result.get("significance", "low")).lower()
            why = str(result.get("why", "No rationale provided"))

            self.write_stream(
                headline=title,
                outlet=source.get("outlet", "Unknown"),
                source_type=source.get("type", "news_wire"),
                significance=significance,
                why=why,
                platform="RSS",
                url=link,
            )

            if significance in {"medium", "high", "critical"}:
                signal = Signal(
                    headline=title,
                    source=source.get("outlet", "Unknown"),
                    source_type=source.get("type", "news_wire"),
                    reliability=reliability,
                    url=link,
                    snippet=getattr(entry, "summary", "")[:500],
                    significance=significance,
                    why_significant=why,
                    timestamp=datetime.now(timezone.utc),
                )
                await self.publish(
                    "orchestrator",
                    "signal",
                    signal.model_dump(mode="json"),
                    significance=significance,
                )
                await self.observe("decide", f"Signal [{significance}] {title}", detail=signal.model_dump_json())

    async def poll_x_loop(self) -> None:
        while True:
            if not self.x_sources:
                await self.observe_throttled(
                    "monitor:x:no_sources_configured",
                    "decide",
                    "No X accounts configured — X/Nitter polling disabled",
                    throttle_seconds=1800,
                )
                await asyncio.sleep(self._tick_sleep())
                continue

            if self.mode == "minimal":
                await self.observe_throttled(
                    "monitor:x:minimal_paused",
                    "decide",
                    "X/Nitter polling paused in minimal mode",
                )
                await asyncio.sleep(self._tick_sleep())
                continue

            accounts = self._select_x_sources_for_mode()
            if not accounts:
                await self.observe_throttled(
                    "monitor:x:no_sources_for_mode",
                    "decide",
                    f"No X accounts selected for mode={self.mode}",
                )
                await asyncio.sleep(self._tick_sleep())
                continue

            account_keys = [self._source_key(account, "handle", "x") for account in accounts]
            self._sync_due_map(self._x_due_at, account_keys)
            due_accounts = self._due_sources(
                accounts,
                self._x_due_at,
                "handle",
                "x",
                self._mode_cap(self.max_x_sources_per_tick),
            )
            for key, account in due_accounts:
                try:
                    await self.process_x_account(account)
                except Exception as exc:  # noqa: BLE001
                    await self.observe("decide", f"X error [{account.get('handle', '?')}]: {exc}")
                finally:
                    self._x_due_at[key] = time.monotonic() + self._source_delay()
            await asyncio.sleep(self._tick_sleep())

    async def process_x_account(self, account: dict) -> None:
        handle = str(account.get("handle", "")).lstrip("@")
        if not handle:
            return

        entries = await self.fetch_nitter_feed(handle)
        reliability = float(account.get("reliability", 0.6))
        prefix = SOCIAL_SKEPTICISM["x"]

        for entry in entries[: self.max_x_items]:
            link = getattr(entry, "link", "") or ""
            title = getattr(entry, "title", "") or ""
            snippet = getattr(entry, "summary", "") or ""
            text = re.sub(r"<[^>]+>", " ", f"{title} {snippet}").strip()
            if not text:
                continue

            key_hash = hashlib.md5(link.encode("utf-8")).hexdigest() if link else hashlib.md5(text.encode("utf-8")).hexdigest()
            seen_key = f"seen_xrss:{handle}:{key_hash}"
            if await self.redis.exists(seen_key):
                continue
            await self.redis.setex(seen_key, 604800, "1")

            normalized_url = self.normalize_x_url(handle, link)
            if not self._is_social_relevant(text):
                self.write_noise_stream(
                    headline=text[:120],
                    outlet=f"@{handle}",
                    source_type="x",
                    significance="low",
                    why=prefix + "No Iran-conflict keyword match; skipped model scoring.",
                    platform="X",
                    url=normalized_url,
                )
                continue

            await self.observe("read", f"[X/Nitter @{handle}] {text[:80]}...")

            result = await self.llm(
                f"""Is this X post significant to the Iran conflict?

Account: @{handle} (X via Nitter RSS)
Post: {text[:500]}
Note: {prefix}Treat as unconfirmed until corroborated.
Source reliability: {reliability}/1.0

Return JSON only: {{"significance": "low|medium|high|critical", "why": "one sentence max"}}

critical = major escalation, strike, nuclear event — corroboration required before critical
high = significant military/diplomatic development, plausible from this source
medium = relevant development worth tracking
low = opinion, unrelated, noise""",
                model="fast",
                max_tokens=100,
                lane="background",
            )

            significance = str(result.get("significance", "low")).lower()
            why = prefix + str(result.get("why", "No rationale provided"))

            self.write_stream(
                headline=text[:120],
                outlet=f"@{handle}",
                source_type="x",
                significance=significance,
                why=why,
                platform="X",
                url=normalized_url,
            )

            if significance in {"medium", "high", "critical"}:
                signal = Signal(
                    headline=text[:200],
                    source=f"@{handle}",
                    source_type="x",
                    reliability=reliability,
                    url=normalized_url,
                    snippet=text[:500],
                    significance=significance,
                    why_significant=why,
                    timestamp=datetime.now(timezone.utc),
                )
                await self.publish(
                    "orchestrator",
                    "signal",
                    signal.model_dump(mode="json"),
                    significance=significance,
                )

    async def fetch_nitter_feed(self, handle: str):
        last_error = None
        for base in self.nitter_bases:
            url = f"{base}/{handle}/rss"
            try:
                feed = await asyncio.to_thread(feedparser.parse, url)
                entries = getattr(feed, "entries", []) or []
                if entries:
                    return entries
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        raise RuntimeError(f"No Nitter RSS data for @{handle}: {last_error}")

    @staticmethod
    def normalize_x_url(handle: str, url: str) -> str:
        if not url:
            return f"https://x.com/{handle}"
        match = re.search(r"/status/(\d+)", url)
        if match:
            return f"https://x.com/{handle}/status/{match.group(1)}"
        return url

    async def poll_telegram_loop(self) -> None:
        while True:
            api_id = os.environ.get("TELEGRAM_API_ID")
            api_hash = os.environ.get("TELEGRAM_API_HASH")
            if not api_id or not api_hash:
                await self.observe_throttled(
                    "monitor:telegram:missing_api_env",
                    "decide",
                    "TELEGRAM_API_ID/HASH not set — Telegram polling disabled",
                    throttle_seconds=1800,
                )
                await asyncio.sleep(self._tick_sleep())
                continue

            if self.mode == "minimal":
                await self.observe_throttled(
                    "monitor:telegram:minimal_paused",
                    "decide",
                    "Telegram polling paused in minimal mode",
                )
                await asyncio.sleep(self._tick_sleep())
                continue

            now = time.monotonic()
            if now < self._telegram_disabled_until:
                await asyncio.sleep(min(self._tick_sleep(), max(1.0, self._telegram_disabled_until - now)))
                continue

            channels = self._select_telegram_sources_for_mode()
            if not channels:
                await self.observe_throttled(
                    "monitor:telegram:no_sources_for_mode",
                    "decide",
                    f"No Telegram channels selected for mode={self.mode}",
                )
                await asyncio.sleep(self._tick_sleep())
                continue

            channel_keys = [self._source_key(channel, "channel", "tg") for channel in channels]
            self._sync_due_map(self._tg_due_at, channel_keys)
            due_channels = self._due_sources(
                channels,
                self._tg_due_at,
                "channel",
                "tg",
                self._mode_cap(self.max_tg_sources_per_tick),
            )
            if not due_channels:
                await asyncio.sleep(self._tick_sleep())
                continue

            tg = await self._connect_telegram_client(api_id, api_hash)
            if tg is None:
                self._telegram_disabled_until = time.monotonic() + float(self.telegram_retry_cooldown)
                for key, _ in due_channels:
                    self._tg_due_at[key] = self._telegram_disabled_until
                await asyncio.sleep(min(self._tick_sleep(), float(self.telegram_retry_cooldown)))
                continue

            for key, channel in due_channels:
                try:
                    await self._poll_telegram_channel(tg, channel)
                except Exception as exc:  # noqa: BLE001
                    await self.observe("decide", f"Telegram error [{channel.get('channel', '?')}]: {exc}")
                finally:
                    self._tg_due_at[key] = time.monotonic() + self._source_delay()
            try:
                await tg.disconnect()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(self._tick_sleep())

    async def _connect_telegram_client(self, api_id: str, api_hash: str) -> TelegramClient | None:
        session_string = os.environ.get("TELEGRAM_SESSION_STRING") or os.environ.get("TG_SESSION")
        session_path = Path("/memory/telegram_session")
        if not session_path.parent.exists():
            session_path = Path("memory/telegram_session")

        if session_string:
            raw = session_string.strip()
            if "/" in raw or raw.endswith(".session"):
                maybe = Path(raw)
                if maybe.suffix == ".session":
                    maybe = maybe.with_suffix("")
                session_path = maybe
                session_string = None

        tg = None
        if session_string:
            try:
                tg = TelegramClient(StringSession(session_string), int(api_id), api_hash)
                await tg.connect()
            except Exception as exc:  # noqa: BLE001
                await self.observe_throttled(
                    "monitor:telegram:bad_session_string",
                    "decide",
                    f"Telegram session string invalid ({exc}) — falling back to file session",
                )
                tg = None

        if tg is None:
            if not session_path.exists():
                await self.observe_throttled(
                    "monitor:telegram:missing_session",
                    "decide",
                    "Telegram session missing and no valid TELEGRAM_SESSION_STRING provided — Telegram polling disabled",
                )
                return None
            try:
                tg = TelegramClient(str(session_path), int(api_id), api_hash)
                await tg.connect()
            except Exception as exc:  # noqa: BLE001
                await self.observe_throttled(
                    "monitor:telegram:file_session_error",
                    "decide",
                    f"Telegram auth failed: {exc} — polling disabled",
                )
                return None

        try:
            if not await tg.is_user_authorized():
                await self.observe_throttled(
                    "monitor:telegram:unauthorized",
                    "decide",
                    "Telegram session not authorized — Telegram polling disabled",
                )
                try:
                    await tg.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                return None
            await self.observe_throttled(
                "monitor:telegram:connected",
                "decide",
                "Telegram client connected",
                throttle_seconds=3600,
            )
            return tg
        except Exception as exc:  # noqa: BLE001
            await self.observe_throttled(
                "monitor:telegram:auth_exception",
                "decide",
                f"Telegram auth failed: {exc} — polling disabled",
            )
            try:
                await tg.disconnect()
            except Exception:  # noqa: BLE001
                pass
            return None

    async def _poll_telegram_channel(self, tg: TelegramClient, channel_cfg: dict) -> None:
        channel = channel_cfg.get("channel")
        if not channel:
            return

        reliability = float(channel_cfg.get("reliability", 0.55))
        skepticism = str(channel_cfg.get("skepticism", "high")).lower()
        skepticism_note = {
            "low": "Telegram channel, treat as unconfirmed — ",
            "medium": "Telegram channel, unconfirmed, moderate skepticism — ",
            "high": "Telegram channel, unconfirmed, high skepticism — may carry editorial bias — ",
        }.get(skepticism, "Unconfirmed Telegram — ")

        messages = await tg.get_messages(channel, limit=self.max_tg_messages)
        for msg in messages:
            text = getattr(msg, "text", None)
            if not text:
                continue

            msg_key = f"seen_tg:{channel}:{msg.id}"
            if await self.redis.exists(msg_key):
                continue
            await self.redis.setex(msg_key, 604800, "1")

            if not self._is_social_relevant(text):
                self.write_noise_stream(
                    headline=text[:120],
                    outlet=channel,
                    source_type="telegram",
                    significance="low",
                    why=skepticism_note + "No Iran-conflict keyword match; skipped model scoring.",
                    platform="Telegram",
                    url=f"https://t.me/{channel}/{msg.id}",
                )
                continue

            await self.observe("read", f"[Telegram {channel}] {text[:80]}...")

            result = await self.llm(
                f"""Is this Telegram message significant to the Iran conflict?

Channel: {channel} (Telegram)
Message: {text[:400]}
Note: {skepticism_note}
Source reliability: {reliability}/1.0

Return JSON only: {{"significance": "low|medium|high|critical", "why": "one sentence max"}}

critical = major escalation event — requires corroboration from higher-reliability source
high = significant development plausible from this source type
medium = worth tracking
low = noise, off-topic, unverifiable claim""",
                model="fast",
                max_tokens=100,
                lane="background",
            )

            significance = str(result.get("significance", "low")).lower()
            why = skepticism_note + str(result.get("why", "No rationale provided"))

            self.write_stream(
                headline=text[:120],
                outlet=channel,
                source_type="telegram",
                significance=significance,
                why=why,
                platform="Telegram",
                url=f"https://t.me/{channel}/{msg.id}",
            )

            if significance in {"medium", "high", "critical"}:
                signal = Signal(
                    headline=text[:200],
                    source=channel,
                    source_type="telegram",
                    reliability=reliability,
                    url=f"https://t.me/{channel}/{msg.id}",
                    snippet=text[:500],
                    significance=significance,
                    why_significant=why,
                    timestamp=datetime.now(timezone.utc),
                )
                await self.publish(
                    "orchestrator",
                    "signal",
                    signal.model_dump(mode="json"),
                    significance=significance,
                )

    def write_stream(
        self,
        headline: str,
        outlet: str,
        source_type: str,
        significance: str,
        why: str,
        platform: str,
        url: str = "",
    ) -> None:
        _ = source_type
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        line = f"[{stamp}] [{significance.upper()}] [{platform}] [{outlet}] {headline} — {why} — {url}\n"
        with self.stream_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def write_noise_stream(
        self,
        headline: str,
        outlet: str,
        source_type: str,
        significance: str,
        why: str,
        platform: str,
        url: str = "",
    ) -> None:
        _ = source_type
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        line = f"[{stamp}] [{significance.upper()}] [{platform}] [{outlet}] {headline} — {why} — {url}\n"
        with self.noise_stream_path.open("a", encoding="utf-8") as f:
            f.write(line)

    async def stream_wipe_loop(self) -> None:
        while True:
            self.wipe_old_stream_entries()
            await asyncio.sleep(int(self.stream_cfg.get("wipe_interval_hours", 6) * 3600))

    def wipe_old_stream_entries(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=float(self.stream_cfg.get("max_age_hours", 48)))

        def prune(path: Path) -> None:
            if not path.exists():
                return
            kept: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    ts = datetime.strptime(line[1:17], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                    if ts > cutoff:
                        kept.append(line)
                except Exception:
                    kept.append(line)

            body = "\n".join(kept)
            if body:
                body += "\n"
            path.write_text(body, encoding="utf-8")

        prune(self.stream_path)
        prune(self.noise_stream_path)

    async def handle(self, message: AgentMessage) -> None:
        if message.type == "resource_update":
            self.mode = str(message.payload.get("mode", "full")).lower()
            self.poll_interval = int(self.poll_intervals.get(self.mode, 300))
            await self.observe("decide", f"Poll interval -> {self.poll_interval}s ({self.mode})")
            return

        if message.type == "reload_sources":
            self.load_sources()
            await self.observe("decide", "Reloaded sources.yaml after source approval")

    def _is_social_relevant(self, text: str) -> bool:
        body = str(text or "").lower()
        return any(keyword in body for keyword in self.social_relevance_keywords)

    @staticmethod
    def _priority_rank(source: dict) -> int:
        priority = str(source.get("priority", "medium")).lower()
        return {"high": 0, "medium": 1, "low": 2}.get(priority, 1)

    def _select_x_sources_for_mode(self) -> list[dict]:
        ranked = sorted(self.x_sources, key=self._priority_rank)
        if self.mode == "light":
            high = [item for item in ranked if str(item.get("priority", "")).lower() == "high"]
            return high[: self.max_x_accounts_light]
        return ranked

    def _select_telegram_sources_for_mode(self) -> list[dict]:
        ranked = sorted(self.telegram_sources, key=self._priority_rank)
        if self.mode == "light":
            high = [item for item in ranked if str(item.get("priority", "")).lower() == "high"]
            return high[: self.max_tg_channels_light]
        return ranked
