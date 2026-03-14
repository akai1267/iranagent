# IMPLEMENT.md — Autonomous Political Intelligence System
## Execution Runbook for Codex

---

## PRIME DIRECTIVE

**Plan.md is the execution source of truth. prompt.md is the governing specification.**

Voice, LLM abstraction, model routing, and agent communication are defined in prompt.md. This file implements them — it does not redefine them. In conflict, prompt.md wins.

Follow milestones in order. Validate after each. Stop and fix before proceeding.

---

## OPERATING LOOP

```
for each milestone in Plan.md:
    1. Read the full milestone before writing anything
    2. Check Documentation.md for unresolved CRITICAL issues
    3. Implement tasks in order
    4. Run validation commands
    5. if CRITICAL or MAJOR failure: stop → fix → re-run
    6. Update Documentation.md
    7. Check off tasks in Plan.md
    8. Commit: "[M{N}] {name} — validation PASS"
```

---

## MILESTONE 0 — Infrastructure

### docker-compose.yml
```yaml
version: '3.9'
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: ["redis_data:/data"]

  orchestrator:
    build:
      context: .
      dockerfile: agents/orchestrator/Dockerfile
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
    depends_on: [redis]
    volumes: ["./memory:/memory", "./config:/config"]
    restart: on-failure

  monitor:
    build:
      context: .
      dockerfile: agents/monitor/Dockerfile
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
    depends_on: [redis]
    volumes: ["./memory:/memory", "./config:/config"]
    restart: on-failure

  researcher:
    build:
      context: .
      dockerfile: agents/researcher/Dockerfile
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
      TAVILY_API_KEY: ${TAVILY_API_KEY}
    depends_on: [redis]
    volumes: ["./memory:/memory", "./config:/config"]
    restart: on-failure

  source_monitor:
    build:
      context: .
      dockerfile: agents/source_monitor/Dockerfile
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
    depends_on: [redis]
    volumes: ["./memory:/memory", "./config:/config"]
    restart: on-failure

  api:
    build:
      context: .
      dockerfile: api/Dockerfile
    ports: ["8000:8000"]
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
    depends_on: [redis]
    volumes: ["./memory:/memory"]
    restart: on-failure

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    ports: ["3000:3000"]
    depends_on: [api]

volumes:
  redis_data:
```

### shared/schemas.py
```python
from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional

class AgentMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    from_agent: str
    to_agent: str
    type: str
    payload: dict
    significance: str = "low"
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class Signal(BaseModel):
    headline: str
    source: str
    source_type: str        # news_wire | think_tank | official | x | telegram
    reliability: float      # 0.0-1.0 from sources.yaml
    url: str
    snippet: str
    significance: str       # low | medium | high | critical
    why_significant: str    # includes skepticism prefix for social sources
    timestamp: datetime

class Post(BaseModel):
    id: str
    timestamp: datetime
    title: str
    content: str
    tags: list[str]
    supersedes: Optional[str] = None

class ObservabilityEvent(BaseModel):
    agent: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    summary: str
    detail: Optional[str] = None
    event_type: str  # search|read|decide|write|interrupt|working|done
```

### shared/rate_limiter.py
```python
# shared/rate_limiter.py
# Sliding-window per-model rate limiter.
# Tracks requests and tokens in the last 60 seconds per model alias.

import time
from collections import deque

class RateLimiter:
    def __init__(self, models_config: dict):
        """
        models_config: from resources.yaml groq.models dict
        e.g. {"fast": {"rpm_limit": 30, "tpm_limit": 20000}, ...}
        """
        self.limits = {}   # alias -> {"rpm": int, "tpm": int}
        self.req_log = {}  # alias -> deque of timestamps
        self.tok_log = {}  # alias -> deque of (timestamp, tokens)

        for alias, cfg in models_config.items():
            self.limits[alias] = {
                "rpm": cfg.get("rpm_limit", 30),
                "tpm": cfg.get("tpm_limit", 6000),
            }
            self.req_log[alias] = deque()
            self.tok_log[alias] = deque()

    def _evict(self, alias: str):
        """Remove entries older than 60 seconds from both logs."""
        cutoff = time.time() - 60.0
        while self.req_log[alias] and self.req_log[alias][0] < cutoff:
            self.req_log[alias].popleft()
        while self.tok_log[alias] and self.tok_log[alias][0][0] < cutoff:
            self.tok_log[alias].popleft()

    def can_call(self, alias: str, tokens_estimate: int = 500) -> bool:
        """
        Returns True if making a call right now is within rate limits.
        Uses a conservative token estimate for the check.
        """
        if alias not in self.limits:
            return True
        self._evict(alias)
        lim = self.limits[alias]
        current_reqs = len(self.req_log[alias])
        current_toks = sum(t for _, t in self.tok_log[alias])
        return (
            current_reqs < lim["rpm"] and
            current_toks + tokens_estimate < lim["tpm"]
        )

    def record_call(self, alias: str, tokens_used: int):
        """Call this after a successful LLM response with actual token count."""
        if alias not in self.limits:
            return
        now = time.time()
        self.req_log[alias].append(now)
        self.tok_log[alias].append((now, tokens_used))

    def seconds_until_reset(self, alias: str) -> float:
        """
        Returns seconds until the oldest entry in the window expires,
        i.e. how long to wait before a slot opens.
        """
        if alias not in self.limits:
            return 0.0
        self._evict(alias)
        oldest_req = self.req_log[alias][0] if self.req_log[alias] else None
        oldest_tok = self.tok_log[alias][0][0] if self.tok_log[alias] else None
        candidates = [t for t in [oldest_req, oldest_tok] if t is not None]
        if not candidates:
            return 0.0
        # oldest entry expires at oldest_ts + 60s
        oldest = min(candidates)
        wait = (oldest + 60.0) - time.time()
        return max(0.0, wait)

    def usage_fraction(self, alias: str) -> float:
        """
        Returns the highest fraction of any limit currently consumed (0.0–1.0).
        Used by Orchestrator to decide mode transitions.
        """
        if alias not in self.limits:
            return 0.0
        self._evict(alias)
        lim = self.limits[alias]
        req_frac = len(self.req_log[alias]) / lim["rpm"]
        tok_frac = sum(t for _, t in self.tok_log[alias]) / lim["tpm"]
        return max(req_frac, tok_frac)
```

