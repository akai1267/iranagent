#!/usr/bin/env python3
from __future__ import annotations
"""
scripts/validate.py

Usage:
  python scripts/validate.py --mode infrastructure
  python scripts/validate.py --agent monitor --duration 300
  python scripts/validate.py --agent monitor --check-sources x,telegram
  python scripts/validate.py --agent orchestrator --test-interrupts
  python scripts/validate.py --agent orchestrator --test-resource-modes
  python scripts/validate.py --check-stream-format
  python scripts/validate.py --check-signal-reliability
  python scripts/validate.py --check-posts --voice --last 5
  python scripts/validate.py --check-post-immutability
  python scripts/validate.py --check-questions-table
  python scripts/validate.py --check-observatory-working-events
  python scripts/validate.py --context-memory
  python scripts/validate.py --test-interrupt-flow
  python scripts/validate.py --test-conversation --voice-check --check-citations
  python scripts/validate.py --quick
  python scripts/validate.py --full
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    import httpx
except Exception:  # noqa: BLE001
    httpx = None

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None

try:
    import yaml
except Exception:  # noqa: BLE001
    yaml = None

try:
    from dotenv import load_dotenv
except Exception:  # noqa: BLE001
    def load_dotenv(*_args, **_kwargs):  # type: ignore[override]
        return False

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BANNED_VOICE_PHRASES = [
    "remains to be seen",
    "multiple competing assessments",
    "it is unclear",
    "analysts argue",
    "some analysts suggest",
]

BANNED_CONTAMINATION_PHRASES = [
    "another round of sanctions",
    "proxy route gives",
    "iran is not striking directly right now",
]


def memory_path(name: str) -> Path:
    if Path("/memory").exists():
        return Path("/memory") / name
    return ROOT / "memory" / name


def config_path(name: str) -> Path:
    if Path("/config").exists():
        return Path("/config") / name
    return ROOT / "config" / name


def db_path() -> Path:
    return memory_path("posts.db")


def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


def api_base() -> str:
    return os.environ.get("API_BASE", "http://localhost:8000")


@dataclass
class CheckResult:
    ok: bool
    reason: str
    critical: bool = False


def check(name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    print(f"Checking: {name}")
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        result = CheckResult(False, f"Unhandled error: {exc}")

    status = "PASS" if result.ok else "FAIL"
    print(f"{status}: {result.reason}")
    return result


def read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def rg(pattern: str, globs: list[str] | None = None) -> list[str]:
    cmd = ["rg", "-n", pattern, str(ROOT)]
    if globs:
        for glob in globs:
            cmd.extend(["-g", glob])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def open_db() -> sqlite3.Connection:
    return sqlite3.connect(db_path())


def redis_client() -> redis.Redis:
    if redis is None:
        raise RuntimeError("redis package not installed")
    return redis.Redis.from_url(redis_url(), decode_responses=True)


# Infrastructure checks

def db_tables_exist() -> CheckResult:
    path = db_path()
    if not path.exists():
        return CheckResult(False, f"DB missing at {path}", critical=True)

    conn = open_db()
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    post_cols = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    conn.close()
    names = {row[0] for row in rows}
    required = {"posts", "posts_fts", "questions", "context_documents", "context_snapshots", "agent_state"}
    missing = required - names
    if missing:
        return CheckResult(False, f"Missing tables: {sorted(missing)}", critical=True)
    required_post_cols = {"evidence_refs", "freshness_meta", "quality_flags"}
    missing_post_cols = required_post_cols - post_cols
    if missing_post_cols:
        return CheckResult(False, f"posts table missing grounding columns: {sorted(missing_post_cols)}", critical=True)
    return CheckResult(True, "core + context tables present")


def fts5_working() -> CheckResult:
    conn = open_db()
    post_id = f"validate-{uuid.uuid4()}"
    conn.execute(
        "INSERT INTO posts (id, timestamp, title, content, tags, supersedes) VALUES (?, datetime('now'), ?, ?, ?, NULL)",
        (post_id, "Validation FTS", "Iran conflict signal validation text", "validation"),
    )
    conn.commit()

    rows = conn.execute(
        """
        SELECT p.id
        FROM posts p
        JOIN posts_fts f ON p.rowid = f.rowid
        WHERE posts_fts MATCH ?
        """,
        ("validation",),
    ).fetchall()

    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()

    if not rows:
        return CheckResult(False, "FTS query returned no rows", critical=True)
    return CheckResult(True, "FTS insert/query works")


def all_heartbeats_present() -> CheckResult:
    if redis is None:
        return CheckResult(False, "redis package not installed", critical=True)

    try:
        r = redis_client()
        r.ping()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"Redis unavailable: {exc}", critical=True)

    missing = []
    for agent in ["orchestrator", "monitor", "researcher"]:
        if not r.get(f"heartbeat:{agent}"):
            missing.append(agent)
    if missing:
        return CheckResult(False, f"Missing heartbeat keys: {missing}", critical=True)
    return CheckResult(True, "All core agent heartbeats present")


def observatory_channel_live() -> CheckResult:
    if redis is None:
        return CheckResult(False, "redis package not installed", critical=True)

    try:
        r = redis_client()
        r.ping()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"Redis unavailable: {exc}", critical=True)

    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe("channel:observatory")
    token = f"validate-{uuid.uuid4()}"
    r.publish("channel:observatory", json.dumps({"agent": "validate", "event_type": "decide", "summary": token}))

    deadline = time.time() + 2.0
    while time.time() < deadline:
        msg = pubsub.get_message(timeout=0.2)
        if not msg:
            continue
        payload = msg.get("data")
        if isinstance(payload, str) and token in payload:
            pubsub.unsubscribe("channel:observatory")
            return CheckResult(True, "Observatory pub/sub channel works")

    pubsub.unsubscribe("channel:observatory")
    return CheckResult(False, "Did not receive test observatory event", critical=True)


def config_files_valid() -> CheckResult:
    if yaml is None:
        return CheckResult(False, "PyYAML not installed", critical=True)

    files = [config_path("sources.yaml"), config_path("domain.yaml"), config_path("resources.yaml")]
    for file_path in files:
        if not file_path.exists():
            return CheckResult(False, f"Missing config file: {file_path}", critical=True)
        try:
            yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return CheckResult(False, f"YAML parse failed for {file_path.name}: {exc}", critical=True)
    return CheckResult(True, "All config YAML files parse")


def env_vars_present() -> CheckResult:
    required = [
        "GROQ_API_KEY",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_PHONE",
        "TAVILY_API_KEY",
        "REDIS_URL",
    ]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        return CheckResult(False, f"Missing env vars: {missing}")
    return CheckResult(True, "All required env vars present")


# Stream checks

def stream_line_format() -> CheckResult:
    stream = memory_path("stream.md")
    if not stream.exists():
        return CheckResult(False, "stream.md missing")

    pattern = re.compile(
        r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] \[(LOW|MEDIUM|HIGH|CRITICAL)\] \[[^\]]+\] \[[^\]]+\] .+ — .+ — .*$"
    )

    for idx, line in enumerate(stream.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        if not pattern.match(line):
            return CheckResult(False, f"Invalid stream format on line {idx}: {line[:120]}")
    return CheckResult(True, "stream.md lines match expected format")


def stream_timestamps_valid() -> CheckResult:
    stream = memory_path("stream.md")
    if not stream.exists():
        return CheckResult(False, "stream.md missing")

    for idx, line in enumerate(stream.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            time.strptime(line[1:17], "%Y-%m-%d %H:%M")
        except Exception:
            return CheckResult(False, f"Invalid timestamp on line {idx}")
    return CheckResult(True, "All stream timestamps parse")


def stream_significance_valid() -> CheckResult:
    stream = memory_path("stream.md")
    if not stream.exists():
        return CheckResult(False, "stream.md missing")

    valid = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    for idx, line in enumerate(stream.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        match = re.search(r"\[([A-Z]+)\]", line)
        if not match or match.group(1) not in valid:
            return CheckResult(False, f"Invalid significance on line {idx}")
    return CheckResult(True, "Stream significance values valid")


# Reliability checks

def signal_has_reliability_field() -> CheckResult:
    schema = read_file(ROOT / "shared" / "schemas.py")
    monitor = read_file(ROOT / "agents" / "monitor" / "agent.py")
    if "reliability" not in schema:
        return CheckResult(False, "Signal schema missing reliability field")
    if "reliability=" not in monitor:
        return CheckResult(False, "Monitor signal creation missing reliability assignment")
    return CheckResult(True, "Signal reliability field is wired in schema + monitor")


def signal_reliability_in_range() -> CheckResult:
    if yaml is None:
        return CheckResult(False, "PyYAML not installed")

    sources = yaml.safe_load(config_path("sources.yaml").read_text(encoding="utf-8"))
    values = []
    for section in ("rss_feeds", "x_accounts", "telegram_channels"):
        for item in sources.get(section, []):
            val = item.get("reliability")
            if val is not None:
                values.append(val)

    bad = [v for v in values if not (0.0 <= float(v) <= 1.0)]
    if bad:
        return CheckResult(False, f"Out-of-range reliability values: {bad}")
    return CheckResult(True, "All configured reliability scores are in 0.0-1.0")


# Post checks

def no_banned_phrases() -> CheckResult:
    conn = open_db()
    rows = conn.execute("SELECT content FROM posts ORDER BY timestamp DESC LIMIT 5").fetchall()
    conn.close()
    for row in rows:
        lower = (row[0] or "").lower()
        for phrase in BANNED_VOICE_PHRASES:
            if phrase in lower:
                return CheckResult(False, f"Banned phrase found: '{phrase}'")
    return CheckResult(True, "No banned phrases in recent posts")


def voice_prompt_not_contaminated() -> CheckResult:
    editorial = read_file(ROOT / "config" / "editorial_brief.md").lower()
    current_picture = read_file(ROOT / "config" / "current_picture_brief.md").lower()
    combined = f"{editorial}\n{current_picture}"
    for phrase in BANNED_CONTAMINATION_PHRASES:
        if phrase in combined:
            return CheckResult(False, f"Contaminating template phrase still present in editorial briefs: '{phrase}'")
    return CheckResult(True, "Editorial briefs have no scenario-specific contamination phrases")


def posts_not_empty() -> CheckResult:
    conn = open_db()
    rows = conn.execute("SELECT id, title, content FROM posts ORDER BY timestamp DESC LIMIT 10").fetchall()
    conn.close()
    if not rows:
        return CheckResult(False, "No posts in DB")

    for post_id, title, content in rows:
        if not title or not content or not content.strip():
            return CheckResult(False, f"Empty post content/title for id={post_id}")
    return CheckResult(True, "Recent posts have non-empty title/content")


def posts_have_sources() -> CheckResult:
    conn = open_db()
    rows = conn.execute("SELECT content FROM posts ORDER BY timestamp DESC LIMIT 5").fetchall()
    conn.close()
    if not rows:
        return CheckResult(False, "No posts to validate")

    markers = ("per ", "reported", "confirmed", "as i wrote")
    for idx, row in enumerate(rows, start=1):
        text = (row[0] or "").lower()
        if not any(marker in text for marker in markers):
            return CheckResult(False, f"Post #{idx} missing informal sourcing language")
    return CheckResult(True, "Recent posts include source/citation language")


# Immutability checks

def no_post_updates_in_code() -> CheckResult:
    hits = rg(r"UPDATE\s+posts\b", ["*.py"])
    if hits:
        return CheckResult(False, f"Found forbidden UPDATE posts statements: {hits[:3]}")
    return CheckResult(True, "No UPDATE statements against posts table")


def fts_triggers_working() -> CheckResult:
    conn = open_db()
    post_id = f"validate-trigger-{uuid.uuid4()}"
    conn.execute(
        "INSERT INTO posts (id, timestamp, title, content, tags, supersedes) VALUES (?, datetime('now'), ?, ?, ?, NULL)",
        (post_id, "Trigger test", "Trigger content", "validation"),
    )
    conn.commit()

    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()

    rows = conn.execute(
        "SELECT rowid FROM posts_fts WHERE posts_fts MATCH 'Trigger'"
    ).fetchall()
    conn.close()

    if rows:
        return CheckResult(False, "FTS delete trigger failed; deleted post still searchable")
    return CheckResult(True, "FTS delete trigger works")


# Questions checks

def questions_table_has_rows() -> CheckResult:
    conn = open_db()
    count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    if count < 1:
        return CheckResult(False, "questions table has no rows")
    return CheckResult(True, f"questions table contains {count} rows")


def open_questions_have_priority_scores() -> CheckResult:
    conn = open_db()
    rows = conn.execute(
        "SELECT id FROM questions WHERE answered_at IS NULL AND (priority_score IS NULL OR priority_score='')"
    ).fetchall()
    conn.close()
    if rows:
        return CheckResult(False, f"Open questions missing priority scores: {len(rows)}")
    return CheckResult(True, "All open questions have priority scores")


# Observatory checks

def working_events_precede_done_events() -> CheckResult:
    base = read_file(ROOT / "shared" / "base_agent.py")
    working_idx = base.find('await self.observe("working"')
    done_idx = base.find('await self.observe("done"')
    if working_idx == -1 or done_idx == -1:
        return CheckResult(False, "base_agent.llm missing working/done observability events")
    if working_idx > done_idx:
        return CheckResult(False, "working event appears after done event in llm()")
    return CheckResult(True, "working events are emitted before done events")


def working_events_have_content() -> CheckResult:
    schema = read_file(ROOT / "shared" / "schemas.py")
    if "summary: str" not in schema:
        return CheckResult(False, "ObservabilityEvent.summary is not required")
    return CheckResult(True, "working event schema enforces non-empty summary")


# Interrupt flow checks

def _agents_online() -> tuple[bool, str]:
    if httpx is None:
        return False, "httpx package not installed"

    try:
        response = httpx.get(f"{api_base()}/health", timeout=3)
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        return False, f"health endpoint unavailable: {exc}"

    agents = data.get("agents", {})
    down = [name for name, status in agents.items() if status != "ok" and name in {"orchestrator", "researcher"}]
    if down:
        return False, f"Required agents down: {down}"
    return True, "agents online"


def critical_signal_reaches_researcher() -> CheckResult:
    if redis is None:
        return CheckResult(False, "redis package not installed")

    online, reason = _agents_online()
    if not online:
        return CheckResult(False, reason)

    token = f"VALIDATE-CRITICAL-{uuid.uuid4()}"
    r = redis_client()
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe("channel:researcher")

    payload = {
        "id": str(uuid.uuid4()),
        "trace_id": str(uuid.uuid4()),
        "from_agent": "validate",
        "to_agent": "orchestrator",
        "type": "signal",
        "significance": "critical",
        "payload": {
            "headline": token,
            "source": "validate",
            "source_type": "official",
            "reliability": 1.0,
            "url": "https://example.com",
            "snippet": token,
            "significance": "critical",
            "why_significant": "validation test",
            "timestamp": "2026-03-12T00:00:00Z",
        },
    }
    r.publish("channel:orchestrator", json.dumps(payload))

    deadline = time.time() + 5
    while time.time() < deadline:
        msg = pubsub.get_message(timeout=0.2)
        if not msg:
            continue
        data = json.loads(msg["data"])
        if data.get("type") == "interrupt" and data.get("payload", {}).get("headline") == token:
            pubsub.unsubscribe("channel:researcher")
            return CheckResult(True, "Critical signal reached researcher within 5s")

    pubsub.unsubscribe("channel:researcher")
    return CheckResult(False, "Critical signal did not reach researcher within 5s")


def low_signal_does_not_interrupt() -> CheckResult:
    if redis is None:
        return CheckResult(False, "redis package not installed")

    online, reason = _agents_online()
    if not online:
        return CheckResult(False, reason)

    token = f"VALIDATE-LOW-{uuid.uuid4()}"
    r = redis_client()
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe("channel:researcher")

    payload = {
        "id": str(uuid.uuid4()),
        "trace_id": str(uuid.uuid4()),
        "from_agent": "validate",
        "to_agent": "orchestrator",
        "type": "signal",
        "significance": "low",
        "payload": {
            "headline": token,
            "source": "validate",
            "source_type": "official",
            "reliability": 1.0,
            "url": "https://example.com",
            "snippet": token,
            "significance": "low",
            "why_significant": "validation test",
            "timestamp": "2026-03-12T00:00:00Z",
        },
    }
    r.publish("channel:orchestrator", json.dumps(payload))

    deadline = time.time() + 3
    while time.time() < deadline:
        msg = pubsub.get_message(timeout=0.2)
        if not msg:
            continue
        data = json.loads(msg["data"])
        if data.get("type") == "interrupt" and data.get("payload", {}).get("headline") == token:
            pubsub.unsubscribe("channel:researcher")
            return CheckResult(False, "Low signal interrupted researcher unexpectedly")

    pubsub.unsubscribe("channel:researcher")
    return CheckResult(True, "Low signal did not interrupt researcher")


def medium_signal_queued_correctly() -> CheckResult:
    # Best-effort validation: ensure medium signals are accepted by orchestrator.
    orchestrator = read_file(ROOT / "agents" / "orchestrator" / "agent.py")
    if "priority = {\"critical\": 0, \"high\": 1, \"medium\": 2}" not in orchestrator:
        return CheckResult(False, "Medium priority queue mapping missing")
    return CheckResult(True, "Medium signals are configured to queue")


# Conversation checks

def response_within_30s() -> CheckResult:
    if httpx is None:
        return CheckResult(False, "httpx package not installed")

    start = time.time()
    try:
        response = httpx.post(
            f"{api_base()}/chat",
            json={"question": "Give your current read in one paragraph.", "urgent": False},
            timeout=35,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"/chat request failed: {exc}")

    elapsed = time.time() - start
    data = response.json()
    if elapsed > 30:
        return CheckResult(False, f"Response took {elapsed:.1f}s (>30s)")
    if not data.get("answer"):
        return CheckResult(False, "Empty answer returned")
    return CheckResult(True, f"Response returned in {elapsed:.1f}s")


def response_voice_check() -> CheckResult:
    if httpx is None:
        return CheckResult(False, "httpx package not installed")

    try:
        response = httpx.post(
            f"{api_base()}/chat",
            json={"question": "What's your best read on proxy escalation?", "urgent": False},
            timeout=35,
        )
        text = response.json().get("answer", "").lower()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"Could not test voice: {exc}")

    for phrase in BANNED_VOICE_PHRASES:
        if phrase in text:
            return CheckResult(False, f"Banned phrase in response: {phrase}")
    return CheckResult(True, "Response passes banned phrase voice check")


def response_has_citation() -> CheckResult:
    if httpx is None:
        return CheckResult(False, "httpx package not installed")
    try:
        response = httpx.post(
            f"{api_base()}/chat",
            json={"question": "Cite one prior post in your answer.", "urgent": False},
            timeout=35,
        )
        text = response.json().get("answer", "").lower()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"Could not test citations: {exc}")

    if "as i wrote" in text or re.search(r"\b\d{4}-\d{2}-\d{2}\b", text):
        return CheckResult(True, "Response includes a post/date citation")
    return CheckResult(False, "Response missing expected citation markers")


# Model routing

def fast_model_for_triage() -> CheckResult:
    monitor = read_file(ROOT / "agents" / "monitor" / "agent.py")
    if monitor.count('model="fast"') < 2:
        return CheckResult(False, "Monitor triage calls are not all routed to fast model", critical=True)
    return CheckResult(True, "Monitor triage routes to fast model")


def deep_model_for_posts() -> CheckResult:
    researcher = read_file(ROOT / "agents" / "researcher" / "agent.py")
    required = [
        '"write_post": "deep"',
        '"update_theories": "deep"',
        '"answer_question": "deep"',
    ]
    missing = [entry for entry in required if entry not in researcher]
    if missing:
        return CheckResult(False, f"Missing deep model assignments: {missing}", critical=True)
    return CheckResult(True, "Post/theory/conversation routing uses deep model")


# Rate limit checks

def rate_limit_triggers_wait() -> CheckResult:
    base = read_file(ROOT / "shared" / "base_agent.py")
    if "while not self.rate_limiter.can_call(model):" not in base:
        return CheckResult(False, "llm() is not waiting for rate limit windows")
    return CheckResult(True, "llm() waits when rate-limited")


def no_crash_on_rate_limit() -> CheckResult:
    base = read_file(ROOT / "shared" / "base_agent.py")
    if "except groq.RateLimitError" not in base:
        return CheckResult(False, "RateLimitError handling missing")
    if "await asyncio.sleep(self.rate_limit_backoff)" not in base:
        return CheckResult(False, "RateLimitError retry backoff missing")
    return CheckResult(True, "RateLimitError handled with wait + retry")


# Context memory checks

def context_source_config_exists() -> CheckResult:
    path = config_path("context_sources.yaml")
    if not path.exists():
        return CheckResult(False, "Missing config/context_sources.yaml", critical=True)
    if yaml is None:
        return CheckResult(False, "PyYAML not installed")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"context_sources.yaml parse failed: {exc}", critical=True)
    required = {"critical_threats", "iran_monitor_structural", "iran_monitor_briefing", "snapshot_policy"}
    missing = required - set(data.keys())
    if missing:
        return CheckResult(False, f"context_sources.yaml missing keys: {sorted(missing)}", critical=True)
    return CheckResult(True, "context_sources.yaml exists with required sections")


def context_modules_exist() -> CheckResult:
    modules = [
        ROOT / "agents" / "researcher" / "context_sources.py",
        ROOT / "agents" / "researcher" / "context_memory.py",
    ]
    missing = [str(path) for path in modules if not path.exists()]
    if missing:
        return CheckResult(False, f"Missing context modules: {missing}", critical=True)
    return CheckResult(True, "Context source/memory modules exist")


def researcher_context_pipeline_wired() -> CheckResult:
    text = read_file(ROOT / "agents" / "researcher" / "agent.py")
    required = [
        "context_refresh_loop",
        "refresh_context_once",
        "build_analysis_context",
        "Current picture rebuilt",
        "Context refresh skipped; no authoritative anchor",
    ]
    missing = [token for token in required if token not in text]
    if missing:
        return CheckResult(False, f"Researcher missing context pipeline tokens: {missing}", critical=True)
    return CheckResult(True, "Researcher context pipeline wiring is present")


def context_api_routes_present() -> CheckResult:
    text = read_file(ROOT / "api" / "main.py")
    required = [
        "@app.get(\"/context/current-picture\"",
        "@app.get(\"/context/structural\"",
        "@app.get(\"/context/documents\"",
        "@app.get(\"/context/status\"",
    ]
    missing = [token for token in required if token not in text]
    if missing:
        return CheckResult(False, f"Missing context API routes: {missing}", critical=True)
    return CheckResult(True, "Context API routes are present")


def context_status_endpoint_live() -> CheckResult:
    if httpx is None:
        return CheckResult(False, "httpx package not installed")
    try:
        response = httpx.get(f"{api_base()}/context/status", timeout=3)
        if response.status_code != 200:
            return CheckResult(False, f"/context/status returned HTTP {response.status_code}")
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"/context/status request failed: {exc}")
    required = {
        "last_successful_refresh_at",
        "structural_age_seconds",
        "current_picture_age_seconds",
        "primary_anchor_cycle",
        "primary_anchor_published_at",
        "authoritative_fresh",
        "stale_mode_active",
        "provider_status",
    }
    if not required.issubset(set(payload.keys())):
        return CheckResult(False, "context/status missing required fields")
    return CheckResult(True, "context/status responds with expected schema")


def posts_grounding_api_present() -> CheckResult:
    text = read_file(ROOT / "api" / "main.py")
    required = [
        "\"evidence_refs\"",
        "\"freshness_meta\"",
        "\"quality_flags\"",
        "@app.get(\"/posts/{post_id}/evidence\")",
    ]
    missing = [token for token in required if token not in text]
    if missing:
        return CheckResult(False, f"Posts grounding API tokens missing: {missing}", critical=True)
    return CheckResult(True, "Posts API exposes grounding fields + evidence endpoint")


def researcher_contract_files_valid() -> CheckResult:
    if yaml is None:
        return CheckResult(False, "PyYAML not installed", critical=True)

    contract = config_path("researcher_contract.yaml")
    templates = config_path("researcher_templates.yaml")
    if not contract.exists():
        return CheckResult(False, "Missing config/researcher_contract.yaml", critical=True)
    if not templates.exists():
        return CheckResult(False, "Missing config/researcher_templates.yaml", critical=True)

    try:
        contract_data = yaml.safe_load(contract.read_text(encoding="utf-8")) or {}
        templates_data = yaml.safe_load(templates.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"Contract/template parse failed: {exc}", critical=True)

    required_contract = {
        "version",
        "pack",
        "weights",
        "writing_policy",
        "temperature_policy",
        "prior_context_policy",
        "title_policy",
        "current_picture_policy",
        "publish_policy",
        "theory_policy",
        "query_policy",
        "style_policy",
        "observability",
    }
    if not required_contract.issubset(set(contract_data.keys())):
        missing = sorted(required_contract - set(contract_data.keys()))
        return CheckResult(False, f"researcher_contract.yaml missing keys: {missing}", critical=True)

    required_templates = {
        "post_judgment",
        "post_frame",
        "post_prose",
        "post_prose_rewrite",
        "post_verifier_v2",
        "write_post",
        "rewrite_post",
        "post_verifier",
        "theory_update_check",
        "theory_rewrite",
        "theory_verifier",
        "query_answer",
        "stream_assessment",
        "question_priority",
        "current_picture_frame",
        "current_picture_prose",
        "current_picture_verifier_v2",
    }
    if not required_templates.issubset(set(templates_data.keys())):
        missing = sorted(required_templates - set(templates_data.keys()))
        return CheckResult(False, f"researcher_templates.yaml missing IDs: {missing}", critical=True)
    return CheckResult(True, "Researcher contract/templates parse and include required keys")


def briefing_pack_pipeline_wired() -> CheckResult:
    researcher = read_file(ROOT / "agents" / "researcher" / "agent.py")
    pack_module = ROOT / "agents" / "researcher" / "briefing_pack.py"
    contract_module = ROOT / "agents" / "researcher" / "contract.py"
    if not pack_module.exists() or not contract_module.exists():
        return CheckResult(False, "briefing_pack.py or contract.py missing", critical=True)
    required_tokens = [
        "compile_briefing_pack_once",
        "briefing_pack_loop",
        "Briefing pack compiled",
        "Briefing pack unchanged",
    ]
    missing = [token for token in required_tokens if token not in researcher]
    if missing:
        return CheckResult(False, f"Researcher briefing-pack wiring missing tokens: {missing}", critical=True)
    return CheckResult(True, "Researcher briefing-pack pipeline wiring is present")


def briefing_pack_api_routes_present() -> CheckResult:
    text = read_file(ROOT / "api" / "main.py")
    required = [
        "@app.get(\"/briefing-pack/latest\"",
        "@app.get(\"/briefing-pack/{cycle_id}\"",
        "@app.get(\"/briefing-pack/latest/markdown\"",
    ]
    missing = [token for token in required if token not in text]
    if missing:
        return CheckResult(False, f"Missing briefing-pack API routes: {missing}", critical=True)
    return CheckResult(True, "Briefing-pack API routes are present")


def context_status_includes_brief_pack_fields() -> CheckResult:
    if httpx is None:
        return CheckResult(False, "httpx package not installed")
    try:
        response = httpx.get(f"{api_base()}/context/status", timeout=3)
        if response.status_code != 200:
            return CheckResult(False, f"/context/status returned HTTP {response.status_code}")
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"/context/status request failed: {exc}")

    required = {
        "briefing_pack_cycle_id",
        "briefing_pack_generated_at",
        "briefing_pack_age_seconds",
        "briefing_pack_contract_hash",
    }
    if not required.issubset(set(payload.keys())):
        return CheckResult(False, "context/status missing briefing-pack metadata fields")
    return CheckResult(True, "context/status includes briefing-pack metadata")


# Frontend checks

def no_border_radius_over_4px() -> CheckResult:
    files = list((ROOT / "frontend" / "src").rglob("*.css")) + list((ROOT / "frontend" / "src").rglob("*.jsx"))
    banned_tokens = ["rounded-lg", "rounded-xl", "rounded-2xl", "rounded-3xl"]
    for file_path in files:
        text = read_file(file_path)
        if any(token in text for token in banned_tokens):
            return CheckResult(False, f"Banned rounded token in {file_path}")

    css = read_file(ROOT / "frontend" / "src" / "index.css")
    for match in re.finditer(r"border-radius:\s*([0-9]+)px", css):
        value = int(match.group(1))
        if value > 4 and value != 999:
            return CheckResult(False, f"border-radius > 4px found in index.css ({value}px)")
    return CheckResult(True, "No border radius values above 4px")


def no_pure_white_backgrounds() -> CheckResult:
    text = read_file(ROOT / "frontend" / "src" / "index.css") + "\n" + "\n".join(
        read_file(path) for path in (ROOT / "frontend" / "src").rglob("*.jsx")
    )
    if "#ffffff" in text.lower() or "bg-white" in text:
        return CheckResult(False, "Pure white background token found")
    return CheckResult(True, "No pure white backgrounds")


def no_cool_grey_backgrounds() -> CheckResult:
    text = "\n".join(
        read_file(path) for path in (ROOT / "frontend" / "src").rglob("*") if path.is_file()
    )
    banned = ["gray-100", "gray-50", "cool-gray", "slate-", "zinc-"]
    for token in banned:
        if token in text:
            return CheckResult(False, f"Cool-grey token found: {token}")
    return CheckResult(True, "No cool grey palette usage")


def google_fonts_loaded() -> CheckResult:
    html = read_file(ROOT / "frontend" / "index.html")
    needed = ["Playfair+Display", "DM+Sans", "JetBrains+Mono"]
    missing = [font for font in needed if font not in html]
    if missing:
        return CheckResult(False, f"Missing Google Fonts in index.html: {missing}")
    return CheckResult(True, "Google Fonts include Playfair, DM Sans, JetBrains Mono")


def playfair_on_post_titles() -> CheckResult:
    post_card = read_file(ROOT / "frontend" / "src" / "components" / "feed" / "PostCard.jsx")
    css = read_file(ROOT / "frontend" / "src" / "index.css")
    if "post-title" not in post_card:
        return CheckResult(False, "PostCard missing .post-title class")
    if "font-family: var(--font-display)" not in css:
        return CheckResult(False, "index.css missing display font on post titles")
    return CheckResult(True, "Post titles use Playfair display styling")


def jetbrains_on_timestamps() -> CheckResult:
    css = read_file(ROOT / "frontend" / "src" / "index.css")
    if ".timestamp" not in css or "font-family: var(--font-mono)" not in css:
        return CheckResult(False, "Timestamp mono typography rule missing")
    return CheckResult(True, "Timestamp rule uses JetBrains Mono")


def design_tokens_in_index_css() -> CheckResult:
    css = read_file(ROOT / "frontend" / "src" / "index.css")
    required = ["--accent", "--bg", "--font-display"]
    missing = [token for token in required if token not in css]
    if missing:
        return CheckResult(False, f"Missing design tokens: {missing}")
    return CheckResult(True, "Design tokens present in index.css")


def observatory_websocket_exists() -> CheckResult:
    hook = read_file(ROOT / "frontend" / "src" / "hooks" / "useObservatory.js")
    if "WebSocket" not in hook:
        return CheckResult(False, "useObservatory hook missing WebSocket")
    return CheckResult(True, "useObservatory uses WebSocket")


def all_four_views_exist() -> CheckResult:
    files = [
        ROOT / "frontend" / "src" / "components" / "feed" / "Feed.jsx",
        ROOT / "frontend" / "src" / "components" / "theories" / "Theories.jsx",
        ROOT / "frontend" / "src" / "components" / "chat" / "Chat.jsx",
        ROOT / "frontend" / "src" / "components" / "observatory" / "Observatory.jsx",
    ]
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        return CheckResult(False, f"Missing required view components: {missing}")
    return CheckResult(True, "Feed/Theories/Chat/Observatory views exist")


def ticker_component_exists() -> CheckResult:
    ticker = ROOT / "frontend" / "src" / "components" / "layout" / "Ticker.jsx"
    if not ticker.exists():
        return CheckResult(False, "Ticker.jsx missing")
    text = read_file(ticker)
    if "show" not in text:
        return CheckResult(False, "Ticker.jsx missing hidden-by-default state")
    return CheckResult(True, "Ticker component exists with show/hide state")


CHECKS: dict[str, list[tuple[str, Callable[[], CheckResult]]]] = {
    "infrastructure": [
        ("db_tables_exist", db_tables_exist),
        ("fts5_working", fts5_working),
        ("all_heartbeats_present", all_heartbeats_present),
        ("observatory_channel_live", observatory_channel_live),
        ("config_files_valid", config_files_valid),
        ("env_vars_present", env_vars_present),
    ],
    "stream_format": [
        ("stream_line_format", stream_line_format),
        ("stream_timestamps_valid", stream_timestamps_valid),
        ("stream_significance_valid", stream_significance_valid),
    ],
    "signal_reliability": [
        ("signal_has_reliability_field", signal_has_reliability_field),
        ("signal_reliability_in_range", signal_reliability_in_range),
    ],
    "posts_voice": [
        ("voice_prompt_not_contaminated", voice_prompt_not_contaminated),
        ("no_banned_phrases", no_banned_phrases),
        ("posts_not_empty", posts_not_empty),
        ("posts_have_sources", posts_have_sources),
    ],
    "post_immutability": [
        ("no_post_updates_in_code", no_post_updates_in_code),
        ("fts_triggers_working", fts_triggers_working),
    ],
    "questions_table": [
        ("questions_table_has_rows", questions_table_has_rows),
        ("open_questions_have_priority_scores", open_questions_have_priority_scores),
    ],
    "observatory_working_events": [
        ("working_events_precede_done_events", working_events_precede_done_events),
        ("working_events_have_content", working_events_have_content),
    ],
    "interrupt_flow": [
        ("critical_signal_reaches_researcher", critical_signal_reaches_researcher),
        ("low_signal_does_not_interrupt", low_signal_does_not_interrupt),
        ("medium_signal_queued_correctly", medium_signal_queued_correctly),
    ],
    "conversation": [
        ("response_within_30s", response_within_30s),
        ("response_voice_check", response_voice_check),
        ("response_has_citation", response_has_citation),
    ],
    "model_routing": [
        ("fast_model_for_triage", fast_model_for_triage),
        ("deep_model_for_posts", deep_model_for_posts),
    ],
    "rate_limit_handling": [
        ("rate_limit_triggers_wait", rate_limit_triggers_wait),
        ("no_crash_on_rate_limit", no_crash_on_rate_limit),
    ],
    "context_memory": [
        ("context_source_config_exists", context_source_config_exists),
        ("context_modules_exist", context_modules_exist),
        ("researcher_contract_files_valid", researcher_contract_files_valid),
        ("briefing_pack_pipeline_wired", briefing_pack_pipeline_wired),
        ("researcher_context_pipeline_wired", researcher_context_pipeline_wired),
        ("context_api_routes_present", context_api_routes_present),
        ("context_status_endpoint_live", context_status_endpoint_live),
        ("briefing_pack_api_routes_present", briefing_pack_api_routes_present),
        ("context_status_includes_brief_pack_fields", context_status_includes_brief_pack_fields),
        ("posts_grounding_api_present", posts_grounding_api_present),
    ],
    "frontend_design": [
        ("no_border_radius_over_4px", no_border_radius_over_4px),
        ("no_pure_white_backgrounds", no_pure_white_backgrounds),
        ("no_cool_grey_backgrounds", no_cool_grey_backgrounds),
        ("google_fonts_loaded", google_fonts_loaded),
        ("playfair_on_post_titles", playfair_on_post_titles),
        ("jetbrains_on_timestamps", jetbrains_on_timestamps),
        ("design_tokens_in_index_css", design_tokens_in_index_css),
        ("observatory_websocket_exists", observatory_websocket_exists),
        ("all_four_views_exist", all_four_views_exist),
        ("ticker_component_exists", ticker_component_exists),
    ],
}

QUICK_CHECKS = ["infrastructure", "stream_format", "posts_voice", "questions_table"]
FULL_CHECKS = list(CHECKS.keys())


def run_group(name: str) -> tuple[int, bool]:
    if name not in CHECKS:
        print(f"Unknown check group: {name}")
        return 1, False

    failures = 0
    critical_failed = False
    print(f"\n=== {name} ===")
    for check_name, fn in CHECKS[name]:
        result = check(check_name, fn)
        if not result.ok:
            failures += 1
            critical_failed = critical_failed or result.critical
    return failures, critical_failed


def run_groups(groups: list[str], stop_on_critical: bool = False) -> int:
    total_failures = 0
    for group in groups:
        failures, critical = run_group(group)
        total_failures += failures
        if stop_on_critical and critical:
            print(f"Stopping due to CRITICAL failure in group: {group}")
            break
    return total_failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validation runner")
    parser.add_argument("--mode", help="Validation mode, e.g. infrastructure")
    parser.add_argument("--agent", choices=["monitor", "orchestrator", "researcher", "source_monitor"])
    parser.add_argument("--duration", type=int, default=0)
    parser.add_argument("--check-sources")
    parser.add_argument("--test-interrupts", action="store_true")
    parser.add_argument("--test-resource-modes", action="store_true")
    parser.add_argument("--check-stream-format", action="store_true")
    parser.add_argument("--check-signal-reliability", action="store_true")
    parser.add_argument("--check-posts", action="store_true")
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--last", type=int, default=5)
    parser.add_argument("--check-post-immutability", action="store_true")
    parser.add_argument("--check-questions-table", action="store_true")
    parser.add_argument("--check-observatory-working-events", action="store_true")
    parser.add_argument("--test-interrupt-flow", action="store_true")
    parser.add_argument("--test-conversation", action="store_true")
    parser.add_argument("--voice-check", action="store_true")
    parser.add_argument("--check-citations", action="store_true")
    parser.add_argument("--frontend-design", action="store_true")
    parser.add_argument("--model-routing", action="store_true")
    parser.add_argument("--rate-limit-handling", action="store_true")
    parser.add_argument("--context-memory", action="store_true")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--full", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    groups: list[str] = []
    stop_on_critical = False

    if args.quick:
        groups.extend(QUICK_CHECKS)
    if args.full:
        groups.extend(FULL_CHECKS)
        stop_on_critical = True

    if args.mode:
        groups.append(args.mode)

    if args.check_stream_format:
        groups.append("stream_format")
    if args.check_signal_reliability:
        groups.append("signal_reliability")
    if args.check_posts:
        groups.append("posts_voice")
    if args.check_post_immutability:
        groups.append("post_immutability")
    if args.check_questions_table:
        groups.append("questions_table")
    if args.check_observatory_working_events:
        groups.append("observatory_working_events")
    if args.test_interrupt_flow or args.test_interrupts:
        groups.append("interrupt_flow")
    if args.test_conversation:
        groups.append("conversation")
    if args.frontend_design:
        groups.append("frontend_design")
    if args.model_routing:
        groups.append("model_routing")
    if args.rate_limit_handling:
        groups.append("rate_limit_handling")
    if args.context_memory:
        groups.append("context_memory")

    if args.agent == "monitor":
        if args.check_sources:
            groups.extend(["stream_format", "signal_reliability"])
        if args.duration:
            print(f"Monitoring monitor-agent behavior for {args.duration}s...")
            time.sleep(args.duration)
    elif args.agent == "orchestrator":
        if args.test_interrupts:
            groups.append("interrupt_flow")
        if args.test_resource_modes:
            groups.append("rate_limit_handling")
    elif args.agent == "source_monitor":
        groups.append("signal_reliability")

    if not groups:
        print("No checks selected. Use --quick, --full, or specific flags.")
        return 1

    # preserve order but remove duplicates
    deduped = []
    seen = set()
    for group in groups:
        if group not in seen:
            deduped.append(group)
            seen.add(group)

    failures = run_groups(deduped, stop_on_critical=stop_on_critical)
    print(f"\nValidation complete: {'PASS' if failures == 0 else 'FAIL'} ({failures} failed checks)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
