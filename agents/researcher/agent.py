from __future__ import annotations

import asyncio
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

from agents.researcher.iranmonitor_fact_pack import FactPack, build_fact_pack
from shared.base_agent import BaseAgent
from shared.schemas import AgentMessage

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "current-picture-v5"
UI_CURRENT_PICTURE_STYLE_PROMPT_DEFAULT = (
    "do phd level analysis n draw insights. write in fluffy paragraphs but not formal, "
    "like how u would say to a friend"
)
UI_CURRENT_PICTURE_ALLOWED_MODELS = {"fast", "standard", "deep"}

STABLE_LEAD_PATTERNS = (
    "news volume is stable",
    "social media activity is stable",
    "top sources",
    "leading the pack",
)
GENERIC_TRANSITIONS = (
    "now, let's talk about",
    "let's take a closer look",
    "moving on to",
    "first off",
)
GENERIC_MAIN_SHIFT_MARKERS = (
    "multiple high-impact events",
    "strategic landscape",
    "regional instability",
    "escalating conflict between iran and its adversaries",
)
GENERIC_LENS_MARKERS = (
    "regional instability",
    "military capabilities",
    "multiple countries involved",
    "high risk of escalation",
)


class ResearcherAgent(BaseAgent):
    """Minimal researcher runtime dedicated to staged current-picture generation."""

    def __init__(self, redis_url: str, groq_key: str):
        resources_path = "/config/resources.yaml" if Path("/config/resources.yaml").exists() else "config/resources.yaml"
        super().__init__("researcher", redis_url, groq_key, resources_path=resources_path)

        legacy_model = os.environ.get("UI_CURRENT_PICTURE_MODEL", "").strip().lower()
        legacy_tokens = os.environ.get("UI_CURRENT_PICTURE_MAX_TOKENS", "").strip()

        self.ui_current_picture_enabled = self._env_bool("UI_CURRENT_PICTURE_ENABLED", True)
        self.ui_current_picture_interval_sec = self._env_int("UI_CURRENT_PICTURE_INTERVAL_SEC", 10800, minimum=300)
        self.ui_current_picture_source_url = (
            os.environ.get("UI_CURRENT_PICTURE_SOURCE_URL", "https://www.iranmonitor.org/api/export-prompt").strip()
            or "https://www.iranmonitor.org/api/export-prompt"
        )
        self.ui_current_picture_style_prompt = (
            os.environ.get("UI_CURRENT_PICTURE_STYLE_PROMPT", UI_CURRENT_PICTURE_STYLE_PROMPT_DEFAULT).strip()
            or UI_CURRENT_PICTURE_STYLE_PROMPT_DEFAULT
        )
        self.ui_current_picture_fact_pack_char_limit = self._env_int(
            "UI_CURRENT_PICTURE_PROMPT_CHAR_LIMIT",
            2800,
            minimum=1200,
        )
        self.ui_current_picture_frame_model = self._pick_model("UI_CURRENT_PICTURE_FRAME_MODEL", "fast")
        self.ui_current_picture_prose_model = self._pick_model(
            "UI_CURRENT_PICTURE_PROSE_MODEL",
            "standard",
            fallback=legacy_model,
        )
        self.ui_current_picture_verify_model = self._pick_model("UI_CURRENT_PICTURE_VERIFY_MODEL", "fast")
        self.ui_current_picture_frame_max_tokens = self._pick_tokens("UI_CURRENT_PICTURE_FRAME_MAX_TOKENS", 220)
        self.ui_current_picture_prose_max_tokens = self._pick_tokens(
            "UI_CURRENT_PICTURE_PROSE_MAX_TOKENS",
            550,
            fallback=legacy_tokens,
        )
        self.ui_current_picture_verify_max_tokens = self._pick_tokens("UI_CURRENT_PICTURE_VERIFY_MAX_TOKENS", 140)

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
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return raw

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

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(clean) <= limit:
            return clean
        if limit <= 3:
            return clean[:limit]
        return clean[: limit - 3].rstrip() + "..."

    def _pick_model(self, name: str, default: str, fallback: str | None = None) -> str:
        raw = os.environ.get(name, "").strip().lower()
        if raw in UI_CURRENT_PICTURE_ALLOWED_MODELS:
            return raw
        if fallback and fallback in UI_CURRENT_PICTURE_ALLOWED_MODELS:
            return fallback
        return default

    def _pick_tokens(self, name: str, default: int, fallback: str | None = None) -> int:
        value = os.environ.get(name)
        if value is not None:
            try:
                return max(64, int(value))
            except ValueError:
                pass
        if fallback:
            try:
                return max(64, int(fallback))
            except ValueError:
                pass
        return max(64, int(default))

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
        content_hash = self._content_hash(content)
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

    @staticmethod
    def _content_hash(content: str) -> str:
        import hashlib

        return hashlib.sha256(content.encode("utf-8")).hexdigest()

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

    @staticmethod
    def _parse_source_generated_at(source_prompt: str) -> str | None:
        match = re.search(r"(?im)^\s*generated\s*:\s*(.+?)\s*$", source_prompt)
        if not match:
            return None
        return ResearcherAgent._to_utc_iso(match.group(1).strip()) or match.group(1).strip()

    def _render_fact_pack_for_frame(self, fact_pack: FactPack) -> str:
        lines = [
            f"generated_at: {fact_pack.generated_at or 'unknown'}",
            f"quality_flags: {', '.join(fact_pack.quality_flags) if fact_pack.quality_flags else 'none'}",
        ]

        overview = fact_pack.overview or {}
        if overview:
            lines.append("overview:")
            for key in ("news_volume_trend", "social_media_activity", "internet_status", "high_impact_events"):
                value = overview.get(key)
                if value:
                    lines.append(f"- {key}: {value}")

        internet_summary = str((fact_pack.internet_status or {}).get("summary") or "").strip()
        if internet_summary:
            lines.append(f"internet_signal: {internet_summary}")

        lines.append("selected_events:")
        for event in fact_pack.selected_events:
            lines.append(
                f"- {event.evidence_id} [{event.bucket}] impact={event.impact} "
                f"{self._shorten(event.title, 110)} | {self._shorten(event.summary, 200)}"
            )

        rendered = "\n".join(lines).strip()
        if len(rendered) <= self.ui_current_picture_fact_pack_char_limit:
            return rendered

        compact_lines = lines[:6]
        for event in fact_pack.selected_events:
            candidate = (
                f"- {event.evidence_id} [{event.bucket}] impact={event.impact} "
                f"{self._shorten(event.title, 70)} | {self._shorten(event.summary, 120)}"
            )
            if len("\n".join(compact_lines + [candidate])) > self.ui_current_picture_fact_pack_char_limit:
                break
            compact_lines.append(candidate)
        return "\n".join(compact_lines).strip()

    def _build_frame_prompt(self, fact_pack: FactPack) -> str:
        return (
            "Build a compact analyst frame from this IranMonitor fact pack.\n"
            "Prioritize the strongest strategic shift, not dashboard stats.\n"
            "Ignore article-count trivia, malformed headline ages, and source-ranking filler.\n"
            "Return JSON with keys: main_shift, core_lenses, secondary_points, ignore_list, watchpoints.\n"
            "Each core_lenses item must include label, claim, evidence_ids.\n\n"
            f"{self._render_fact_pack_for_frame(fact_pack)}"
        )

    def _fallback_lenses_from_fact_pack(self, fact_pack: FactPack) -> list[dict[str, object]]:
        templates = {
            "regional_cost_surface": "Iran appears to be widening the battlespace so neighboring states and US-linked regional infrastructure feel exposed.",
            "endurance_and_attrition": "The conflict is turning into an endurance contest focused on interceptor burn rates, repeated waves, and cumulative system strain.",
            "commerce_and_shipping": "Commercial nodes, islands, and shipping routes are becoming leverage points rather than just collateral concerns.",
            "regime_governability": "Internal control and wartime governability remain part of the picture rather than evidence of immediate regime collapse.",
            "battlefield_attrition": "Direct battlefield losses and high-value military targets are still shaping the tempo of escalation.",
            "diplomatic_pressure": "Regional diplomacy is being used to pressure neighbors and complicate coalition behavior around the war.",
        }
        grouped: dict[str, list[str]] = {}
        for event in fact_pack.selected_events:
            grouped.setdefault(event.bucket, []).append(event.evidence_id)

        ordered_buckets = sorted(
            grouped,
            key=lambda bucket: max(
                (event.impact for event in fact_pack.selected_events if event.bucket == bucket),
                default=0,
            ),
            reverse=True,
        )
        lenses: list[dict[str, object]] = []
        for bucket in ordered_buckets[:4]:
            lenses.append(
                {
                    "label": bucket.replace("_", " "),
                    "claim": templates.get(bucket, "This bucket materially affects the current picture."),
                    "evidence_ids": grouped.get(bucket, [])[:3],
                }
            )
        return lenses

    def _fallback_main_shift_from_fact_pack(self, fact_pack: FactPack) -> str:
        buckets = {event.bucket for event in fact_pack.selected_events}
        if (
            ("regional_cost_surface" in buckets or "commerce_and_shipping" in buckets)
            and "endurance_and_attrition" in buckets
        ):
            return (
                "Iran appears to be widening the war's cost surface across Gulf infrastructure "
                "and coalition systems while leaning on endurance pressure."
            )
        if "regional_cost_surface" in buckets:
            return "Iran appears to be widening the battlespace so the region, not just Israel, feels the war directly."
        if "endurance_and_attrition" in buckets:
            return "The conflict is shifting toward endurance pressure and cumulative system strain rather than a simple strike-for-strike exchange."
        return "The war is becoming structurally more dangerous, with pressure spreading beyond the immediate strike exchange."

    def _normalize_frame(self, raw_frame: dict, fact_pack: FactPack) -> dict | None:
        if not isinstance(raw_frame, dict):
            return None

        main_shift = self._shorten(str(raw_frame.get("main_shift") or "").strip(), 180)
        raw_lenses = raw_frame.get("core_lenses")
        core_lenses: list[dict[str, object]] = []
        if isinstance(raw_lenses, list):
            for item in raw_lenses[:4]:
                if not isinstance(item, dict):
                    continue
                claim = self._shorten(str(item.get("claim") or "").strip(), 180)
                label = self._shorten(str(item.get("label") or "").strip(), 48)
                evidence_ids = item.get("evidence_ids")
                if not isinstance(evidence_ids, list):
                    evidence_ids = []
                evidence_ids = [str(value).strip() for value in evidence_ids if str(value).strip()][:3]
                if claim:
                    core_lenses.append(
                        {
                            "label": label or "lens",
                            "claim": claim,
                            "evidence_ids": evidence_ids,
                        }
                    )

        if not core_lenses:
            fallback_claim = self._shorten(str(raw_frame.get("claim") or "").strip(), 180)
            fallback_label = self._shorten(str(raw_frame.get("label") or "").strip(), 48)
            fallback_ids = raw_frame.get("evidence_ids")
            if not isinstance(fallback_ids, list):
                fallback_ids = [event.evidence_id for event in fact_pack.selected_events[:2]]
            fallback_ids = [str(value).strip() for value in fallback_ids if str(value).strip()][:3]
            if fallback_claim:
                core_lenses.append(
                    {
                        "label": fallback_label or "lens",
                        "claim": fallback_claim,
                        "evidence_ids": fallback_ids,
                    }
                )

        secondary_points = []
        raw_secondary = raw_frame.get("secondary_points")
        if isinstance(raw_secondary, list):
            secondary_points = [self._shorten(str(item).strip(), 120) for item in raw_secondary if str(item).strip()][:4]

        ignore_list = []
        raw_ignore = raw_frame.get("ignore_list")
        if isinstance(raw_ignore, list):
            ignore_list = [self._shorten(str(item).strip(), 100) for item in raw_ignore if str(item).strip()][:4]

        watchpoints = []
        raw_watchpoints = raw_frame.get("watchpoints")
        if isinstance(raw_watchpoints, list):
            watchpoints = [self._shorten(str(item).strip(), 120) for item in raw_watchpoints if str(item).strip()][:4]

        if (not main_shift or any(marker in main_shift.lower() for marker in GENERIC_MAIN_SHIFT_MARKERS)) and fact_pack.selected_events:
            main_shift = self._shorten(self._fallback_main_shift_from_fact_pack(fact_pack), 180)

        fallback_lenses = self._fallback_lenses_from_fact_pack(fact_pack)
        if core_lenses and len(core_lenses) == 1:
            label = str(core_lenses[0].get("label") or "").strip().lower()
            claim = str(core_lenses[0].get("claim") or "").strip().lower()
            if any(marker in label or marker in claim for marker in GENERIC_LENS_MARKERS):
                core_lenses = []

        if not core_lenses:
            core_lenses = fallback_lenses
        else:
            existing_labels = {str(item.get("label") or "").strip().lower() for item in core_lenses}
            for lens in fallback_lenses:
                label = str(lens.get("label") or "").strip().lower()
                if label in existing_labels:
                    continue
                core_lenses.append(lens)
                existing_labels.add(label)
                if len(core_lenses) >= 4:
                    break

        if not main_shift or not core_lenses:
            return None

        return {
            "main_shift": main_shift,
            "core_lenses": core_lenses,
            "secondary_points": secondary_points,
            "ignore_list": ignore_list,
            "watchpoints": watchpoints,
        }

    def _compact_frame_block(self, frame: dict) -> str:
        lines = [f"main_shift: {self._shorten(str(frame.get('main_shift') or ''), 180)}", "core_lenses:"]
        for lens in list(frame.get("core_lenses") or [])[:4]:
            if not isinstance(lens, dict):
                continue
            label = self._shorten(str(lens.get("label") or "lens"), 32)
            claim = self._shorten(str(lens.get("claim") or ""), 100)
            evidence_ids = ",".join(str(item) for item in lens.get("evidence_ids") or [])
            lines.append(f"- {label}: {claim} [{evidence_ids}]")
        if frame.get("watchpoints"):
            lines.append("watchpoints:")
            for point in list(frame.get("watchpoints") or [])[:3]:
                lines.append(f"- {self._shorten(str(point), 80)}")
        return "\n".join(lines)

    def _compact_evidence_block(self, fact_pack: FactPack) -> str:
        bucket_priority = {
            "regional_cost_surface": 0,
            "commerce_and_shipping": 1,
            "endurance_and_attrition": 2,
            "regime_governability": 3,
            "diplomatic_pressure": 4,
            "battlefield_attrition": 5,
        }
        ordered_events = sorted(
            fact_pack.selected_events,
            key=lambda event: (bucket_priority.get(event.bucket, 99), -int(event.impact)),
        )
        lines = []
        for event in ordered_events[:4]:
            lines.append(
                f"{event.evidence_id} [{event.bucket}] "
                f"{self._shorten(event.title, 54)} | {self._shorten(event.summary, 62)}"
            )
        return "\n".join(lines)

    def _build_prose_prompt(self, frame: dict, fact_pack: FactPack, issues: list[str] | None = None) -> str:
        task_parts = [
            "Write the final current picture note from the frame and evidence below.",
            "Open with the main strategic shift in sentence one.",
            "Write only 5-8 dense paragraphs.",
            "Do not use bullets, numbered lists, section headings, or labels like Main Shift or Core Lenses.",
            "Do not say you are summarizing a collection of articles or a dashboard.",
            self.ui_current_picture_style_prompt,
        ]
        if issues:
            task_parts.append(
                "Fix these issues: " + "; ".join(self._shorten(item, 90) for item in issues[:6])
            )
        prompt_parts = [
            "TASK",
            "\n".join(task_parts),
            "FRAME",
            self._compact_frame_block(frame),
            "EVIDENCE",
            self._compact_evidence_block(fact_pack),
        ]
        return "\n\n".join(part for part in prompt_parts if part).strip()

    def _heuristic_verifier_issues(self, content: str) -> list[str]:
        issues: list[str] = []
        clean = re.sub(r"\s+", " ", content.strip())
        lead = clean[:260].lower()
        for pattern in STABLE_LEAD_PATTERNS:
            if pattern in lead:
                issues.append(f"lead opens with weak dashboard framing: {pattern}")
        lower = clean.lower()
        for phrase in GENERIC_TRANSITIONS:
            if phrase in lower:
                issues.append(f"generic transition present: {phrase}")
        if "here's a summary" in lower or "summary of the information" in lower:
            issues.append("output reads like a pack summary instead of a thesis note")
        if "collection of news articles" in lower or "reports related to" in lower:
            issues.append("output frames the source pack instead of the strategic picture")
        if "bbc فارسی" in lower or "bbc persian" in lower or "leading the pack" in lower:
            issues.append("source-count or outlet-ranking filler leaked into final note")
        if "20526d ago" in lower:
            issues.append("corrupt headline-age material leaked into final note")
        if "**main shift:**" in lower or "**core lenses:**" in lower:
            issues.append("section-heading formatting leaked into final note")
        if re.search(r"(?m)^\s*\d+\.\s", content):
            issues.append("numbered list leaked into final note")
        if re.search(r"(?m)^\s*[-*]\s", content):
            issues.append("bullet formatting leaked into final note")
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", content.strip()) if item.strip()]
        if len(paragraphs) < 4:
            issues.append("output is not written as a full multi-paragraph note")
        if not re.search(r"[.!?\"')\]]\s*$", content.strip()):
            issues.append("output ends on an incomplete sentence")
        return issues

    def _build_verifier_prompt(self, frame: dict, fact_pack: FactPack, content: str, heuristic_issues: list[str]) -> str:
        hints = "; ".join(heuristic_issues) if heuristic_issues else "none"
        return (
            "Verify this current picture note.\n"
            "Return JSON with keys: passes, issues, needs_rewrite.\n"
            "Reject if the note is recap-style, source-count-driven, weakly analytical, or cut off.\n"
            "Reject if paragraph 1 does not state the main shift.\n"
            "Reject if major paragraphs do not map back to frame claims.\n\n"
            f"FRAME\n{self._compact_frame_block(frame)}\n\n"
            f"QUALITY_FLAGS\n{', '.join(fact_pack.quality_flags) if fact_pack.quality_flags else 'none'}\n\n"
            f"HEURISTIC_ISSUES\n{hints}\n\n"
            f"NOTE\n{content}"
        )

    async def _generate_frame(self, fact_pack: FactPack) -> dict | None:
        raw_frame = await self.llm(
            self._build_frame_prompt(fact_pack),
            model=self.ui_current_picture_frame_model,
            max_tokens=self.ui_current_picture_frame_max_tokens,
            temperature=0.15,
            expect_json=True,
            lane="background",
            background_prompt_char_limit=max(self.ui_current_picture_fact_pack_char_limit + 300, 2200),
            background_max_tokens_limit=self.ui_current_picture_frame_max_tokens,
        )
        return self._normalize_frame(raw_frame, fact_pack)

    async def _write_prose(self, frame: dict, fact_pack: FactPack, issues: list[str] | None = None) -> str:
        prompt = self._build_prose_prompt(frame, fact_pack, issues=issues)
        max_tokens = int(self.ui_current_picture_prose_max_tokens)
        tpm_cap = self._effective_tpm_cap(self.ui_current_picture_prose_model)
        while max_tokens > 220 and self.estimate_tokens(prompt, max_tokens) > int(tpm_cap * 0.94):
            max_tokens -= 32
        generated = await self.llm(
            prompt,
            model=self.ui_current_picture_prose_model,
            max_tokens=max_tokens,
            temperature=0.65,
            expect_json=False,
            lane="background",
            background_prompt_char_limit=max(2600, self.ui_current_picture_fact_pack_char_limit + 400),
            background_max_tokens_limit=max_tokens,
        )
        return self._trim_incomplete_tail(str(generated or "").strip())

    async def _verify_prose(self, frame: dict, fact_pack: FactPack, content: str) -> tuple[bool, list[str]]:
        heuristic_issues = self._heuristic_verifier_issues(content)
        verifier = await self.llm(
            self._build_verifier_prompt(frame, fact_pack, content, heuristic_issues),
            model=self.ui_current_picture_verify_model,
            max_tokens=self.ui_current_picture_verify_max_tokens,
            temperature=0.1,
            expect_json=True,
            lane="background",
            background_prompt_char_limit=2600,
            background_max_tokens_limit=self.ui_current_picture_verify_max_tokens,
        )
        issues = list(heuristic_issues)
        if isinstance(verifier, dict):
            raw_issues = verifier.get("issues")
            if isinstance(raw_issues, list):
                issues.extend(str(item).strip() for item in raw_issues if str(item).strip())
            passes = bool(verifier.get("passes")) and not issues
            needs_rewrite = bool(verifier.get("needs_rewrite")) or bool(issues)
            return passes and not needs_rewrite, issues
        return False, issues or ["verifier returned invalid payload"]

    async def _generate_verified_note(self, fact_pack: FactPack) -> tuple[str | None, list[str]]:
        frame = await self._generate_frame(fact_pack)
        if frame is None:
            return None, ["frame_generation_failed"]

        content = await self._write_prose(frame, fact_pack)
        if not content:
            return None, ["prose_generation_empty"]

        passes, issues = await self._verify_prose(frame, fact_pack, content)
        if passes:
            return content, []

        rewrite = await self._write_prose(frame, fact_pack, issues=issues)
        if not rewrite:
            return None, issues or ["rewrite_generation_empty"]

        passes, rewrite_issues = await self._verify_prose(frame, fact_pack, rewrite)
        if passes:
            return rewrite, ["rewritten_after_verify"]
        return None, rewrite_issues or issues or ["verification_failed"]

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

        fact_pack = build_fact_pack(source_prompt)
        existing_snapshot = await asyncio.to_thread(self._load_latest_snapshot, "ui_current_picture")
        existing_age = await asyncio.to_thread(self._snapshot_age_seconds, "ui_current_picture")
        previous_fact_pack_hash = await self.get_agent_state(self.ui_current_picture_last_prompt_hash_state_key, default="")
        existing_pipeline_version = ""
        if not previous_fact_pack_hash and isinstance(existing_snapshot, dict):
            existing_meta = existing_snapshot.get("meta", {})
            if isinstance(existing_meta, dict):
                previous_fact_pack_hash = str(
                    existing_meta.get("fact_pack_hash") or existing_meta.get("prompt_hash") or ""
                )
                existing_pipeline_version = str(existing_meta.get("pipeline_version") or "")
        elif isinstance(existing_snapshot, dict):
            existing_meta = existing_snapshot.get("meta", {})
            if isinstance(existing_meta, dict):
                existing_pipeline_version = str(existing_meta.get("pipeline_version") or "")

        if (
            existing_snapshot is not None
            and previous_fact_pack_hash == fact_pack.fact_pack_hash
            and existing_pipeline_version == PIPELINE_VERSION
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

        note, generation_flags = await self._generate_verified_note(fact_pack)
        if not note:
            error_msg = "UI current picture verification failed"
            await self.set_agent_state(self.ui_current_picture_last_error_state_key, error_msg)
            await self.observe_throttled(
                "ui_current_picture:refresh_failed",
                "decide",
                f"UI current picture refresh failed ({error_msg})",
                throttle_seconds=900,
            )
            return False

        source_generated_at = self._parse_source_generated_at(source_prompt)
        quality_flags = sorted(set(list(fact_pack.quality_flags) + generation_flags))
        meta = {
            "source_url": self.ui_current_picture_source_url,
            "source_generated_at": source_generated_at,
            "model": self.ui_current_picture_prose_model,
            "model_chain": [
                self.ui_current_picture_frame_model,
                self.ui_current_picture_prose_model,
                self.ui_current_picture_verify_model,
            ],
            "pipeline_version": PIPELINE_VERSION,
            "fact_pack_hash": fact_pack.fact_pack_hash,
            "quality_flags": quality_flags,
            "refresh_reason": reason,
        }
        changed = await asyncio.to_thread(
            self._save_snapshot,
            "ui_current_picture",
            note,
            meta,
        )
        await self.set_agent_state(self.ui_current_picture_last_prompt_hash_state_key, fact_pack.fact_pack_hash)
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

        initial_sleep = self.ui_current_picture_interval_sec + int(random.uniform(2, 8))
        await asyncio.sleep(initial_sleep)
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