### shared/base_agent.py — Full implementation with Groq
```python
import groq
import redis.asyncio as aioredis
import json, asyncio, logging, re, time, yaml
from datetime import datetime
from uuid import uuid4
from shared.schemas import AgentMessage, ObservabilityEvent
from shared.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

MODELS = {
    "fast":     "llama-3.1-8b-instant",
    "standard": "llama-3.3-70b-versatile",
    "deep":     "deepseek-r1-distill-llama-70b"
}

DEFAULT_TEMPS = {
    "fast": 0.1,
    "standard": 0.3,
    "deep": 0.7
}

class BaseAgent:
    def __init__(self, name: str, redis_url: str, groq_key: str,
                 resources_path: str = "/config/resources.yaml"):
        self.name = name
        self.redis_url = redis_url
        self.groq_client = groq.AsyncGroq(api_key=groq_key)
        self.redis = None

        with open(resources_path) as f:
            res = yaml.safe_load(f)
        self.rate_limiter = RateLimiter(res["groq"]["models"])
        self.rate_limit_backoff = res["groq"].get("rate_limit_backoff", 62)

    async def start(self):
        self.redis = await aioredis.from_url(self.redis_url)
        logger.info(f"{self.name} started")
        await asyncio.gather(self.consume_loop(), self.heartbeat_loop())

    async def consume_loop(self):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"channel:{self.name}")
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    msg = AgentMessage(**json.loads(message["data"]))
                    await self.handle(msg)
                except Exception as e:
                    logger.error(f"{self.name} handle error: {e}")
                    await self.observe("decide", f"Message handling error: {e}")

    async def heartbeat_loop(self):
        while True:
            await self.redis.set(f"heartbeat:{self.name}", "ok", ex=30)
            await asyncio.sleep(10)

    async def publish(self, to_agent: str, msg_type: str, payload: dict,
                      significance: str = "low", trace_id=None):
        msg = AgentMessage(
            trace_id=trace_id or uuid4(),
            from_agent=self.name,
            to_agent=to_agent,
            type=msg_type,
            payload=payload,
            significance=significance
        )
        await self.redis.publish(f"channel:{to_agent}", msg.json())

    async def observe(self, event_type: str, summary: str, detail: str = None):
        event = ObservabilityEvent(
            agent=self.name,
            summary=summary,
            detail=detail,
            event_type=event_type
        )
        await self.redis.publish("channel:observatory", event.json())

    async def llm(self, prompt: str, model: str = "standard",
                  max_tokens: int = 500, temperature: float = None,
                  expect_json: bool = True) -> dict | str:
        """
        Groq LLM call. Model aliases: fast | standard | deep
        See prompt.md for canonical definition and model assignments.
        """
        model_name = MODELS[model]
        temp = temperature if temperature is not None else DEFAULT_TEMPS[model]

        # wait for rate limit window if needed
        while not self.rate_limiter.can_call(model):
            wait = self.rate_limiter.seconds_until_reset(model)
            await self.observe("decide",
                f"Rate limited on {model} ({model_name}) — waiting {wait:.0f}s")
            await asyncio.sleep(wait + 1)

        await self.observe("working",
            f"[{model}] {prompt[:80].strip()}...",
            detail=f"model={model_name} max_tokens={max_tokens}\n\n{prompt}")

        try:
            response = await self.groq_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temp
            )

            text = response.choices[0].message.content
            usage = response.usage
            tokens = usage.prompt_tokens + usage.completion_tokens

            self.rate_limiter.record_call(model, tokens)

            await self.observe("done",
                f"[{model}] {tokens} tokens",
                detail=text)

            # report usage to orchestrator
            await self.publish("orchestrator", "token_usage", {
                "tokens": tokens,
                "model": model,
                "agent": self.name
            })

            # strip DeepSeek-R1 think blocks
            if "<think>" in text:
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

            if not expect_json:
                return text

            # strip markdown JSON fences
            clean = text.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]).strip()

            return json.loads(clean)

        except groq.RateLimitError:
            await self.observe("decide",
                f"Groq rate limit error on {model} — waiting {self.rate_limit_backoff}s")
            await asyncio.sleep(self.rate_limit_backoff)
            # retry once
            response = await self.groq_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temp
            )
            text = response.choices[0].message.content
            if "<think>" in text:
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            if not expect_json:
                return text
            clean = text.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]).strip()
            return json.loads(clean)

    async def handle(self, message: AgentMessage):
        raise NotImplementedError
```

### scripts/init_db.py
```python
import sqlite3

def init(path: str = "/memory/posts.db"):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")  # concurrent read/write safety
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            supersedes TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
            title, content,
            content='posts',
            content_rowid='rowid'
        );

        CREATE TRIGGER IF NOT EXISTS posts_ai
        AFTER INSERT ON posts BEGIN
            INSERT INTO posts_fts(rowid, title, content)
            VALUES (new.rowid, new.title, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS posts_ad
        AFTER DELETE ON posts BEGIN
            INSERT INTO posts_fts(posts_fts, rowid, title, content)
            VALUES ('delete', old.rowid, old.title, old.content);
        END;

        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            added_at TEXT NOT NULL,
            priority_score REAL DEFAULT 0.5,
            last_scored TEXT,
            answered_at TEXT
        );
    """)
    conn.commit()
    conn.close()
    print("DB initialized.")

if __name__ == "__main__":
    init()
```

---

## MILESTONE 1 — Monitor

```python
# agents/monitor/agent.py
import feedparser, hashlib, asyncio, yaml
from datetime import datetime, timedelta
from pathlib import Path
from shared.base_agent import BaseAgent
from shared.schemas import Signal

SOCIAL_SKEPTICISM = {
    "x": "Unconfirmed, social source — ",
    "telegram": "Unconfirmed, Telegram channel — "
}

class MonitorAgent(BaseAgent):
    def __init__(self, redis_url, groq_key):
        super().__init__("monitor", redis_url, groq_key)
        with open("/config/sources.yaml") as f:
            self.sources_config = yaml.safe_load(f)
        self.rss_sources = self.sources_config["rss_feeds"]
        self.poll_interval = 300
        self.stream_path = Path("/memory/stream.md")

    async def start(self):
        await asyncio.gather(
            super().start(),
            self.poll_loop(),
            self.stream_wipe_loop()
        )

    async def poll_loop(self):
        while True:
            for source in self.rss_sources:
                try:
                    await self.process_rss_feed(source)
                except Exception as e:
                    await self.observe("decide", f"RSS error [{source['outlet']}]: {e}")
            await asyncio.sleep(self.poll_interval)

    async def process_rss_feed(self, source: dict):
        feed = await asyncio.to_thread(feedparser.parse, source["url"])
        for entry in feed.entries[:10]:
            url_hash = hashlib.md5(entry.link.encode()).hexdigest()
            if await self.redis.exists(f"seen:{url_hash}"):
                continue
            await self.redis.setex(f"seen:{url_hash}", 604800, "1")

            await self.observe("read",
                f"[{source['outlet']}] {entry.title}",
                detail=entry.link)

            # fast model for quick triage
            result = await self.llm(f"""Is this item significant to the Iran conflict?

Headline: {entry.title}
Snippet: {getattr(entry, 'summary', '')[:200]}
Source: {source['outlet']} ({source['type']})
Source reliability: {source.get('reliability', 0.7)}/1.0

Return JSON only: {{"significance": "low|medium|high|critical", "why": "one sentence max"}}

critical = major escalation, strike, nuclear event, war declaration
high = significant military/diplomatic/nuclear development
medium = relevant development worth tracking
low = unrelated, minor, background

Adjust threshold by reliability: {source.get('reliability', 0.7)} reliability source \
needs {'strong evidence' if source.get('reliability', 0.7) < 0.7 else 'normal evidence'} for HIGH.""",
                model="fast", max_tokens=80)

            significance = result["significance"]
            why = result["why"]

            self.write_stream(entry.title, source["outlet"], source["type"],
                              significance, why, "RSS", entry.link)

            if significance in ["medium", "high", "critical"]:
                signal = Signal(
                    headline=entry.title,
                    source=source["outlet"],
                    source_type=source["type"],
                    reliability=source.get("reliability", 0.7),
                    url=entry.link,
                    snippet=getattr(entry, "summary", "")[:500],
                    significance=significance,
                    why_significant=why,
                    timestamp=datetime.utcnow()
                )
                await self.publish("orchestrator", "signal",
                                   signal.dict(), significance=significance)
                await self.observe("decide",
                    f"Signal [{significance}]: {entry.title}", detail=signal.json())

    def write_stream(self, headline, outlet, source_type, significance, why, platform, url=""):
        line = (f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}] "
                f"[{significance.upper()}] [{platform}] [{outlet}] "
                f"{headline} — {why} — {url}\n")
        with open(self.stream_path, "a") as f:
            f.write(line)

    async def stream_wipe_loop(self):
        while True:
            self.wipe_old_stream_entries()
            await asyncio.sleep(21600)  # 6 hours

    def wipe_old_stream_entries(self):
        if not self.stream_path.exists():
            return
        cutoff = datetime.utcnow() - timedelta(hours=48)
        lines = self.stream_path.read_text().splitlines()
        kept = []
        for line in lines:
            try:
                ts = datetime.strptime(line[1:17], "%Y-%m-%d %H:%M")
                if ts > cutoff:
                    kept.append(line)
            except Exception:
                kept.append(line)
        self.stream_path.write_text("\n".join(kept) + ("\n" if kept else ""))
        # note: observe() is async, call from async context only
        # log via logger here
        import logging
        logging.getLogger(__name__).info(f"Stream wiped — kept {len(kept)} entries")

    async def handle(self, message):
        if message.type == "resource_update":
            mode = message.payload.get("mode")
            intervals = {"full": 300, "light": 900, "minimal": 3600}
            self.poll_interval = intervals.get(mode, 300)
            await self.observe("decide", f"Poll interval → {self.poll_interval}s ({mode} mode)")
```

