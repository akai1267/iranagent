import asyncio
import json
import logging
import math
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import groq
import redis.asyncio as aioredis
import yaml

from scripts.init_db import init as init_db
from shared.rate_limiter import GlobalRateLimiter, RateLimiter
from shared.schemas import AgentMessage, ObservabilityEvent

logger = logging.getLogger(__name__)

MODELS = {
    "fast": "llama-3.1-8b-instant",
    "standard": "llama-3.3-70b-versatile",
    "deep": "llama-3.3-70b-versatile",
}

DEFAULT_TEMPS = {
    "fast": 0.1,
    "standard": 0.3,
    "deep": 0.7,
}


class BaseAgent:
    def __init__(self, name: str, redis_url: str, groq_key: str, resources_path: str = "/config/resources.yaml"):
        self.name = name
        self.redis_url = redis_url
        self.redis = None
        self.global_limiter: GlobalRateLimiter | None = None
        self.groq_keys = self._load_groq_keys(groq_key)
        self.groq_clients = [groq.AsyncGroq(api_key=key) for key in self.groq_keys]
        self._groq_key_cooldowns = [0.0 for _ in self.groq_clients]
        self._groq_rr_cursor = 0

        self.observatory_seq_key = os.environ.get("OBSERVATORY_SEQ_KEY", "observatory:seq")
        self.observatory_preview_len = self._env_int("OBSERVATORY_PREVIEW_LEN", 220, minimum=80)
        self.observatory_sqlite_limit = self._env_int(
            "OBSERVATORY_SQLITE_LIMIT",
            self._env_int("OBSERVATORY_HISTORY_LIMIT", 5000, minimum=100),
            minimum=100,
        )
        self.overlimit_policy = os.environ.get("OVERLIMIT_POLICY", "degrade_background").strip().lower()
        self.llm_paused = os.environ.get("LLM_PAUSED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.token_margin = self._env_float("TOKEN_ESTIMATE_MARGIN", 0.15, minimum=0.05, maximum=0.50)
        self.background_min_interval_floor = self._env_float("BACKGROUND_LLM_MIN_INTERVAL_SEC", 0.0, minimum=0.0, maximum=30.0)
        self.background_pace_safety_factor = self._env_float("BACKGROUND_PACE_SAFETY_FACTOR", 1.25, minimum=1.0, maximum=3.0)
        self.background_prompt_limits = {
            "fast": self._env_int("BACKGROUND_PROMPT_CHAR_LIMIT_FAST", 900, minimum=200),
            "standard": self._env_int("BACKGROUND_PROMPT_CHAR_LIMIT_STANDARD", 1600, minimum=400),
            "deep": self._env_int("BACKGROUND_PROMPT_CHAR_LIMIT_DEEP", 2200, minimum=600),
        }
        self.background_max_tokens_limits = {
            "fast": self._env_int("BACKGROUND_MAX_TOKENS_FAST", 100, minimum=32),
            "standard": self._env_int("BACKGROUND_MAX_TOKENS_STANDARD", 180, minimum=64),
            "deep": self._env_int("BACKGROUND_MAX_TOKENS_DEEP", 260, minimum=96),
        }
        self.observatory_throttle_seconds = self._env_int("OBSERVATORY_THROTTLE_SECONDS", 120, minimum=30)
        self._observability_throttle_until: dict[str, float] = {}
        self.budget_skip_key_prefix = os.environ.get("BUDGET_SKIP_KEY_PREFIX", "budget_skip")
        self.budget_skip_retention_minutes = self._env_int("BUDGET_SKIP_RETENTION_MINUTES", 180, minimum=60)
        self.db_path = self._resolve_db_path()

        # Deprecated Redis history knobs are kept for compatibility only.
        try:
            _ = int(os.environ.get("OBSERVATORY_HISTORY_LIMIT", "0"))
        except ValueError:
            pass

        if not os.path.exists(resources_path):
            resources_path = "config/resources.yaml"

        with open(resources_path, "r", encoding="utf-8") as f:
            resources = yaml.safe_load(f)

        self.groq_models = resources["groq"]["models"]
        threshold = float(resources.get("groq", {}).get("rate_limit_threshold", 1.0))
        self.global_threshold = threshold
        self.rate_limiter = RateLimiter(self.groq_models, threshold=threshold)
        self.rate_limit_backoff = int(resources["groq"].get("rate_limit_backoff", 62))

    @staticmethod
    def _resolve_db_path() -> Path:
        preferred = Path("/memory/posts.db")
        if preferred.parent.exists():
            preferred.parent.mkdir(parents=True, exist_ok=True)
            return preferred

        local = Path("memory/posts.db")
        local.parent.mkdir(parents=True, exist_ok=True)
        return local

    @staticmethod
    def _load_groq_keys(primary_key: str) -> list[str]:
        raw_pool = os.environ.get("GROQ_API_KEYS", "")
        candidates: list[str] = []
        if primary_key and str(primary_key).strip():
            candidates.append(str(primary_key).strip())
        if raw_pool.strip():
            for token in re.split(r"[\s,]+", raw_pool.strip()):
                key = token.strip()
                if key:
                    candidates.append(key)

        unique: list[str] = []
        seen: set[str] = set()
        for key in candidates:
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique

    @staticmethod
    def _env_int(name: str, default: int, minimum: int = 0) -> int:
        value = os.environ.get(name)
        if value is None:
            return max(minimum, int(default))
        try:
            return max(minimum, int(value))
        except ValueError:
            return max(minimum, int(default))

    @staticmethod
    def _env_float(name: str, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        value = os.environ.get(name)
        try:
            parsed = float(value) if value is not None else float(default)
        except ValueError:
            parsed = float(default)
        return max(minimum, min(maximum, parsed))

    async def init_runtime(self) -> None:
        if self.redis is None:
            self.redis = await aioredis.from_url(self.redis_url)
        init_db(str(self.db_path))
        if self.global_limiter is None:
            self.global_limiter = GlobalRateLimiter(self.redis, self.groq_models, threshold=self.global_threshold)

    async def start(self) -> None:
        await self.init_runtime()
        logger.info("%s started", self.name)
        await asyncio.gather(self.consume_loop(), self.heartbeat_loop())

    async def consume_loop(self) -> None:
        backoff = 2.0
        while True:
            pubsub = None
            try:
                if self.redis is None:
                    await self.init_runtime()
                pubsub = self.redis.pubsub()
                await pubsub.subscribe(f"channel:{self.name}")
                backoff = 2.0

                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        msg = AgentMessage(**json.loads(data))
                        await self.handle(msg)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("%s consume_loop message error", self.name)
                        await self.observe("decide", f"Message handling error: {exc}")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("%s consume_loop transport failure", self.name)
                await self._reset_runtime_connections()
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2.0)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe(f"channel:{self.name}")
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        await pubsub.close()
                    except Exception:  # noqa: BLE001
                        pass

    async def heartbeat_loop(self) -> None:
        backoff = 2.0
        while True:
            try:
                if self.redis is None:
                    await self.init_runtime()
                await self.redis.set(f"heartbeat:{self.name}", "ok", ex=30)
                backoff = 2.0
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("%s heartbeat transport failure", self.name)
                await self._reset_runtime_connections()
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2.0)

    async def _reset_runtime_connections(self) -> None:
        if self.redis is None:
            self.global_limiter = None
            return
        try:
            await self.redis.aclose()
        except Exception:  # noqa: BLE001
            pass
        self.redis = None
        self.global_limiter = None

    async def publish(
        self,
        to_agent: str,
        msg_type: str,
        payload: dict,
        significance: str = "low",
        trace_id=None,
    ) -> None:
        if self.redis is None:
            await self.init_runtime()
        msg = AgentMessage(
            trace_id=trace_id or uuid4(),
            from_agent=self.name,
            to_agent=to_agent,
            type=msg_type,
            payload=payload,
            significance=significance,
        )
        await self.redis.publish(f"channel:{to_agent}", msg.model_dump_json())

    async def observe(
        self,
        event_type: str,
        summary: str,
        detail: str | None = None,
        significance: str | None = None,
    ) -> None:
        if self.redis is None:
            try:
                await self.init_runtime()
            except Exception:  # noqa: BLE001
                logger.exception("%s observability init_runtime failed", self.name)

        preview = None
        has_detail = bool(detail and str(detail).strip())
        if has_detail:
            preview = self._compact_preview(str(detail))

        seq = None
        try:
            seq = int(await self.redis.incr(self.observatory_seq_key))
        except Exception:  # noqa: BLE001
            logger.exception("%s observability sequence increment failed", self.name)

        event = ObservabilityEvent(
            seq=seq,
            agent=self.name,
            event_type=event_type,
            summary=summary,
            preview=preview,
            has_detail=has_detail,
            detail=detail if has_detail else None,
            significance=significance,
        )

        try:
            await asyncio.to_thread(self._store_observability_event, event)
        except Exception:  # noqa: BLE001
            logger.exception("%s observability sqlite write failed", self.name)

        compact = event.model_dump(mode="json", exclude={"detail"})
        try:
            await self.redis.publish("channel:observatory", json.dumps(compact, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            logger.exception("%s observability publish failed", self.name)

    async def observe_throttled(
        self,
        throttle_key: str,
        event_type: str,
        summary: str,
        detail: str | None = None,
        significance: str | None = None,
        throttle_seconds: int | None = None,
    ) -> bool:
        seconds = throttle_seconds if throttle_seconds is not None else self.observatory_throttle_seconds
        now = time.monotonic()
        until = self._observability_throttle_until.get(throttle_key, 0.0)
        if now < until:
            return False
        self._observability_throttle_until[throttle_key] = now + float(max(1, seconds))
        await self.observe(event_type, summary, detail=detail, significance=significance)
        return True

    async def _record_budget_skip(self, model: str, reason: str, lane: str) -> None:
        if self.redis is None:
            return
        bucket = int(time.time() // 60)
        key = f"{self.budget_skip_key_prefix}:{model}:{reason}:{lane}:{bucket}"
        ttl = max(120, int(self.budget_skip_retention_minutes * 60))
        try:
            pipe = self.redis.pipeline(transaction=False)
            pipe.incr(key)
            pipe.expire(key, ttl)
            await pipe.execute()
        except Exception:  # noqa: BLE001
            logger.exception("%s budget skip counter increment failed (%s:%s)", self.name, model, reason)

    def _store_observability_event(self, event: ObservabilityEvent) -> None:
        if event.seq is None:
            return

        conn = sqlite3.connect(str(self.db_path), timeout=30)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """
                INSERT OR REPLACE INTO observatory_events (
                    seq,
                    timestamp,
                    agent,
                    event_type,
                    summary,
                    preview,
                    detail,
                    significance,
                    has_detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(event.seq),
                    event.timestamp.isoformat(),
                    event.agent,
                    event.event_type,
                    event.summary,
                    event.preview,
                    event.detail,
                    event.significance,
                    1 if event.has_detail else 0,
                ),
            )
            cutoff = int(event.seq) - self.observatory_sqlite_limit
            if cutoff > 0:
                conn.execute("DELETE FROM observatory_events WHERE seq <= ?", (cutoff,))
            conn.commit()
        finally:
            conn.close()

    def _load_agent_state(self, key: str) -> str | None:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        try:
            row = conn.execute("SELECT value FROM agent_state WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def _save_agent_state(self, key: str, value: str) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """
                INSERT INTO agent_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def _agent_state_key(self, key: str) -> str:
        return f"{self.name}:{key}"

    async def get_agent_state(self, key: str, default: str | None = None) -> str | None:
        try:
            value = await asyncio.to_thread(self._load_agent_state, self._agent_state_key(key))
            return default if value is None else value
        except Exception:  # noqa: BLE001
            logger.exception("%s agent_state load failed (%s)", self.name, key)
            return default

    async def set_agent_state(self, key: str, value: str) -> None:
        try:
            await asyncio.to_thread(self._save_agent_state, self._agent_state_key(key), value)
        except Exception:  # noqa: BLE001
            logger.exception("%s agent_state save failed (%s)", self.name, key)

    def _compact_preview(self, detail: str) -> str:
        clean = re.sub(r"\s+", " ", detail).strip()
        if len(clean) <= self.observatory_preview_len:
            return clean
        if self.observatory_preview_len <= 3:
            return clean[: self.observatory_preview_len]
        return clean[: self.observatory_preview_len - 3] + "..."

    def estimate_tokens(self, prompt: str, max_tokens: int) -> int:
        prompt_tokens = max(1, int(math.ceil(len(prompt.encode("utf-8")) / 3.8)))
        completion_tokens = max(1, int(max_tokens))
        total = prompt_tokens + completion_tokens
        return max(total, int(math.ceil(total * (1.0 + self.token_margin))))

    @staticmethod
    def _normalize_lane(lane: str) -> str:
        return "interactive" if lane == "interactive" else "background"

    def _effective_tpm_cap(self, model: str) -> int:
        if self.global_limiter is not None:
            return self.global_limiter.effective_tpm(model)
        cfg = self.groq_models.get(model, {})
        tpm = max(1, int(cfg.get("tpm_limit", 6000)))
        return max(1, int(tpm * self.global_threshold))

    def _background_pace_interval(self, model: str) -> float:
        if self.global_limiter is not None:
            effective_rpm = self.global_limiter.effective_rpm(model)
        else:
            cfg = self.groq_models.get(model, {})
            rpm = max(1, int(cfg.get("rpm_limit", 30)))
            effective_rpm = max(1, int(rpm * self.global_threshold))
        dynamic_interval = (60.0 / max(1.0, float(effective_rpm))) * self.background_pace_safety_factor
        return max(self.background_min_interval_floor, dynamic_interval)

    def _apply_background_clamps(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        lane: str,
        prompt_limit_override: int | None = None,
        token_limit_override: int | None = None,
    ) -> tuple[str, int]:
        if self._normalize_lane(lane) != "background":
            return prompt, int(max_tokens)

        prompt_limit = self.background_prompt_limits.get(model, len(prompt))
        if prompt_limit_override is not None and int(prompt_limit_override) > 0:
            prompt_limit = int(prompt_limit_override)

        token_limit = self.background_max_tokens_limits.get(model, int(max_tokens))
        if token_limit_override is not None and int(token_limit_override) > 0:
            token_limit = int(token_limit_override)

        clamped_prompt = prompt[:prompt_limit] if len(prompt) > prompt_limit else prompt
        clamped_tokens = min(int(max_tokens), int(token_limit))
        return clamped_prompt, max(1, clamped_tokens)

    async def _reserve_budget(self, model: str, tokens_estimate: int, lane: str) -> tuple[bool, int]:
        if not self.global_limiter:
            return True, max(1, int(tokens_estimate))

        lane = self._normalize_lane(lane)
        while True:
            if lane == "background":
                min_interval = self._background_pace_interval(model)
                try:
                    wait = await self.global_limiter.acquire_pace_slot(model, min_interval)
                except Exception:  # noqa: BLE001
                    logger.exception("%s background pacing check failed", self.name)
                    wait = 0.0
                if wait > 0:
                    await asyncio.sleep(wait)

            try:
                result = await self.global_limiter.reserve(model, tokens_estimate)
            except Exception:  # noqa: BLE001
                logger.exception("%s global limiter reservation failed", self.name)
                return lane == "interactive", max(1, int(tokens_estimate))
            if result.get("allowed"):
                return True, int(result.get("reserved_tokens", tokens_estimate))

            retry_after = max(1, int(result.get("retry_after", 1)))
            if lane == "background" and self.overlimit_policy == "degrade_background":
                await self._record_budget_skip(model, "budget_exhausted", lane)
                await self.observe_throttled(
                    f"overlimit:{self.name}:{model}:budget_exhausted",
                    "decide",
                    f"[{model}] background budget exhausted - skipping (retry ~{retry_after}s)",
                )
                return False, 0

            wait = min(max(1, self.rate_limit_backoff), retry_after + 1)
            await self.observe(
                "decide",
                f"[{model}] budget exhausted ({lane}) - waiting {wait}s",
            )
            await asyncio.sleep(wait)

    async def _reconcile_budget(self, model: str, reserved_tokens: int, actual_tokens: int) -> None:
        if not self.global_limiter:
            return
        delta = int(actual_tokens) - int(reserved_tokens)
        if delta != 0:
            try:
                await self.global_limiter.adjust_tokens(model, delta)
            except Exception:  # noqa: BLE001
                logger.exception("%s global limiter reconciliation failed", self.name)

    @staticmethod
    def _degraded_llm_response(expect_json: bool):
        if expect_json:
            return {}
        return ""

    @staticmethod
    def _strip_json_fence(text: str) -> str:
        clean = text.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)
        return clean.strip()

    @staticmethod
    def _json_output_instruction() -> str:
        return (
            "Return ONLY a valid JSON object. "
            "No markdown, no prose, no code fences, no comments."
        )

    def _next_groq_client_index(self, exclude: set[int] | None = None) -> int | None:
        if not self.groq_clients:
            return None
        blocked = exclude or set()
        now = time.monotonic()
        available = [idx for idx, until in enumerate(self._groq_key_cooldowns) if now >= until and idx not in blocked]
        if not available:
            return None

        start = self._groq_rr_cursor % len(self.groq_clients)
        for offset in range(len(self.groq_clients)):
            idx = (start + offset) % len(self.groq_clients)
            if idx in available:
                self._groq_rr_cursor = (idx + 1) % len(self.groq_clients)
                return idx

        idx = available[0]
        self._groq_rr_cursor = (idx + 1) % len(self.groq_clients)
        return idx

    def _soonest_groq_wait(self) -> float:
        if not self._groq_key_cooldowns:
            return 0.0
        now = time.monotonic()
        waits = [max(0.0, until - now) for until in self._groq_key_cooldowns]
        return min(waits) if waits else 0.0

    def _parse_rate_limit_wait_seconds(self, exc: Exception) -> int:
        text = str(exc)
        for mins, secs in re.findall(r"(\d+)m(\d+(?:\.\d+)?)s", text):
            total = float(mins) * 60.0 + float(secs)
            return max(1, int(math.ceil(total)))
        for sec_str in re.findall(r"(\d+(?:\.\d+)?)s", text):
            try:
                return max(1, int(math.ceil(float(sec_str))))
            except ValueError:
                continue
        return max(1, int(self.rate_limit_backoff))

    def _mark_groq_key_rate_limited(self, key_idx: int, exc: Exception) -> int:
        retry = self._parse_rate_limit_wait_seconds(exc)
        cooldown = time.monotonic() + float(retry)
        if 0 <= key_idx < len(self._groq_key_cooldowns):
            self._groq_key_cooldowns[key_idx] = max(self._groq_key_cooldowns[key_idx], cooldown)
        return retry

    def _enforce_json_prompt(self, prompt: str, max_len: int | None = None) -> str:
        instruction = self._json_output_instruction()
        working = prompt.rstrip()
        if instruction.lower() in working.lower():
            return working

        if max_len is not None and max_len > len(instruction) + 16 and len(working) + len(instruction) + 2 > max_len:
            keep = max_len - len(instruction) - 2
            working = working[: max(0, keep)].rstrip()
        return f"{working}\n\n{instruction}"

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    @staticmethod
    def _parse_scalar(token: str):
        raw = token.strip()
        lower = raw.lower()
        if lower in {"true", "false"}:
            return lower == "true"
        if lower == "null":
            return None
        if re.fullmatch(r"-?\d+", raw):
            try:
                return int(raw)
            except ValueError:
                return raw
        if re.fullmatch(r"-?\d+\.\d+", raw):
            try:
                return float(raw)
            except ValueError:
                return raw
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            return raw[1:-1]
        return raw

    @classmethod
    def _repair_json_from_text(cls, text: str) -> dict:
        repaired: dict = {}

        pair_matches = re.findall(
            r'"?([A-Za-z_][A-Za-z0-9_]*)"?\s*:\s*("([^"\\]|\\.)*"|\'([^\'\\]|\\.)*\'|true|false|null|-?\d+(?:\.\d+)?)',
            text,
            flags=re.IGNORECASE,
        )
        for key, raw_value, _, _ in pair_matches:
            repaired[key] = cls._parse_scalar(raw_value)

        if repaired:
            return repaired

        sig_match = re.search(r"\bsignificance\b[^a-zA-Z0-9]*(low|medium|high|critical)", text, flags=re.IGNORECASE)
        if sig_match:
            repaired["significance"] = sig_match.group(1).lower()

        worth_match = re.search(r"\bworth[_\s-]*posting\b[^a-zA-Z0-9]*(true|false|yes|no)", text, flags=re.IGNORECASE)
        if worth_match:
            repaired["worth_posting"] = worth_match.group(1).lower() in {"true", "yes"}

        update_match = re.search(r"\bupdate[_\s-]*warranted\b[^a-zA-Z0-9]*(true|false|yes|no)", text, flags=re.IGNORECASE)
        if update_match:
            repaired["update_warranted"] = update_match.group(1).lower() in {"true", "yes"}

        why_match = re.search(r"\bwhy\b\s*[:=-]\s*(.+)", text, flags=re.IGNORECASE)
        if why_match:
            repaired["why"] = why_match.group(1).strip()

        reason_match = re.search(r"\breason\b\s*[:=-]\s*(.+)", text, flags=re.IGNORECASE)
        if reason_match:
            repaired["reason"] = reason_match.group(1).strip()

        return repaired

    async def llm(
        self,
        prompt: str,
        model: str = "standard",
        max_tokens: int = 500,
        temperature: float | None = None,
        expect_json: bool = True,
        lane: str = "background",
        background_prompt_char_limit: int | None = None,
        background_max_tokens_limit: int | None = None,
    ):
        model_name = MODELS[model]
        temp = temperature if temperature is not None else DEFAULT_TEMPS[model]
        lane = self._normalize_lane(lane)

        if self.llm_paused:
            await self.observe_throttled(
                f"llm_paused:{self.name}:{model}",
                "decide",
                f"[{model}] llm paused - skipping",
                throttle_seconds=300,
            )
            return self._degraded_llm_response(expect_json)

        if not self.groq_clients:
            await self.observe("done", f"[{model}] mock response (missing GROQ_API_KEY)")
            if expect_json:
                return {"significance": "low", "why": "No model key configured"}
            return "No model key configured."

        prompt_for_call, max_tokens_for_call = self._apply_background_clamps(
            prompt,
            model,
            max_tokens,
            lane,
            prompt_limit_override=background_prompt_char_limit,
            token_limit_override=background_max_tokens_limit,
        )
        if expect_json:
            prompt_limit = self.background_prompt_limits.get(model) if lane == "background" else None
            prompt_for_call = self._enforce_json_prompt(prompt_for_call, max_len=prompt_limit)
        tokens_estimate = self.estimate_tokens(prompt_for_call, max_tokens_for_call)

        if lane == "background":
            tpm_cap = self._effective_tpm_cap(model)
            if tokens_estimate > tpm_cap:
                await self._record_budget_skip(model, "oversized_request", lane)
                await self.observe_throttled(
                    f"overlimit:{self.name}:{model}:oversized_request",
                    "decide",
                    f"[{model}] background request too large for global tpm cap ({tokens_estimate}>{tpm_cap}) - skipping",
                )
                return self._degraded_llm_response(expect_json)

        allowed, tokens_reserved = await self._reserve_budget(model, tokens_estimate, lane)
        if not allowed:
            return self._degraded_llm_response(expect_json)

        await self.observe(
            "working",
            f"[{model}] {prompt_for_call[:80].strip()}...",
            detail=f"model={model_name} lane={lane} reserved_tokens={tokens_reserved} estimated_tokens={tokens_estimate} max_tokens={max_tokens_for_call} temperature={temp}\n\n{prompt_for_call}",
        )

        response = None
        attempted: set[int] = set()
        while response is None:
            client_idx = self._next_groq_client_index(exclude=attempted)
            if client_idx is None:
                if lane != "interactive" and self.overlimit_policy == "degrade_background":
                    await self._record_budget_skip(model, "groq_keypool_exhausted", lane)
                    await self.observe_throttled(
                        f"overlimit:{self.name}:{model}:groq_keypool_exhausted",
                        "decide",
                        f"Groq keys cooling down on {model_name} — background call skipped",
                    )
                    await self._reconcile_budget(model, tokens_reserved, 0)
                    return self._degraded_llm_response(expect_json)

                wait = max(1, int(math.ceil(max(self.rate_limit_backoff, self._soonest_groq_wait()))))
                await self.observe("decide", f"Groq keys cooling down on {model_name} — waiting {wait}s")
                await asyncio.sleep(wait)
                attempted.clear()
                continue

            attempted.add(client_idx)
            client = self.groq_clients[client_idx]

            try:
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt_for_call}],
                    max_tokens=max_tokens_for_call,
                    temperature=temp,
                )
            except groq.RateLimitError as exc:
                retry = self._mark_groq_key_rate_limited(client_idx, exc)
                if len(attempted) < len(self.groq_clients):
                    await self.observe_throttled(
                        f"groq_key_rotate:{self.name}:{model}",
                        "decide",
                        f"Groq key {client_idx + 1} limited on {model_name}; rotating key",
                        throttle_seconds=60,
                    )
                    continue

                if lane != "interactive" and self.overlimit_policy == "degrade_background":
                    await self._record_budget_skip(model, "groq_rate_limit", lane)
                    await self.observe_throttled(
                        f"overlimit:{self.name}:{model}:groq_rate_limit",
                        "decide",
                        f"Groq rate limit on {model_name} — background call skipped",
                    )
                    await self._reconcile_budget(model, tokens_reserved, 0)
                    return self._degraded_llm_response(expect_json)

                wait = max(1, int(max(self.rate_limit_backoff, retry)))
                await self.observe("decide", f"Groq rate limit on {model_name} — waiting {wait}s")
                await asyncio.sleep(wait)
                attempted.clear()
            except Exception:  # noqa: BLE001
                await self._reconcile_budget(model, tokens_reserved, 0)
                raise

        text = response.choices[0].message.content or ""
        usage = response.usage
        tokens = int((usage.prompt_tokens or 0) + (usage.completion_tokens or 0))

        await self._reconcile_budget(model, tokens_reserved, tokens)
        self.rate_limiter.record_call(model, tokens)
        await self.observe("done", f"[{model}] {tokens} tokens", detail=text)

        if self.name != "orchestrator":
            await self.publish(
                "orchestrator",
                "token_usage",
                {
                    "agent": self.name,
                    "model": model,
                    "tokens": tokens,
                },
            )

        if "<think>" in text:
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        if not expect_json:
            return text

        clean = self._strip_json_fence(text)
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            extracted = self._extract_first_json_object(clean)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass

            repaired = self._repair_json_from_text(clean)
            if repaired:
                await self.observe_throttled(
                    f"json_repair:{self.name}:{model}",
                    "decide",
                    f"JSON parse repaired on {model_name}",
                    throttle_seconds=180,
                )
                return repaired

            await self.observe_throttled(
                f"json_parse_fail:{self.name}:{model}",
                "decide",
                f"JSON parse failed on {model_name}; returning empty object",
            )
            return {}

    async def handle(self, message: AgentMessage) -> None:  # pragma: no cover
        raise NotImplementedError
