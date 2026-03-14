import asyncio
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from shared.base_agent import BaseAgent
from shared.schemas import AgentMessage

logger = logging.getLogger(__name__)

UI_CURRENT_PICTURE_STYLE_PROMPT_DEFAULT = (
    "do phd level analysis n draw insights. write in fluffy paragraphs but not formal, "
    "like how u would say to a friend"
)
UI_CURRENT_PICTURE_ALLOWED_MODELS = {"fast", "standard", "deep"}


class ResearcherAgent(BaseAgent):
    """Minimal researcher runtime dedicated to UI current-picture generation."""

    def __init__(self, redis_url: str, groq_key: str):
        resources_path = "/config/resources.yaml" if Path("/config/resources.yaml").exists() else "config/resources.yaml"
        super().__init__("researcher", redis_url, groq_key, resources_path=resources_path)

        self.ui_current_picture_enabled = self._env_bool("UI_CURRENT_PICTURE_ENABLED", True)
        self.ui_current_picture_interval_sec = self._env_int("UI_CURRENT_PICTURE_INTERVAL_SEC", 10800, minimum=300)
        self.ui_current_picture_source_url = (
            os.environ.get("UI_CURRENT_PICTURE_SOURCE_URL", "https://www.iranmonitor.org/api/export-prompt").strip()
            or "https://www.iranmonitor.org/api/export-prompt"
        )

        requested_model = os.environ.get("UI_CURRENT_PICTURE_MODEL", "fast").strip().lower() or "fast"
        self.ui_current_picture_model = requested_model if requested_model in UI_CURRENT_PICTURE_ALLOWED_MODELS else "fast"
        self.ui_current_picture_max_tokens = self._env_int("UI_CURRENT_PICTURE_MAX_TOKENS", 360, minimum=120)
        self.ui_current_picture_prompt_char_limit = self._env_int("UI_CURRENT_PICTURE_PROMPT_CHAR_LIMIT", 2800, minimum=600)
        self.ui_current_picture_style_prompt = (
            os.environ.get(
                "UI_CURRENT_PICTURE_STYLE_PROMPT",
                UI_CURRENT_PICTURE_STYLE_PROMPT_DEFAULT,
            ).strip()
            or UI_CURRENT_PICTURE_STYLE_PROMPT_DEFAULT
        )

        self.ui_current_picture_last_attempt_state_key = "ui_current_picture:last_attempt_at"
        self.ui_current_picture_last_success_state_key = "ui_current_picture:last_success_at"
        self.ui_current_picture_last_prompt_hash_state_key = "ui_current_picture:last_prompt_hash"
        self.ui_current_picture_last_error_state_key = "ui_current_picture:last_error"

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _safe_json_loads(raw: str | None, fallback):
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return fallback

    @staticmethod
    def _to_utc_iso(value: str | None) -> str | None:
        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None

        candidates = [raw]
        if raw.endswith("Z"):
            candidates.append(raw[:-1] + "+00:00")

        for candidate in candidates:
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_source_generated_at(source_prompt: str) -> str | None:
        match = re.search(r"(?im)^\s*generated\s*:\s*(.+?)\s*$", source_prompt)
        if not match:
            return None
        return ResearcherAgent._to_utc_iso(match.group(1).strip()) or match.group(1).strip()

    @staticmethod
    def _trim_incomplete_tail(text: str) -> str:
        clean = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not clean:
            return ""

        if re.search(r"[.!?\"')\]]\s*$", clean):
            return clean

        last_punct = max(clean.rfind("."), clean.rfind("!"), clean.rfind("?"))
        if last_punct >= int(len(clean) * 0.55):
            trimmed = clean[: last_punct + 1].strip()
            if trimmed:
                return trimmed
        return clean

    def _db_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _load_latest_snapshot(self, snapshot_type: str) -> dict | None:
        conn = self._db_connect()
        try:
            row = conn.execute(
                """
                SELECT id, generated_at, content, content_hash, meta_json
                FROM context_snapshots
                WHERE snapshot_type = ?
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (snapshot_type,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return None
        return {
            "id": row[0],
            "generated_at": row[1],
            "content": row[2],
            "content_hash": row[3],
            "meta": self._safe_json_loads(row[4], {}),
        }

    def _save_snapshot(self, snapshot_type: str, content: str, meta: dict) -> bool:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        latest = self._load_latest_snapshot(snapshot_type)
        if latest and str(latest.get("content_hash") or "") == content_hash:
            return False

        conn = self._db_connect()
        try:
            conn.execute(
                """
                INSERT INTO context_snapshots (
                    id, snapshot_type, generated_at, content, content_hash, source_doc_ids, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    snapshot_type,
                    datetime.now(timezone.utc).isoformat(),
                    content,
                    content_hash,
                    "[]",
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def _snapshot_age_seconds(self, snapshot_type: str) -> int | None:
        snapshot = self._load_latest_snapshot(snapshot_type)
        if not snapshot:
            return None
        generated_at = self._to_utc_iso(str(snapshot.get("generated_at") or ""))
        if not generated_at:
            return None
        try:
            dt = datetime.fromisoformat(generated_at)
        except ValueError:
            return None
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))

    async def refresh_ui_current_picture_once(self, reason: str = "manual") -> bool:
        if not self.ui_current_picture_enabled:
            return False

        attempt_at = datetime.now(timezone.utc).isoformat()
        await self.set_agent_state(self.ui_current_picture_last_attempt_state_key, attempt_at)

        try:
            async with httpx.AsyncClient(timeout=35, follow_redirects=True) as client:
                response = await client.get(
                    self.ui_current_picture_source_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                response.raise_for_status()
                payload = response.json()
            source_prompt = str(payload.get("prompt", "")).strip()
            if not source_prompt:
                raise ValueError("IranMonitor payload missing 'prompt'")
        except Exception as exc:  # noqa: BLE001
            await self.set_agent_state(self.ui_current_picture_last_error_state_key, str(exc))
            await self.observe_throttled(
                "ui_current_picture:refresh_failed",
                "decide",
                f"UI current picture refresh failed ({exc})",
                throttle_seconds=900,
            )
            return False

        prompt_hash = hashlib.sha256(source_prompt.encode("utf-8")).hexdigest()
        existing_snapshot = await asyncio.to_thread(self._load_latest_snapshot, "ui_current_picture")
        existing_age = await asyncio.to_thread(self._snapshot_age_seconds, "ui_current_picture")
        previous_prompt_hash = await self.get_agent_state(self.ui_current_picture_last_prompt_hash_state_key, default="")
        if not previous_prompt_hash and isinstance(existing_snapshot, dict):
            existing_meta = existing_snapshot.get("meta", {})
            if isinstance(existing_meta, dict):
                previous_prompt_hash = str(existing_meta.get("prompt_hash") or "")

        if (
            existing_snapshot is not None
            and previous_prompt_hash == prompt_hash
            and existing_age is not None
            and existing_age < self.ui_current_picture_interval_sec
        ):
            await self.set_agent_state(self.ui_current_picture_last_error_state_key, "")
            await self.observe_throttled(
                "ui_current_picture:unchanged",
                "decide",
                "UI current picture unchanged",
                throttle_seconds=1200,
            )
            return False

        truncated = False
        prompt_for_llm = source_prompt
        if len(prompt_for_llm) > self.ui_current_picture_prompt_char_limit:
            prompt_for_llm = prompt_for_llm[: self.ui_current_picture_prompt_char_limit].rstrip() + "\n\n[TRUNCATED]"
            truncated = True

        llm_prompt = (
            f"{prompt_for_llm}\n\n"
            f"{self.ui_current_picture_style_prompt}"
        )

        generated = await self.llm(
            llm_prompt,
            model=self.ui_current_picture_model,
            max_tokens=self.ui_current_picture_max_tokens,
            expect_json=False,
            lane="background",
            background_prompt_char_limit=max(self.ui_current_picture_prompt_char_limit + 200, 2200),
            background_max_tokens_limit=self.ui_current_picture_max_tokens,
        )
        content = self._trim_incomplete_tail(str(generated or "").strip())
        if not content:
            error_msg = "UI current picture generation returned empty output"
            await self.set_agent_state(self.ui_current_picture_last_error_state_key, error_msg)
            await self.observe_throttled(
                "ui_current_picture:refresh_failed",
                "decide",
                f"UI current picture refresh failed ({error_msg})",
                throttle_seconds=900,
            )
            return False

        source_generated_at = self._parse_source_generated_at(source_prompt)
        changed = await asyncio.to_thread(
            self._save_snapshot,
            "ui_current_picture",
            content,
            {
                "source_url": self.ui_current_picture_source_url,
                "source_generated_at": source_generated_at,
                "model": self.ui_current_picture_model,
                "prompt_hash": prompt_hash,
                "refresh_reason": reason,
                "input_truncated": truncated,
            },
        )
        await self.set_agent_state(self.ui_current_picture_last_prompt_hash_state_key, prompt_hash)
        await self.set_agent_state(self.ui_current_picture_last_success_state_key, datetime.now(timezone.utc).isoformat())
        await self.set_agent_state(self.ui_current_picture_last_error_state_key, "")

        if changed:
            await self.observe("write", "UI current picture rebuilt")
        else:
            await self.observe_throttled(
                "ui_current_picture:unchanged",
                "decide",
                "UI current picture unchanged",
                throttle_seconds=1200,
            )
        return changed

    async def ui_current_picture_loop(self) -> None:
        if not self.ui_current_picture_enabled:
            await self.observe_throttled(
                "ui_current_picture:disabled",
                "decide",
                "UI current picture loop disabled",
                throttle_seconds=3600,
            )
            while True:
                await asyncio.sleep(self.ui_current_picture_interval_sec)

        await asyncio.sleep(random.uniform(2, 8))
        while True:
            try:
                await self.refresh_ui_current_picture_once(reason="scheduled")
            except Exception as exc:  # noqa: BLE001
                logger.exception("ui current picture loop error")
                await self.set_agent_state(self.ui_current_picture_last_error_state_key, str(exc))
                await self.observe_throttled(
                    "ui_current_picture:refresh_failed",
                    "decide",
                    f"UI current picture refresh failed ({exc})",
                    throttle_seconds=900,
                )
            await asyncio.sleep(self.ui_current_picture_interval_sec)

    async def handle(self, msg: AgentMessage) -> None:
        # This service is intentionally single-purpose now.
        _ = msg

    async def start(self) -> None:
        await self.init_runtime()
        if self.ui_current_picture_enabled:
            try:
                await self.refresh_ui_current_picture_once(reason="startup")
            except Exception as exc:  # noqa: BLE001
                logger.exception("startup UI current picture refresh failed")
                await self.set_agent_state(self.ui_current_picture_last_error_state_key, str(exc))
                await self.observe_throttled(
                    "ui_current_picture:refresh_failed",
                    "decide",
                    f"UI current picture refresh failed ({exc})",
                    throttle_seconds=900,
                )

        await asyncio.gather(
            self.consume_loop(),
            self.heartbeat_loop(),
            self.ui_current_picture_loop(),
        )