---

## MILESTONE 2 — Monitor (X + Telegram)

Add these methods to `MonitorAgent`. The `start()` gather already runs `poll_loop()` —
add `poll_x_loop()` and `poll_telegram_loop()` to the gather in `start()`.

```python
# Add to agents/monitor/agent.py

import tweepy
from telethon import TelegramClient
from telethon.sessions import StringSession

# ── X (Twitter) via Tweepy ────────────────────────────────────────────────

async def poll_x_loop(self):
    """Poll X accounts via Tweepy every poll_interval seconds."""
    bearer = os.environ.get("TWITTER_BEARER_TOKEN")
    if not bearer:
        await self.observe("decide", "TWITTER_BEARER_TOKEN not set — X polling disabled")
        return

    client = tweepy.Client(bearer_token=bearer, wait_on_rate_limit=True)
    seen_key = "seen_x"

    while True:
        for account in self.sources_config.get("x_accounts", []):
            try:
                await asyncio.to_thread(
                    self._poll_x_account, client, account, seen_key
                )
            except Exception as e:
                await self.observe("decide", f"X error [{account['handle']}]: {e}")
        await asyncio.sleep(self.poll_interval)

def _poll_x_account(self, client, account: dict, seen_key: str):
    """Synchronous Tweepy call — run in thread via asyncio.to_thread."""
    import asyncio
    handle = account["handle"].lstrip("@")
    try:
        user = client.get_user(username=handle)
        if not user.data:
            return
        tweets = client.get_users_tweets(
            user.data.id,
            max_results=10,
            tweet_fields=["created_at", "text"],
            exclude=["retweets", "replies"]
        )
        if not tweets.data:
            return
        for tweet in tweets.data:
            tweet_key = f"seen_x:{tweet.id}"
            # Use asyncio.run_coroutine_threadsafe or store to process async
            # Here we store in a queue to be processed by async caller
            self._x_queue.append({
                "handle": handle,
                "tweet_id": tweet.id,
                "text": tweet.text,
                "key": tweet_key,
                "account": account
            })
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"X poll error [{handle}]: {e}")

async def _process_x_queue(self):
    """Process queued tweets — assess significance, write stream, signal."""
    while self._x_queue:
        item = self._x_queue.pop(0)
        if await self.redis.exists(item["key"]):
            continue
        await self.redis.setex(item["key"], 604800, "1")

        await self.observe("read",
            f"[X @{item['handle']}] {item['text'][:80]}...")

        skepticism_prefix = SOCIAL_SKEPTICISM["x"]
        result = await self.llm(
            f"""Is this tweet significant to the Iran conflict?

Account: @{item['handle']} (X/Twitter)
Tweet: {item['text']}
Note: {skepticism_prefix}Treat as unconfirmed until corroborated.
Source reliability: 0.6/1.0 (social, unverified)

Return JSON only: {{"significance": "low|medium|high|critical", "why": "one sentence max"}}

critical = major escalation, strike, nuclear event — corroboration required before critical
high = significant military/diplomatic development, plausible from this source
medium = relevant development worth tracking
low = opinion, unrelated, noise""",
            model="fast", max_tokens=80)

        self.write_stream(
            item["text"][:120], f"@{item['handle']}", "x",
            result["significance"],
            skepticism_prefix + result["why"],
            "X"
        )

        if result["significance"] in ["medium", "high", "critical"]:
            from shared.schemas import Signal
            signal = Signal(
                headline=item["text"][:200],
                source=f"@{item['handle']}",
                source_type="x",
                reliability=0.6,
                url=f"https://x.com/{item['handle']}/status/{item['tweet_id']}",
                snippet=item["text"],
                significance=result["significance"],
                why_significant=skepticism_prefix + result["why"],
                timestamp=datetime.utcnow()
            )
            await self.publish("orchestrator", "signal",
                               signal.dict(), significance=result["significance"])

# ── Telegram via Telethon ─────────────────────────────────────────────────

async def poll_telegram_loop(self):
    """
    Read recent messages from configured Telegram channels.
    Session file persisted at /memory/telegram_session (from volume mount).
    FIRST RUN: must run container interactively to complete phone auth:
      docker-compose run -it monitor python -c "
        from telethon.sync import TelegramClient
        c = TelegramClient('/memory/telegram_session',
            API_ID, API_HASH)
        c.start(phone=PHONE)
        print('Session saved.')
      "
    Subsequent runs: session file handles auth automatically.
    """
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        await self.observe("decide",
            "TELEGRAM_API_ID/HASH not set — Telegram polling disabled")
        return

    session_path = "/memory/telegram_session"
    try:
        tg = TelegramClient(session_path, int(api_id), api_hash)
        await tg.start()
        await self.observe("decide", "Telegram client connected")
    except Exception as e:
        await self.observe("decide", f"Telegram auth failed: {e} — polling disabled")
        return

    channels = self.sources_config.get("telegram_channels", [])

    while True:
        for ch in channels:
            try:
                await self._poll_telegram_channel(tg, ch)
            except Exception as e:
                await self.observe("decide",
                    f"Telegram error [{ch['channel']}]: {e}")
        await asyncio.sleep(self.poll_interval)

async def _poll_telegram_channel(self, tg: TelegramClient, ch: dict):
    channel_name = ch["channel"]
    reliability = ch.get("reliability", 0.55)
    skepticism = ch.get("skepticism", "high")  # low|medium|high

    # reliability notes for configured channels:
    # slavyangrad, colonelcassad: pro-Russian framing, valuable for proxy coverage,
    #   reliability 0.5 — needs corroboration, framing bias noted in stream
    # ddgeopolitics, geopolitics_prime, warmonitors: aggregator accounts, 0.55-0.6
    # MiddleEastSpectator, Mediterranean_Man: moderate credibility, 0.6-0.65
    # intelslava: Russian-linked, 0.45
    # financialjuice: financial/market focused, 0.5 for geopolitics

    skepticism_note = {
        "low": "Telegram channel, treat as unconfirmed — ",
        "medium": "Telegram channel, unconfirmed, moderate skepticism — ",
        "high": "Telegram channel, unconfirmed, high skepticism — may carry editorial bias — "
    }.get(skepticism, "Unconfirmed Telegram — ")

    messages = await tg.get_messages(channel_name, limit=5)
    for msg in messages:
        if not msg.text:
            continue
        msg_key = f"seen_tg:{channel_name}:{msg.id}"
        if await self.redis.exists(msg_key):
            continue
        await self.redis.setex(msg_key, 604800, "1")

        await self.observe("read",
            f"[Telegram {channel_name}] {msg.text[:80]}...")

        result = await self.llm(
            f"""Is this Telegram message significant to the Iran conflict?

Channel: {channel_name} (Telegram)
Message: {msg.text[:400]}
Note: {skepticism_note}
Source reliability: {reliability}/1.0

Return JSON only: {{"significance": "low|medium|high|critical", "why": "one sentence max"}}

critical = major escalation event — requires corroboration from higher-reliability source
high = significant development plausible from this source type
medium = worth tracking
low = noise, off-topic, unverifiable claim""",
            model="fast", max_tokens=80)

        full_why = skepticism_note + result["why"]
        self.write_stream(
            msg.text[:120], channel_name, "telegram",
            result["significance"], full_why, "Telegram"
        )

        if result["significance"] in ["medium", "high", "critical"]:
            from shared.schemas import Signal
            signal = Signal(
                headline=msg.text[:200],
                source=channel_name,
                source_type="telegram",
                reliability=reliability,
                url=f"https://t.me/{channel_name}/{msg.id}",
                snippet=msg.text[:500],
                significance=result["significance"],
                why_significant=full_why,
                timestamp=datetime.utcnow()
            )
            await self.publish("orchestrator", "signal",
                               signal.dict(), significance=result["significance"])
```

### Update `__init__` and `start()` in MonitorAgent:
```python
def __init__(self, redis_url, groq_key):
    super().__init__("monitor", redis_url, groq_key)
    with open("/config/sources.yaml") as f:
        self.sources_config = yaml.safe_load(f)
    self.rss_sources = self.sources_config["rss_feeds"]
    self.poll_interval = 300
    self.stream_path = Path("/memory/stream.md")
    self._x_queue = []  # buffer for sync->async X tweet processing

async def start(self):
    self.stream_path.touch(exist_ok=True)  # ensure file exists
    await asyncio.gather(
        super().start(),
        self.poll_loop(),
        self.poll_x_loop(),
        self.poll_telegram_loop(),
        self.stream_wipe_loop(),
        self._x_queue_processor()
    )

async def _x_queue_processor(self):
    """Drain X tweet queue continuously."""
    while True:
        if self._x_queue:
            await self._process_x_queue()
        await asyncio.sleep(5)
```

### Add `import os` to monitor imports.

---

## MILESTONE 3 — Orchestrator

```python
# agents/orchestrator/agent.py
import asyncio, yaml
from shared.base_agent import BaseAgent
from shared.schemas import Signal

class OrchestratorAgent(BaseAgent):
    def __init__(self, redis_url, groq_key):
        super().__init__("orchestrator", redis_url, groq_key)
        self.researcher_state = "idle"
        self.researcher_focus = None
        self.queue = asyncio.PriorityQueue()
        self.last_mode = "full"
        # per-model usage tracked by rate_limiter in base_agent

    async def start(self):
        await asyncio.gather(
            super().start(),
            self.queue_processor(),
            self.mode_monitor()
        )

    def current_mode(self) -> str:
        """
        Mode based on whether any critical model (standard/deep) is near its limit.
        Fast model hitting limit only reduces monitor polling, not researcher work.
        """
        for model in ["standard", "deep"]:
            if not self.rate_limiter.can_call(model):
                return "light"
        return "full"

    async def mode_monitor(self):
        while True:
            mode = self.current_mode()
            if mode != self.last_mode:
                self.last_mode = mode
                for agent in ["monitor", "researcher"]:
                    await self.publish(agent, "resource_update", {"mode": mode})
                await self.observe("decide", f"Mode → {mode.upper()}")
            await asyncio.sleep(15)  # check frequently — rate limits reset per minute

    async def handle(self, message):
        if message.type == "signal":
            await self.route_signal(message)
        elif message.type == "status":
            self.researcher_state = message.payload.get("state", "idle")
            self.researcher_focus = message.payload.get("focus")
        elif message.type == "token_usage":
            # rate_limiter already updated by the calling agent
            # orchestrator just observes
            pass
        elif message.type == "query":
            await self.route_query(message)

    async def route_signal(self, message):
        signal = Signal(**message.payload)
        mode = self.current_mode()

        await self.observe("decide",
            f"Signal [{signal.significance}] from {signal.source}: {signal.headline}",
            detail=signal.json())

        if mode == "minimal" and signal.significance != "critical":
            await self.observe("decide", "MINIMAL — skipping non-critical signal")
            return

        if signal.significance == "critical":
            await self.publish("researcher", "interrupt",
                               message.payload, significance="critical")
            await self.observe("decide", "CRITICAL — interrupting researcher immediately")

        elif signal.significance == "high" and self.researcher_state == "idle":
            await self.publish("researcher", "interrupt",
                               message.payload, significance="high")

        else:
            priority = {"critical": 0, "high": 1, "medium": 2}.get(signal.significance, 3)
            await self.queue.put((priority, signal.dict()))
            await self.observe("decide",
                f"[{signal.significance}] queued — researcher is {self.researcher_state}")

    async def queue_processor(self):
        while True:
            if self.researcher_state == "idle" and not self.queue.empty():
                _, payload = await self.queue.get()
                await self.publish("researcher", "interrupt", payload)
            await asyncio.sleep(5)

    async def route_query(self, message):
        urgent = message.payload.get("urgent", False)
        if urgent:
            await self.publish("researcher", "interrupt",
                               message.payload, significance="high")
        else:
            await self.publish("researcher", "query", message.payload)
        await self.observe("decide",
            f"Query routed (urgent={urgent}): {message.payload.get('question', '')[:60]}")
```

---

## MILESTONE 4 — Researcher

```python
# agents/researcher/agent.py
import asyncio, sqlite3, yaml, json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from shared.base_agent import BaseAgent
from shared.schemas import Post

DB = "/memory/posts.db"
THEORIES_PATH = Path("/memory/working_theories.md")
STREAM_PATH = Path("/memory/stream.md")

# Model routing — see prompt.md for rationale
CALL_MODELS = {
    "post_judgment":         "fast",
    "stream_assessment":     "standard",
    "question_priority":     "standard",
    "tether_check":          "standard",
    "theories_update_check": "standard",
    "write_post":            "deep",
    "update_theories":       "deep",
    "answer_question":       "deep",
    "seed_theories":         "deep",
}

# Voice system prompt — canonical in prompt.md, implemented here
# Includes few-shot examples per prompt.md requirements
VOICE_PROMPT = """You write in the voice of a brilliant friend who has been thinking hard 
about the Iran conflict for a long time.

Rules:
- Lead with your assessment. Then reasoning.
- Have a point of view. State it. Don't hide behind "analysts say."
- Confidence matches reality: "This is clear..." / "My best read is..." / "Genuinely uncertain here..."
- No false balance. If evidence points one way, say so.
- Cite sources informally: "per the IAEA February report..." / "Telegram reporting, unconfirmed..."
- If updating a prior: say explicitly what changed and why.

GOOD EXAMPLE — write like this:
"Iran is not striking directly right now and the reason is straightforward if you look at the economics. Another round of sanctions would be devastating — the rial is already in freefall and the IRGC knows domestic pressure is at a threshold. The proxy route gives them deniability and keeps the pressure on without triggering the response they can't afford. That's not restraint, that's calculation."

BAD EXAMPLE — never write like this:
"Multiple analysts have suggested that Iran may be considering various options in response to recent developments. It remains to be seen how the situation will evolve, as different stakeholders have competing interests that could influence outcomes in unpredictable ways."

Never write: "Multiple competing assessments" / "It remains to be seen" / 
"Some analysts argue X while others contend Y" without your view on who's right."""

class ResearcherAgent(BaseAgent):
    def __init__(self, redis_url, groq_key, tavily_key):
        super().__init__("researcher", redis_url, groq_key)
        self.tavily_key = tavily_key
        with open("/config/domain.yaml") as f:
            self.domain = yaml.safe_load(f)
        with open("/config/resources.yaml") as f:
            self.res_config = yaml.safe_load(f)
        self.mode = "full"
        self.state = "idle"
        self.db = None

    async def start(self):
        self.db = sqlite3.connect(DB, check_same_thread=False)
        await self.seed_theories_if_empty()
        await self.report_state("idle")
        await asyncio.gather(super().start(), self.main_loop())

    async def seed_theories_if_empty(self):
        content = THEORIES_PATH.read_text() if THEORIES_PATH.exists() else ""
        if len(content.strip()) < 20:
            await self.observe("decide", "Seeding initial working theories")
            seed = await self.llm(
                self.domain["initial_priors_prompt"],
                model=CALL_MODELS["seed_theories"],
                max_tokens=500,
                expect_json=False
            )
            THEORIES_PATH.write_text(seed)
            await self.observe("write", "Working theories seeded", detail=seed)

    async def report_state(self, state: str, focus: str = None):
        self.state = state
        await self.publish("orchestrator", "status", {"state": state, "focus": focus})

    async def handle(self, message):
        if message.type == "interrupt":
            await self.handle_interrupt(message.payload, message.significance)
        elif message.type == "query":
            await self.handle_query(message.payload)
        elif message.type == "resource_update":
            self.mode = message.payload.get("mode", "full")
            await self.observe("decide", f"Mode updated to {self.mode}")

    async def main_loop(self):
        while True:
            if self.state == "idle":
                await self.check_stream()
                await self.prioritize_questions()
                questions = self.get_open_questions()
                if questions and self.mode == "full":
                    top = questions[0]
                    await self.deep_dive(top["question"], top["id"])
            await asyncio.sleep(30)

    async def check_stream(self):
        if not STREAM_PATH.exists():
            return
        lines = STREAM_PATH.read_text().splitlines()
        recent = [l for l in lines[-30:] if l.strip()]
        if not recent:
            return

        theories = THEORIES_PATH.read_text()
        await self.observe("read", "Checking stream", detail="\n".join(recent))

        result = await self.llm(f"""Recent stream entries:
{chr(10).join(recent)}

Your working theories:
{theories}

Does anything here:
1. Meaningfully change the current picture?
2. Surface a new open question worth researching?

Return JSON: {{"changes_picture": bool, "what": "description or null",
               "new_question": "question or null"}}""",
            model=CALL_MODELS["stream_assessment"], max_tokens=200)

        if result.get("new_question"):
            self.add_question(result["new_question"])
            await self.observe("decide", f"New question: {result['new_question']}")

        if result.get("changes_picture") and result.get("what"):
            await self.consider_post({"context": result["what"], "from": "stream"})

    async def prioritize_questions(self):
        questions = self.get_open_questions()
        if len(questions) < 2:
            return

        stream_recent = STREAM_PATH.read_text().splitlines()[-15:] if STREAM_PATH.exists() else []

        result = await self.llm(f"""Score and rank these open research questions by priority.

Questions:
{[{'id': q['id'], 'question': q['question'], 'age_hours': q['age_hours']} for q in questions]}

Recent stream:
{chr(10).join(stream_recent)}

Score each 0.0-1.0 by: centrality to conflict understanding, recency signal, age.

Return JSON: {{"ranked": [{{"id": "str", "score": 0.0}}]}}""",
            model=CALL_MODELS["question_priority"], max_tokens=300)

        for item in result.get("ranked", []):
            self.db.execute(
                "UPDATE questions SET priority_score=?, last_scored=? WHERE id=?",
                (item["score"], datetime.utcnow().isoformat(), item["id"])
            )
        self.db.commit()

    def get_open_questions(self, limit: int = 10) -> list[dict]:
        rows = self.db.execute("""
            SELECT id, question, added_at, priority_score,
            ROUND((julianday('now') - julianday(added_at)) * 24, 1) as age_hours
            FROM questions WHERE answered_at IS NULL
            ORDER BY priority_score DESC LIMIT ?
        """, (limit,)).fetchall()
        return [{"id": r[0], "question": r[1], "added_at": r[2],
                 "priority_score": r[3], "age_hours": r[4]} for r in rows]

    def add_question(self, question: str):
        # Deduplicate by exact text — near-duplicates handled by question priority LLM
        existing = self.db.execute(
            "SELECT id FROM questions WHERE question = ? AND answered_at IS NULL",
            (question,)
        ).fetchone()
        if existing:
            return  # already tracking this question
        self.db.execute(
            "INSERT INTO questions (id, question, added_at, priority_score) VALUES (?,?,?,?)",
            (str(uuid4()), question, datetime.utcnow().isoformat(), 0.5)
        )
        self.db.commit()

    def search_posts(self, query: str, limit: int = 5) -> list[dict]:
        rows = self.db.execute("""
            SELECT p.id, p.timestamp, p.title, p.content, p.tags, p.supersedes
            FROM posts p JOIN posts_fts f ON p.rowid = f.rowid
            WHERE posts_fts MATCH ?
            ORDER BY p.timestamp DESC LIMIT ?
        """, (query, limit)).fetchall()
        return [{"id": r[0], "timestamp": r[1], "title": r[2],
                 "content": r[3], "tags": r[4], "supersedes": r[5]} for r in rows]

    def save_post(self, post: Post):
        self.db.execute(
            "INSERT INTO posts (id, timestamp, title, content, tags, supersedes) VALUES (?,?,?,?,?,?)",
            (post.id, post.timestamp.isoformat(), post.title, post.content,
             ",".join(post.tags), post.supersedes)
        )
        self.db.commit()

    async def handle_interrupt(self, payload: dict, significance: str):
        await self.report_state("interrupted", payload.get("headline", ""))
        await self.observe("interrupt",
            f"[{significance}] {payload.get('headline', '')[:80]}", detail=str(payload))
        await self.consider_post(payload)
        await self.report_state("idle")

    async def consider_post(self, context):
        # Extract search terms from context — FTS needs keywords, not a dict string
        if isinstance(context, dict):
            fts_query = context.get("headline") or context.get("question") or                         context.get("context") or str(list(context.values())[:2])
        else:
            fts_query = str(context)
        fts_query = fts_query[:120].strip()
        prior_posts = self.search_posts(fts_query)
        theories = THEORIES_PATH.read_text()

        judgment = await self.llm(f"""Context: {str(context)[:500]}

Recent relevant posts:
{[p['timestamp'][:10] + ' — ' + p['title'] for p in prior_posts]}

Working theories:
{theories[:500]}

Worth publishing? Only yes if: draws connections sources aren't making, has implications
others aren't drawing, revises prior thinking, or surfaces meaningful uncertainty.
Not if: just summarizes sources, repeats a recent post.

Return JSON: {{"worth_posting": bool, "reason": "one sentence",
               "supersedes_id": "post id or null"}}""",
            model=CALL_MODELS["post_judgment"], max_tokens=120)

        await self.observe("decide",
            f"Post: {'YES' if judgment['worth_posting'] else 'NO'} — {judgment['reason']}")

        if judgment["worth_posting"]:
            await self.write_post(context, judgment.get("supersedes_id"))

    async def write_post(self, context, supersedes_id: str = None):
        await self.report_state("writing")
        if isinstance(context, dict):
            fts_query = context.get("headline") or context.get("question") or                         context.get("context") or str(list(context.values())[:2])
        else:
            fts_query = str(context)
        prior_posts = self.search_posts(fts_query[:120].strip())
        theories = THEORIES_PATH.read_text()
        superseded_note = ""

        if supersedes_id:
            prior = self.db.execute(
                "SELECT title, timestamp FROM posts WHERE id=?", (supersedes_id,)
            ).fetchone()
            if prior:
                superseded_note = f"\nThis updates: '{prior[0]}' ({prior[1][:10]}). Acknowledge what changed and why."

        result = await self.llm(f"""{VOICE_PROMPT}
{superseded_note}

Context: {str(context)[:800]}

Working theories:
{theories}

Relevant prior posts (most recent first):
{[p['timestamp'][:10] + ': ' + p['content'][:250] for p in prior_posts]}

Write the post. Whatever length the thought requires — two sentences or several paragraphs.
Return JSON: {{"title": "str", "content": "str", "tags": ["str"]}}""",
            model=CALL_MODELS["write_post"], max_tokens=1000)

        post = Post(
            id=str(uuid4()),
            timestamp=datetime.utcnow(),
            title=result["title"],
            content=result["content"],
            tags=result.get("tags", []),
            supersedes=supersedes_id
        )
        self.save_post(post)
        await self.observe("write", f"Post: {post.title}", detail=post.content)
        await self.maybe_update_theories(post.content)
        await self.report_state("idle")

    async def maybe_update_theories(self, post_content: str):
        theories = THEORIES_PATH.read_text()
        check = await self.llm(f"""Post written:
{post_content[:500]}

Current working theories:
{theories}

Did this change HOW YOU THINK — not just what you know?
Warranted: pattern confirmed as prior, prior overturned, new useful lens.
Not warranted: new facts fitting existing priors.

Return JSON: {{"update_warranted": bool, "what_changes": "str or null"}}""",
            model=CALL_MODELS["theories_update_check"], max_tokens=120)

        if check["update_warranted"]:
            updated = await self.llm(f"""Current working theories:
{theories}

What changes: {check['what_changes']}

Rewrite incorporating this update. First person, direct. Priors and lenses, not facts.
Return the full updated document text only.""",
                model=CALL_MODELS["update_theories"], max_tokens=600, expect_json=False)
            THEORIES_PATH.write_text(updated)
            await self.observe("write", "Theories updated", detail=updated)
```

---

## MILESTONE 5 — Deep Dive + Conversation

```python
# Add to ResearcherAgent

async def deep_dive(self, question: str, question_id: str):
    budget = self.res_config["dive_budget"].get(self.mode, 0)
    if budget == 0:
        await self.observe("decide", f"{self.mode.upper()} mode — skipping dive: {question}")
        return

    await self.report_state("diving", question)
    readings, calls = [], 0
    current_q = question

    while calls < budget:
        results = await self.search_web(current_q)
        calls += 1
        await self.observe("search", f"Search: {current_q}",
            detail=str([r.get("title", r["url"]) for r in results[:5]]))

        for result in results[:3]:
            if calls >= budget:
                break
            try:
                content = await self.fetch_content(result["url"])
                readings.append({"content": content[:3000], "source": result["url"],
                                  "title": result.get("title", "")})
                calls += 1
                await self.observe("read",
                    f"Read: {result.get('title', result['url'])[:80]}",
                    detail=content[:2000])
            except Exception as e:
                await self.observe("decide", f"Fetch error: {e}")

        if not readings:
            break

        # tether check — enforced condition, not a comment
        check = await self.llm(f"""Researching: "{question}"
Sub-question: "{current_q}"
Tether: {self.domain['tether_rule']}

Recent readings:
{[r['content'][:250] for r in readings[-3:]]}

1. Does continuing sharpen understanding of the Iran conflict specifically?
2. Follow-up question? (null if exhausted or diverging)

Return JSON: {{"sharpens_conflict": bool, "follow_up": "str or null", "reason": "brief"}}""",
            model=CALL_MODELS["tether_check"], max_tokens=150)
        calls += 1

        await self.observe("decide",
            f"Tether: {'CONTINUE' if check['sharpens_conflict'] else 'STOP'} — {check['reason']}")

        if not check["sharpens_conflict"]:
            break
        if not check["follow_up"]:
            break
        current_q = check["follow_up"]

    self.db.execute(
        "UPDATE questions SET answered_at=? WHERE id=?",
        (datetime.utcnow().isoformat(), question_id)
    )
    self.db.commit()

    if readings:
        await self.consider_post({
            "question": question,
            "findings": [r["content"][:400] for r in readings[:3]],
            "sources": [r["source"] for r in readings]
        })

    await self.report_state("idle")

async def handle_query(self, payload: dict):
    question = payload.get("question", "")
    trace_id = payload.get("trace_id", str(uuid4()))

    await self.report_state("answering", question)
    relevant = self.search_posts(question, limit=5)
    theories = THEORIES_PATH.read_text()
    stream = STREAM_PATH.read_text().splitlines()[-15:] if STREAM_PATH.exists() else []

    response = await self.llm(f"""{VOICE_PROMPT}

Question: {question}

Your prior posts on this topic (cite as "as I wrote on [date], [title]..."):
{[p['timestamp'][:10] + ' — ' + p['title'] + ': ' + p['content'][:300] for p in relevant]}

Working theories:
{theories}

Recent stream:
{chr(10).join(stream)}

Answer directly. Cite your own posts. If you don't know, say so — but say what you do know.""",
        model=CALL_MODELS["answer_question"], max_tokens=800, expect_json=False)

    await self.redis.publish(
        f"channel:response:{trace_id}",
        json.dumps({"answer": response, "trace_id": trace_id})
    )
    await self.observe("write", f"Answered: {question[:60]}", detail=response)
    await self.report_state("idle")

async def search_web(self, query: str) -> list[dict]:
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.post("https://api.tavily.com/search", json={
            "api_key": self.tavily_key,
            "query": query,
            "search_depth": "basic",
            "max_results": 5
        })
    return r.json().get("results", [])

async def fetch_content(self, url: str) -> str:
    import httpx
    from bs4 import BeautifulSoup
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    return " ".join(p.get_text() for p in soup.find_all("p"))[:5000]
```

---

## MILESTONE 5b — API (implement alongside M5, before Frontend)

```python
# api/main.py
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis.asyncio as aioredis
import json, sqlite3, asyncio, os
from uuid import uuid4

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])

@app.get("/health")
async def health():
    r = await aioredis.from_url("redis://redis:6379")
    agents = {}
    for a in ["orchestrator", "monitor", "researcher"]:
        val = await r.get(f"heartbeat:{a}")
        agents[a] = "ok" if val else "down"
    return {"status": "ok", "agents": agents}

@app.websocket("/ws/observatory")
async def observatory(ws: WebSocket):
    await ws.accept()
    r = await aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
    p = r.pubsub()
    await p.subscribe("channel:observatory")
    try:
        async for msg in p.listen():
            if msg["type"] == "message":
                await ws.send_text(msg["data"])
    except Exception:
        pass  # client disconnected
    finally:
        await p.unsubscribe("channel:observatory")
        await r.aclose()

@app.get("/posts")
async def get_posts(limit: int = 50, tag: str = None):
    conn = sqlite3.connect("/memory/posts.db")
    q = "SELECT * FROM posts WHERE tags LIKE ? ORDER BY timestamp DESC LIMIT ?" if tag else \
        "SELECT * FROM posts ORDER BY timestamp DESC LIMIT ?"
    args = (f"%{tag}%", limit) if tag else (limit,)
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [{"id": r[0], "timestamp": r[1], "title": r[2],
             "content": r[3], "tags": r[4], "supersedes": r[5]} for r in rows]

@app.get("/questions")
async def get_questions():
    conn = sqlite3.connect("/memory/posts.db")
    rows = conn.execute(
        "SELECT id, question, priority_score FROM questions WHERE answered_at IS NULL ORDER BY priority_score DESC"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "question": r[1], "priority": r[2]} for r in rows]

@app.get("/working-theories")
async def working_theories():
    import os, datetime
    path = "/memory/working_theories.md"
    try:
        with open(path) as f:
            content = f.read()
        mtime = os.path.getmtime(path)
        updated_at = datetime.datetime.utcfromtimestamp(mtime).isoformat() + "Z"
        return {"content": content, "updated_at": updated_at}
    except FileNotFoundError:
        return {"content": "", "updated_at": None}

class ChatRequest(BaseModel):
    question: str
    urgent: bool = False

@app.post("/chat")
async def chat(body: ChatRequest):
    question = body.question
    urgent = body.urgent
    trace_id = str(uuid4())
    r = await aioredis.from_url("redis://redis:6379")
    await r.publish("channel:orchestrator", json.dumps({
        "from_agent": "user", "to_agent": "orchestrator",
        "type": "query", "payload": {"question": question, "urgent": urgent, "trace_id": trace_id},
        "trace_id": trace_id, "significance": "high" if urgent else "low", "id": trace_id
    }))
    p = r.pubsub()
    await p.subscribe(f"channel:response:{trace_id}")
    try:
        async with asyncio.timeout(30):
            async for msg in p.listen():
                if msg["type"] == "message":
                    data = json.loads(msg["data"])
                    return {"answer": data["answer"], "trace_id": trace_id}
    except asyncio.TimeoutError:
        return {"answer": "Still working on it — try again in a moment.", "trace_id": trace_id}
```

---

---

## SOURCE HEALTH MONITOR — New Agent

A lightweight fourth agent. Watches source quality over time, proposes additions from a
curated seed list, flags degraded sources. Does NOT autonomously add sources — it proposes,
the user approves via a review queue in the UI.

```python
# agents/source_monitor/agent.py
import asyncio, yaml, json, sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from shared.base_agent import BaseAgent

DB = "/memory/posts.db"
SOURCES_PATH = Path("/config/sources.yaml")
PROPOSALS_PATH = Path("/memory/source_proposals.json")

# Curated seed list — human-vetted sources to draw proposals from.
# Agent never reaches outside this list. Add to it manually when needed.
CANDIDATE_POOL = {
    "telegram": [
        {"channel": "IntelSlava", "notes": "Russian-linked aggregator, useful for proxy theater, high skepticism"},
        {"channel": "IranObserver", "notes": "Iran-focused, moderate reliability"},
        {"channel": "ArabicanewsChannel", "notes": "Arabic-language aggregator, use for regional framing"},
        {"channel": "Qassam_English", "notes": "Hamas-affiliated — primary source bias, useful for faction messaging"},
        {"channel": "AlMayadeenEnglish", "notes": "Hezbollah-aligned Lebanese outlet — useful for axis messaging"},
        {"channel": "IsraeliPM", "notes": "Official Israeli government channel"},
        {"channel": "khamenei_ir", "notes": "Official Khamenei channel — primary source for regime messaging"},
        {"channel": "IranMOFA", "notes": "Iran Ministry of Foreign Affairs — official positions"},
    ],
    "rss": [
        {"url": "https://www.middleeasteye.net/rss", "outlet": "Middle East Eye", "reliability": 0.75},
        {"url": "https://english.alaraby.co.uk/rss.xml", "outlet": "Al-Araby Al-Jadeed", "reliability": 0.7},
        {"url": "https://carnegieendowment.org/rss/solr/articles/?fa=middle-east", "outlet": "Carnegie Endowment", "reliability": 0.85},
        {"url": "https://www.stimson.org/feed/", "outlet": "Stimson Center", "reliability": 0.8},
        {"url": "https://iranprimer.usip.org/rss.xml", "outlet": "Iran Primer (USIP)", "reliability": 0.9},
    ],
    "x": [
        {"handle": "AAhronheim", "notes": "Jerusalem Post military correspondent"},
        {"handle": "hxhassan", "notes": "Hassan Hassan — Syria/ISIS/Iran analyst"},
        {"handle": "jonathanschanzer", "notes": "FDD analyst, hawkish but well-sourced on Iran finance"},
        {"handle": "KhaledElgindy", "notes": "Middle East Institute, Palestinian affairs"},
    ]
}

class SourceMonitorAgent(BaseAgent):
    def __init__(self, redis_url, groq_key):
        super().__init__("source_monitor", redis_url, groq_key)
        self.proposals_path = PROPOSALS_PATH
        self.check_interval = 3600 * 6  # every 6 hours

    async def start(self):
        PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not PROPOSALS_PATH.exists():
            PROPOSALS_PATH.write_text("[]")
        await asyncio.gather(
            super().start(),
            self.health_check_loop()
        )

    async def health_check_loop(self):
        while True:
            await self.check_source_health()
            await asyncio.sleep(self.check_interval)

    async def check_source_health(self):
        """
        Score each source by signal/noise ratio from recent stream entries.
        Flag sources that have gone quiet or are producing mostly LOW signals.
        Propose candidates from pool if a category is underperforming.
        """
        await self.observe("decide", "Running source health check")

        stream_path = Path("/memory/stream.md")
        if not stream_path.exists():
            return

        lines = stream_path.read_text().splitlines()
        cutoff = datetime.utcnow() - timedelta(hours=48)

        # Parse stream entries and compute per-source signal quality
        source_stats = {}  # source -> {"total": int, "high_or_critical": int}
        for line in lines:
            try:
                ts = datetime.strptime(line[1:17], "%Y-%m-%d %H:%M")
                if ts < cutoff:
                    continue
                # line format: [ts] [SIGNIFICANCE] [PLATFORM] [OUTLET] ...
                parts = line.split("] [")
                if len(parts) < 4:
                    continue
                significance = parts[1].strip().lower()
                outlet = parts[3].strip().rstrip("]")
                if outlet not in source_stats:
                    source_stats[outlet] = {"total": 0, "signal": 0}
                source_stats[outlet]["total"] += 1
                if significance in ["high", "critical"]:
                    source_stats[outlet]["signal"] += 1
            except Exception:
                continue

        if not source_stats:
            await self.observe("decide", "Not enough stream data for health check yet")
            return

        # Build health report
        health_summary = []
        for outlet, stats in source_stats.items():
            if stats["total"] == 0:
                continue
            ratio = stats["signal"] / stats["total"]
            health_summary.append({
                "outlet": outlet,
                "total_items": stats["total"],
                "signal_ratio": round(ratio, 2),
                "status": "good" if ratio > 0.15 else "low_signal" if stats["total"] > 5 else "insufficient_data"
            })

        health_summary.sort(key=lambda x: x["signal_ratio"])

        await self.observe("decide",
            f"Source health: {len(health_summary)} sources assessed",
            detail=json.dumps(health_summary, indent=2))

        # Ask LLM to interpret and propose
        sources_yaml = yaml.safe_load(SOURCES_PATH.read_text())
        current_channels = [s.get("channel", s.get("handle", s.get("outlet", "")))
                           for s in (
                               sources_yaml.get("telegram_channels", []) +
                               sources_yaml.get("x_accounts", []) +
                               sources_yaml.get("rss_feeds", [])
                           )]

        result = await self.llm(f"""You monitor source quality for an Iran conflict intelligence system.

Source health over last 48 hours:
{json.dumps(health_summary, indent=2)}

Currently tracked sources: {current_channels}

Available candidates to propose (not yet tracked):
{json.dumps(CANDIDATE_POOL, indent=2)}

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
            model="standard", max_tokens=400)

        flags = result.get("flags", [])
        proposals = result.get("proposals", [])

        if flags:
            await self.observe("decide",
                f"Source flags: {len(flags)}",
                detail=json.dumps(flags, indent=2))

        if proposals:
            # Store proposals for human review — do not auto-add to sources.yaml
            existing = json.loads(PROPOSALS_PATH.read_text())
            for p in proposals:
                p["proposed_at"] = datetime.utcnow().isoformat()
                p["status"] = "pending"
                existing.append(p)
            PROPOSALS_PATH.write_text(json.dumps(existing, indent=2))
            await self.observe("decide",
                f"Proposed {len(proposals)} new sources — pending human review at GET /source-proposals",
                detail=json.dumps(proposals, indent=2))
        else:
            await self.observe("decide", "Source health check complete — no new proposals")

    async def handle(self, message):
        if message.type == "approve_source":
            await self.approve_proposal(message.payload)
        elif message.type == "reject_source":
            await self.reject_proposal(message.payload)

    async def approve_proposal(self, payload: dict):
        """
        Add approved source to sources.yaml.
        Called when user approves a proposal via the UI.
        """
        proposal_id = payload.get("id")
        proposals = json.loads(PROPOSALS_PATH.read_text())
        proposal = next((p for p in proposals if p.get("id") == proposal_id), None)
        if not proposal:
            return

        sources = yaml.safe_load(SOURCES_PATH.read_text())
        src_type = proposal.get("type")

        if src_type == "telegram":
            sources.setdefault("telegram_channels", []).append({
                "channel": proposal["identifier"],
                "skepticism": "medium",
                "reliability": 0.55,
                "priority": "medium",
                "added_by": "source_monitor",
                "added_at": datetime.utcnow().isoformat()
            })
        elif src_type == "x":
            sources.setdefault("x_accounts", []).append({
                "handle": proposal["identifier"],
                "priority": "medium",
                "added_by": "source_monitor",
                "added_at": datetime.utcnow().isoformat()
            })
        elif src_type == "rss":
            sources.setdefault("rss_feeds", []).append({
                "url": proposal["identifier"],
                "outlet": proposal.get("outlet", proposal["identifier"]),
                "type": "news_wire",
                "reliability": 0.6,
                "added_by": "source_monitor",
                "added_at": datetime.utcnow().isoformat()
            })

        SOURCES_PATH.write_text(yaml.dump(sources, default_flow_style=False))

        # Mark proposal as approved
        for p in proposals:
            if p.get("id") == proposal_id:
                p["status"] = "approved"
        PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))

        await self.observe("decide", f"Source approved and added: {proposal['identifier']}")

        # Notify monitor to reload sources
        await self.publish("monitor", "reload_sources", {})

    async def reject_proposal(self, payload: dict):
        proposal_id = payload.get("id")
        proposals = json.loads(PROPOSALS_PATH.read_text())
        for p in proposals:
            if p.get("id") == proposal_id:
                p["status"] = "rejected"
        PROPOSALS_PATH.write_text(json.dumps(proposals, indent=2))
        await self.observe("decide", f"Source proposal rejected: {payload.get('identifier', '')}")
```

### Add `GET /source-proposals` and `POST /source-proposals/{id}/approve|reject` to API:
```python
@app.get("/source-proposals")
async def get_source_proposals():
    proposals_path = "/memory/source_proposals.json"
    try:
        proposals = json.loads(open(proposals_path).read())
        return [p for p in proposals if p.get("status") == "pending"]
    except FileNotFoundError:
        return []

@app.post("/source-proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str):
    r = await aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
    await r.publish("channel:source_monitor", json.dumps({
        "from_agent": "user", "to_agent": "source_monitor",
        "type": "approve_source", "payload": {"id": proposal_id},
        "significance": "low", "id": str(uuid4()), "trace_id": str(uuid4())
    }))
    return {"status": "approved"}

@app.post("/source-proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str):
    r = await aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
    await r.publish("channel:source_monitor", json.dumps({
        "from_agent": "user", "to_agent": "source_monitor",
        "type": "reject_source", "payload": {"id": proposal_id},
        "significance": "low", "id": str(uuid4()), "trace_id": str(uuid4())
    }))
    return {"status": "rejected"}
```

### agents/source_monitor/Dockerfile:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agents/source_monitor/ ./agents/source_monitor/
COPY shared/ ./shared/
COPY config/ ./config/
CMD ["python", "-m", "agents.source_monitor.main"]
```

### agents/source_monitor/main.py:
```python
import asyncio, os
from agents.source_monitor.agent import SourceMonitorAgent

async def main():
    agent = SourceMonitorAgent(
        redis_url=os.environ["REDIS_URL"],
        groq_key=os.environ["GROQ_API_KEY"]
    )
    await agent.start()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## SCOPING RULES

- **Voice defined in prompt.md.** VOICE_PROMPT here includes the few-shot examples from prompt.md. Do not modify without updating prompt.md.
- **Model routing defined in prompt.md.** CALL_MODELS dict here implements it. Do not change model assignments without updating prompt.md.
- **No vector store, no knowledge graph, three agents only.**
- **Posts immutable.** INSERT only. No UPDATE on posts table.
- **Tether rule is `if not check["sharpens_conflict"]: break`.** Not a comment.
- **Rate limiting waits for window reset.** Never degrades model quality mid-thought. Never crashes on rate limit.
- **Telegram session file** must be on persisted volume — mount it at `/memory/telegram_session` not in container root.

---

*Implements prompt.md and Plan.md. Does not redefine voice, model routing, or agent comms.*
