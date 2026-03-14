import asyncio
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from agents.researcher.briefing_pack import (
    BriefingPackManager,
    cycle_id_now,
    pack_age_seconds,
    pack_to_markdown,
    stable_hash,
    utc_now_iso,
)
from agents.researcher.contract import (
    contract_hash,
    load_contract,
    load_templates,
    render_template,
)
from agents.researcher.context_memory import ContextMemoryStore, render_analysis_context
from agents.researcher.context_sources import (
    CriticalThreatsIranUpdateAdapter,
    IranMonitorBriefingAdapter,
    IranMonitorStructuralAdapter,
    StreamDeltaExtractor,
)
from shared.base_agent import BaseAgent
from shared.schemas import AgentMessage, Post

logger = logging.getLogger(__name__)

EDITORIAL_BRIEF_FALLBACK = """Write like a political-military analyst for readers who already follow the conflict closely.
Lead with the best read, use dense natural paragraphs, and prefer concrete operational meaning over recap."""

CURRENT_PICTURE_BRIEF_FALLBACK = """Write a compact analyst brief that explains the operating baseline, what changed, what did not, and what to watch next.
Keep it specific, paragraph-based, and anchored in authoritative reporting."""

CALL_MODELS = {
    "post_judgment": "fast",
    "stream_assessment": "fast",
    "question_priority": "fast",
    "tether_check": "fast",
    "theories_update_check": "fast",
    "write_post": "deep",
    "update_theories": "deep",
    "answer_question": "deep",
    "seed_theories": "standard",
}

_SOURCE_BOILERPLATE_PATTERNS = (
    "data cutoff",
    "publishing two updates daily",
    "morning update will focus",
    "evening update will be more comprehensive",
    "{{region_detail.text}}",
    "{{person_detail.text}}",
    "{{organization_detail.text}}",
    "{{series.description",
)

_FACT_ACTION_KEYWORDS = (
    "strike",
    "struck",
    "launched",
    "issued",
    "announced",
    "warned",
    "deployed",
    "mobilized",
    "targeted",
    "killed",
    "injured",
    "detained",
    "arrested",
    "sanction",
    "negotiat",
    "ceasefire",
    "attack",
    "missile",
    "drone",
)

_FACT_ENTITY_KEYWORDS = (
    "khamenei",
    "irgc",
    "quds",
    "israel",
    "u.s.",
    "united states",
    "iaea",
    "hezbollah",
    "hamas",
    "houthi",
    "tehran",
    "assembly of experts",
    "axis of resistance",
)

_FACT_CONTEXT_KEYWORDS = (
    "province",
    "governorate",
    "city",
    "base",
    "facility",
    "nuclear",
    "air defense",
    "diplomatic",
    "foreign ministry",
    "security",
    "airstrike",
)


class ResearcherAgent(BaseAgent):
    def __init__(self, redis_url: str, groq_key: str, tavily_key: str):
        resources_path = "/config/resources.yaml" if Path("/config/resources.yaml").exists() else "config/resources.yaml"
        super().__init__("researcher", redis_url, groq_key, resources_path=resources_path)

        domain_path = Path("/config/domain.yaml") if Path("/config/domain.yaml").exists() else Path("config/domain.yaml")
        resources = Path(resources_path)

        self.domain = yaml.safe_load(domain_path.read_text(encoding="utf-8"))
        self.res_config = yaml.safe_load(resources.read_text(encoding="utf-8"))
        self.tavily_key = tavily_key

        default_mode = os.environ.get("DEFAULT_MODE", "full").strip().lower()
        self.mode = default_mode if default_mode in {"full", "light", "minimal"} else "full"
        self.state = "idle"

        self.db_path = Path("/memory/posts.db")
        if not self.db_path.parent.exists():
            self.db_path = Path("memory/posts.db")

        self.theories_path = Path("/memory/working_theories.md")
        if not self.theories_path.parent.exists():
            self.theories_path = Path("memory/working_theories.md")

        self.stream_path = Path("/memory/stream.md")
        if not self.stream_path.parent.exists():
            self.stream_path = Path("memory/stream.md")

        self.db: sqlite3.Connection | None = None
        self.stream_analysis_min_interval = self._env_int("RESEARCHER_STREAM_ANALYSIS_MIN_INTERVAL_SEC", 180, minimum=30)
        self.post_idle_backstop_hours = self._env_int("RESEARCHER_POST_IDLE_BACKSTOP_HOURS", 18, minimum=1)
        self.post_idle_force_cooldown_sec = self._env_int("RESEARCHER_POST_IDLE_FORCE_COOLDOWN_SEC", 21600, minimum=900)
        self.theory_idle_backstop_hours = self._env_int("RESEARCHER_THEORY_IDLE_BACKSTOP_HOURS", 48, minimum=6)
        self.stream_offset_state_key = "stream_line_offset"
        self.stream_fingerprint_state_key = "stream_fingerprint"
        self.stream_last_analysis_state_key = "stream_last_analysis_at"
        self.post_idle_last_forced_state_key = "post_idle_last_forced_at"
        self.theories_last_updated_state_key = "theories_last_updated_at"
        self.last_stream_fingerprint = ""
        self.last_stream_line_offset = 0
        self.last_stream_analysis_at: datetime | None = None
        self.context_sources_path = (
            Path("/config/context_sources.yaml")
            if Path("/config/context_sources.yaml").exists()
            else Path("config/context_sources.yaml")
        )
        self.context_cfg = self._load_context_config()
        default_contract_path = (
            Path("/config/researcher_contract.yaml")
            if Path("/config/researcher_contract.yaml").exists()
            else Path("config/researcher_contract.yaml")
        )
        default_templates_path = (
            Path("/config/researcher_templates.yaml")
            if Path("/config/researcher_templates.yaml").exists()
            else Path("config/researcher_templates.yaml")
        )
        default_editorial_brief_path = (
            Path("/config/editorial_brief.md") if Path("/config/editorial_brief.md").exists() else Path("config/editorial_brief.md")
        )
        default_current_picture_brief_path = (
            Path("/config/current_picture_brief.md")
            if Path("/config/current_picture_brief.md").exists()
            else Path("config/current_picture_brief.md")
        )
        self.contract_path = Path(os.environ.get("RESEARCHER_CONTRACT_PATH", str(default_contract_path)))
        self.templates_path = Path(os.environ.get("RESEARCHER_TEMPLATES_PATH", str(default_templates_path)))
        self.editorial_brief_path = Path(
            os.environ.get("RESEARCHER_EDITORIAL_BRIEF_PATH", str(default_editorial_brief_path))
        )
        self.current_picture_brief_path = Path(
            os.environ.get("RESEARCHER_CURRENT_PICTURE_BRIEF_PATH", str(default_current_picture_brief_path))
        )
        self.contract, self.contract_fallback = load_contract(self.contract_path)
        self.templates, self.templates_fallback = load_templates(self.templates_path)
        self.editorial_brief = self._load_brief_text(self.editorial_brief_path, EDITORIAL_BRIEF_FALLBACK)
        self.current_picture_brief = self._load_brief_text(
            self.current_picture_brief_path,
            CURRENT_PICTURE_BRIEF_FALLBACK,
        )
        self.contract_hash = contract_hash(self.contract)
        self.brief_pack_state_cycle_key = "brief_pack:last_cycle_id"
        self.brief_pack_state_generated_at_key = "brief_pack:last_generated_at"
        self.brief_pack_state_input_hash_key = "brief_pack:last_input_hash"
        self.brief_pack_state_contract_hash_key = "brief_pack:last_contract_hash"
        self.brief_pack_state_stale_status_at_key = "brief_pack:last_stale_status_at"
        self.briefing_pack_root = self._resolve_briefing_pack_root()
        self.briefing_pack = BriefingPackManager(self.briefing_pack_root, retention_count=self.contract.pack.retention_count)
        self._apply_contract_runtime_defaults()
        policy = self.context_cfg.get("snapshot_policy", {})
        self.context_discovery_interval = self._env_int(
            "CONTEXT_DISCOVERY_INTERVAL_SEC",
            int(self.context_cfg.get("critical_threats", {}).get("discovery_interval_sec", 1200)),
            minimum=300,
        )
        self.context_max_staleness = self._env_int(
            "CONTEXT_MAX_STALENESS_SEC",
            int(policy.get("max_staleness_sec", 21600)),
            minimum=1800,
        )
        self.context_startup_jitter_sec = self._env_int(
            "CONTEXT_STARTUP_JITTER_SEC",
            int(policy.get("startup_jitter_sec", 30)),
            minimum=0,
        )
        self.context_structural_refresh_sec = self._env_int(
            "CONTEXT_STRUCTURAL_REFRESH_SEC",
            int(self.context_cfg.get("iran_monitor_structural", {}).get("refresh_interval_sec", 86400)),
            minimum=3600,
        )
        self.context_max_stream_snapshot = self._env_int(
            "CONTEXT_MAX_STREAM_DELTAS_IN_SNAPSHOT",
            int(policy.get("max_stream_deltas_in_snapshot", 12)),
            minimum=1,
        )
        self.context_max_stream_prompt = self._env_int(
            "CONTEXT_MAX_STREAM_DELTAS_IN_PROMPT",
            int(policy.get("max_stream_deltas_in_prompt", 10)),
            minimum=1,
        )
        self.context_verifier_enabled = os.environ.get("CONTEXT_VERIFIER_ENABLED", "true").strip().lower() == "true"
        self.context_allow_tavily_fallback = (
            os.environ.get("CONTEXT_ALLOW_TAVILY_FALLBACK", "true").strip().lower() == "true"
        )
        self.context_state_last_discovery_key = "context:last_discovery_at"
        self.context_state_last_success_key = "context:last_successful_refresh_at"
        self.context_state_last_structural_hash_key = "context:last_structural_hash"
        self.context_state_last_picture_hash_key = "context:last_current_picture_hash"
        self.context_state_last_picture_at_key = "context:last_current_picture_generated_at"
        self.authoritative_anchor_max_age_hours = float(
            os.environ.get(
                "AUTHORITATIVE_ANCHOR_MAX_AGE_HOURS",
                str(self.contract.publish_policy.authoritative_anchor_max_age_hours),
            )
            or str(self.contract.publish_policy.authoritative_anchor_max_age_hours)
        )
        self.stale_status_note_cooldown_sec = self._env_int(
            "STALE_STATUS_NOTE_COOLDOWN_SEC",
            self.contract.publish_policy.stale_status_cooldown_sec,
            minimum=3600,
        )
        self.stale_status_last_published_state_key = self.brief_pack_state_stale_status_at_key
        self.theory_hygiene_reset_state_key = "theories:hygiene_reset_v1"
        self.context_store = ContextMemoryStore(str(self.db_path))
        ct_cfg = self.context_cfg.get("critical_threats", {})
        im_struct_cfg = self.context_cfg.get("iran_monitor_structural", {})
        im_brief_cfg = self.context_cfg.get("iran_monitor_briefing", {})
        self.ct_adapter = CriticalThreatsIranUpdateAdapter(
            timeout_sec=int(ct_cfg.get("timeout_sec", 20)),
            morning_pattern=str(ct_cfg.get("morning_pattern", "Iran Update Morning Special Report")),
            evening_pattern=str(ct_cfg.get("evening_pattern", "Iran Update Evening Special Report")),
        )
        self.iran_struct_adapter = IranMonitorStructuralAdapter(
            url=str(im_struct_cfg.get("url", "https://www.iranmonitor.org/whats-happening-in-iran")),
            timeout_sec=int(im_struct_cfg.get("timeout_sec", 20)),
        )
        self.iran_brief_adapter = IranMonitorBriefingAdapter(timeout_sec=int(im_brief_cfg.get("timeout_sec", 20)))
        self.stream_delta_extractor = StreamDeltaExtractor(self.stream_path)
        self.call_models = dict(CALL_MODELS)
        self.saver_profile = os.environ.get("LLM_SAVER_PROFILE", "strict").strip().lower()
        if self.saver_profile in {"strict", "ultra", "saver"}:
            self.call_models["write_post"] = "standard"
            self.call_models["update_theories"] = "standard"
            self.call_models["answer_question"] = "standard"
        self.context_ready = False

    def _model_for(self, key: str) -> str:
        return str(self.call_models.get(key, CALL_MODELS.get(key, "fast")))

    @staticmethod
    def _load_brief_text(path: Path, fallback_text: str) -> str:
        try:
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
        except Exception:
            pass
        return fallback_text.strip()

    def _temperature_for(self, key: str, default: float | None = None) -> float:
        policy = self.contract.temperature_policy
        value = getattr(policy, key, default if default is not None else 0.3)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default if default is not None else 0.3
        return max(0.0, min(1.5, float(parsed)))

    @staticmethod
    def _resolve_briefing_pack_root() -> Path:
        env_root = os.environ.get("BRIEFING_PACK_ROOT", "").strip()
        if env_root:
            return Path(env_root)
        preferred = Path("/memory/briefing_packs")
        if preferred.parent.exists():
            return preferred
        return Path("memory/briefing_packs")

    def _apply_contract_runtime_defaults(self) -> None:
        self.pack_compile_tick_sec = self._env_int(
            "BRIEF_PACK_COMPILE_TICK_SEC",
            self.contract.pack.compile_tick_sec,
            minimum=15,
        )
        self.pack_max_age_sec = self._env_int(
            "BRIEF_PACK_MAX_AGE_SEC",
            self.contract.pack.max_pack_age_sec,
            minimum=300,
        )
        self.pack_retention_count = self._env_int(
            "BRIEF_PACK_RETENTION_COUNT",
            self.contract.pack.retention_count,
            minimum=10,
        )
        self.pack_max_stream_deltas = self._env_int(
            "BRIEF_PACK_MAX_STREAM_DELTAS",
            self.contract.pack.max_stream_deltas,
            minimum=1,
        )
        self.pack_max_prior_posts = self._env_int(
            "BRIEF_PACK_MAX_PRIOR_POSTS",
            self.contract.pack.max_prior_posts,
            minimum=1,
        )
        self.authoritative_anchor_max_age_hours = float(
            os.environ.get(
                "AUTHORITATIVE_ANCHOR_MAX_AGE_HOURS",
                str(self.contract.publish_policy.authoritative_anchor_max_age_hours),
            )
            or str(self.contract.publish_policy.authoritative_anchor_max_age_hours)
        )
        self.stale_status_note_cooldown_sec = self._env_int(
            "STALE_STATUS_NOTE_COOLDOWN_SEC",
            self.contract.publish_policy.stale_status_cooldown_sec,
            minimum=3600,
        )
        default_writer_pipeline_v2 = "true" if self.contract.writing_policy.writer_pipeline_v2 else "false"
        self.writer_pipeline_v2 = (
            os.environ.get("WRITER_PIPELINE_V2", default_writer_pipeline_v2).strip().lower() == "true"
        )
        self.briefing_pack.retention_count = self.pack_retention_count

    async def _reload_contract_and_templates(self) -> None:
        previous_hash = self.contract_hash
        contract, contract_fallback = load_contract(self.contract_path)
        templates, templates_fallback = load_templates(self.templates_path)
        editorial_brief = self._load_brief_text(self.editorial_brief_path, EDITORIAL_BRIEF_FALLBACK)
        current_picture_brief = self._load_brief_text(
            self.current_picture_brief_path,
            CURRENT_PICTURE_BRIEF_FALLBACK,
        )
        new_hash = contract_hash(contract)
        self.contract = contract
        self.templates = templates
        self.contract_fallback = contract_fallback
        self.templates_fallback = templates_fallback
        self.editorial_brief = editorial_brief
        self.current_picture_brief = current_picture_brief
        self.contract_hash = new_hash
        self._apply_contract_runtime_defaults()
        if contract_fallback or templates_fallback:
            await self.observe_throttled(
                "contract:invalid",
                "decide",
                "Contract invalid; fallback defaults active",
                throttle_seconds=600,
            )
            return
        if new_hash != previous_hash:
            await self.observe("decide", f"Contract reload applied (hash={new_hash[:12]})")

    @staticmethod
    def _template_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        return json.dumps(value, ensure_ascii=False, indent=2)

    def _render_prompt(self, template_id: str, values: dict[str, Any]) -> str:
        template = self.templates.get(template_id, "")
        rendered_values = {key: self._template_value(val) for key, val in values.items()}
        return render_template(template, rendered_values)

    def _latest_briefing_pack(self) -> dict[str, Any] | None:
        return self.briefing_pack.load_latest_json()

    def _has_latest_briefing_pack(self) -> bool:
        return self._latest_briefing_pack() is not None

    @staticmethod
    def _clean_cycle_id(value: str | None) -> str:
        raw = str(value or "").strip()
        return raw if re.fullmatch(r"\d{8}T\d{6}Z", raw) else ""

    def _style_violations(
        self,
        text: str,
        require_evidence_tags: bool = False,
        allow_visible_evidence_tags: bool = True,
    ) -> list[str]:
        violations: list[str] = []
        lower = str(text or "").lower()
        for phrase in self.contract.style_policy.banned_phrases:
            token = str(phrase).strip().lower()
            if token and token in lower:
                violations.append(f"banned_phrase:{token}")
        if self.contract.style_policy.require_paragraphs_only:
            for line in str(text or "").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if re.match(r"^[-*]\s", stripped) or re.match(r"^\d+\.\s", stripped):
                    violations.append("non_paragraph_format")
                    break
        if not allow_visible_evidence_tags and re.search(r"\[[A-Z]\d+[A-Z0-9]*\]", str(text or "")):
            violations.append("visible_evidence_tags")
        if require_evidence_tags and self.contract.style_policy.require_evidence_tags:
            if not re.search(r"\[E\d+\]", str(text or "")):
                violations.append("missing_evidence_tags")
        return violations

    def _load_context_config(self) -> dict:
        if self.context_sources_path.exists():
            data = yaml.safe_load(self.context_sources_path.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}
        return {}

    async def start(self) -> None:
        self.theories_path.parent.mkdir(parents=True, exist_ok=True)
        self.theories_path.touch(exist_ok=True)
        self.stream_path.parent.mkdir(parents=True, exist_ok=True)
        self.stream_path.touch(exist_ok=True)
        self.briefing_pack_root.mkdir(parents=True, exist_ok=True)

        await self.init_runtime()
        if self.contract_fallback or self.templates_fallback:
            await self.observe_throttled(
                "contract:invalid",
                "decide",
                "Contract invalid; fallback defaults active",
                throttle_seconds=600,
            )
        await self.set_agent_state(self.brief_pack_state_contract_hash_key, self.contract_hash)
        existing_pack = self._latest_briefing_pack()
        if isinstance(existing_pack, dict):
            cycle = self._clean_cycle_id(existing_pack.get("cycle_id"))
            if cycle:
                await self.set_agent_state(self.brief_pack_state_cycle_key, cycle)
            generated_at = str(existing_pack.get("generated_at") or "").strip()
            if generated_at:
                await self.set_agent_state(self.brief_pack_state_generated_at_key, generated_at)
            if str(existing_pack.get("contract_hash") or "").strip():
                await self.set_agent_state(
                    self.brief_pack_state_contract_hash_key,
                    str(existing_pack.get("contract_hash")).strip(),
                )
        self.last_stream_fingerprint = await self.get_agent_state(self.stream_fingerprint_state_key, default="") or ""
        offset_raw = await self.get_agent_state(self.stream_offset_state_key, default="0")
        try:
            self.last_stream_line_offset = max(0, int(offset_raw or 0))
        except ValueError:
            self.last_stream_line_offset = 0
        last_analysis_raw = await self.get_agent_state(self.stream_last_analysis_state_key)
        if last_analysis_raw:
            try:
                parsed = datetime.fromisoformat(last_analysis_raw)
                self.last_stream_analysis_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                self.last_stream_analysis_at = None

        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            await self.seed_theories_if_empty()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to seed theories")
            await self.observe("decide", f"Failed to seed theories: {exc}")
        try:
            await self.refresh_context_once(force_missing=True, reason="startup")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed startup context refresh")
            await self.observe("decide", f"Startup context refresh failed: {exc}")
        try:
            await self.compile_briefing_pack_once(force=True, reason="startup")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed startup briefing-pack compile")
            await self.observe("decide", f"Startup briefing-pack compile failed: {exc}")
        try:
            await self.ensure_theory_hygiene_reset()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed theory hygiene reset")
            await self.observe("decide", f"Theory hygiene reset failed: {exc}")
        self.context_ready = self._has_required_context() and self._has_latest_briefing_pack()
        await self.report_state("idle")
        await asyncio.gather(
            self.consume_loop(),
            self.heartbeat_loop(),
            self.main_loop(),
            self.context_refresh_loop(),
            self.briefing_pack_loop(),
        )

    async def report_state(self, state: str, focus: str | None = None) -> None:
        self.state = state
        await self.publish("orchestrator", "status", {"state": state, "focus": focus})

    def _has_required_context(self) -> bool:
        structural = self.context_store.get_latest_snapshot("structural_context")
        current = self.context_store.get_latest_snapshot("current_picture")
        return structural is not None and current is not None

    def _snapshot_text(self, snapshot_type: str) -> str:
        snapshot = self.context_store.get_latest_snapshot(snapshot_type)
        return str(snapshot.get("content", "")) if snapshot else ""

    @staticmethod
    def _compact_text(text: str, limit: int) -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) <= limit:
            return clean
        return clean[: max(0, limit - 3)].rstrip() + "..."

    @staticmethod
    def _clean_post_title_candidate(text: str) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        clean = clean.strip("#*\"'` ")
        clean = re.sub(r"\[[A-Z]\d+[A-Z0-9]*\]", "", clean).strip()
        clean = re.sub(r"\s{2,}", " ", clean).strip()
        return clean[:110].strip()

    def _derive_post_title(
        self,
        title_raw: str,
        content_raw: str,
        context_text: str,
        thesis: str = "",
    ) -> str:
        def _trim_title(text: str) -> str:
            t = self._clean_post_title_candidate(text)
            if not t:
                return ""
            t = re.split(r"\s[-–—:]\s", t, maxsplit=1)[0].strip()
            t = re.split(r"[;:]", t, maxsplit=1)[0].strip()
            t = re.split(r",\s", t, maxsplit=1)[0].strip()
            words = t.split()
            max_words = max(3, int(self.contract.title_policy.max_words))
            if len(words) > max_words:
                t = " ".join(words[:max_words]).strip()
            t = t.rstrip(",;:- ")
            if t.lower().endswith(("and", "or", "but", "because", "with", "than", "while", "that")):
                t = " ".join(t.split()[:-1]).strip()
            return t[:88].strip()

        candidate = self._clean_post_title_candidate(title_raw)
        bad = {
            "",
            "untitled",
            "untitled analysis",
            "analysis",
            "update",
            "post",
        }
        if self.contract.title_policy.avoid_generic_titles and candidate.lower() in bad:
            candidate = ""
        if candidate.lower() not in bad and len(candidate) >= 8:
            trimmed = _trim_title(candidate)
            if trimmed:
                return trimmed

        if self.contract.title_policy.derive_from_thesis_if_missing:
            thesis_title = _trim_title(thesis)
            if thesis_title and thesis_title.lower() not in bad:
                return thesis_title

        content = re.sub(r"\[[A-Z]\d+[A-Z0-9]*\]", "", str(content_raw or ""))
        content = re.sub(r"\s+", " ", content).strip()
        if content:
            # Try first sentence, then first clause.
            sentence = re.split(r"(?<=[.!?])\s+", content, maxsplit=1)[0]
            sentence = sentence.strip(" -:")
            sentence = _trim_title(sentence)
            if len(sentence) >= 12:
                return sentence
            words = content.split()
            if words:
                return _trim_title(" ".join(words[:12]))

        ctx = re.sub(r"\s+", " ", str(context_text or "")).strip()
        if ctx:
            return _trim_title(f"Iran Update: {ctx[:72]}")
        return f"Iran Conflict Update {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"

    @staticmethod
    def _parse_title_body(text: str) -> tuple[str, str]:
        raw = str(text or "").strip()
        if not raw:
            return "", ""

        title = ""
        body = raw
        m = re.search(r"(?im)^\s*title\s*:\s*(.+)$", raw)
        if m:
            title = m.group(1).strip()
            body = raw[m.end() :].strip()
            body = re.sub(r"(?im)^\s*content\s*:\s*", "", body).strip()
        return title, body

    @staticmethod
    def _strip_public_evidence_tags(text: str) -> str:
        clean = re.sub(r"\s*\[[A-Z]\d+[A-Z0-9]*\]", "", str(text or ""))
        clean = re.sub(r"\n{3,}", "\n\n", clean)
        clean = re.sub(r"[ \t]{2,}", " ", clean)
        return clean.strip()

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _sanitize_evidence_ids(self, values: Any, valid_ids: set[str]) -> list[str]:
        items = self._coerce_string_list(values)
        seen: set[str] = set()
        ordered: list[str] = []
        for token in items:
            if token not in valid_ids or token in seen:
                continue
            seen.add(token)
            ordered.append(token)
        return ordered

    def _normalize_post_frame(self, frame: Any, evidence_ledger: list[dict[str, Any]]) -> dict[str, Any]:
        valid_ids = {str(item.get("id")) for item in evidence_ledger if item.get("id")}
        payload = frame if isinstance(frame, dict) else {}
        core_claims_raw = payload.get("core_claims", [])
        core_claims: list[dict[str, Any]] = []
        if isinstance(core_claims_raw, list):
            for item in core_claims_raw[:6]:
                if isinstance(item, dict):
                    claim = self._compact_text(str(item.get("claim", "")), 220)
                    evidence_ids = self._sanitize_evidence_ids(item.get("evidence_ids", []), valid_ids)
                else:
                    claim = self._compact_text(str(item), 220)
                    evidence_ids = []
                if not claim:
                    continue
                core_claims.append({"claim": claim, "evidence_ids": evidence_ids})
        supporting_ids = self._sanitize_evidence_ids(payload.get("supporting_evidence_ids", []), valid_ids)
        if not core_claims:
            thesis = self._compact_text(str(payload.get("thesis", "")).strip(), 220)
            if thesis:
                core_claims.append({"claim": thesis, "evidence_ids": supporting_ids[:2]})
        if not supporting_ids:
            for item in core_claims:
                for evidence_id in item.get("evidence_ids", []):
                    if evidence_id not in supporting_ids:
                        supporting_ids.append(evidence_id)
        return {
            "title": self._clean_post_title_candidate(str(payload.get("title", ""))),
            "thesis": self._compact_text(str(payload.get("thesis", "")).strip(), 260),
            "why_now": self._compact_text(str(payload.get("why_now", "")).strip(), 260),
            "core_claims": core_claims,
            "supporting_evidence_ids": supporting_ids,
            "revision_of_prior": self._compact_text(str(payload.get("revision_of_prior", "")).strip(), 220)
            or None,
            "watchpoint": self._compact_text(str(payload.get("watchpoint", "")).strip(), 220),
            "confidence": str(payload.get("confidence", "medium")).strip().lower() or "medium",
            "quality_risks": self._coerce_string_list(payload.get("quality_risks", []))[:6],
        }

    def _frame_claim_map(self, frame: dict[str, Any], evidence_ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
        valid_ids = {str(item.get("id")) for item in evidence_ledger if item.get("id")}
        claim_map: list[dict[str, Any]] = []
        thesis = self._compact_text(str(frame.get("thesis", "")).strip(), 220)
        supporting_ids = self._sanitize_evidence_ids(frame.get("supporting_evidence_ids", []), valid_ids)
        if thesis:
            claim_map.append({"claim": thesis, "evidence_ids": supporting_ids[:3]})
        for item in frame.get("core_claims", []):
            if not isinstance(item, dict):
                continue
            claim = self._compact_text(str(item.get("claim", "")).strip(), 220)
            evidence_ids = self._sanitize_evidence_ids(item.get("evidence_ids", []), valid_ids)
            if claim:
                claim_map.append({"claim": claim, "evidence_ids": evidence_ids or supporting_ids[:2]})
        watchpoint = self._compact_text(str(frame.get("watchpoint", "")).strip(), 220)
        if watchpoint:
            claim_map.append({"claim": watchpoint, "evidence_ids": supporting_ids[:2]})
        dedup: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in claim_map:
            claim = str(item.get("claim", "")).strip()
            if not claim or claim in seen:
                continue
            seen.add(claim)
            dedup.append(item)
        return dedup

    def _normalize_claim_map(self, claim_map: Any, evidence_ledger: list[dict[str, Any]], frame: dict[str, Any]) -> list[dict[str, Any]]:
        valid_ids = {str(item.get("id")) for item in evidence_ledger if item.get("id")}
        cleaned: list[dict[str, Any]] = []
        if isinstance(claim_map, list):
            for item in claim_map[:8]:
                if not isinstance(item, dict):
                    continue
                claim = self._compact_text(str(item.get("claim", "")).strip(), 240)
                evidence_ids = self._sanitize_evidence_ids(item.get("evidence_ids", []), valid_ids)
                if claim and evidence_ids:
                    cleaned.append({"claim": claim, "evidence_ids": evidence_ids})
        if cleaned:
            return cleaned
        return self._frame_claim_map(frame, evidence_ledger)

    def _normalize_current_picture_frame(self, frame: Any) -> dict[str, str]:
        payload = frame if isinstance(frame, dict) else {}
        keys = (
            "topline",
            "operational_picture",
            "political_diplomatic_picture",
            "what_changed",
            "what_is_continuing",
            "watchpoints_12_24h",
            "gaps",
            "source_use",
        )
        result = {key: self._compact_text(str(payload.get(key, "")).strip(), 320) for key in keys}
        return result

    @staticmethod
    def _paragraph_count(text: str) -> int:
        return len([part for part in re.split(r"\n\s*\n", str(text or "").strip()) if part.strip()])

    def _post_tags_from_context(self, context: dict | str, frame: dict[str, Any] | None = None) -> list[str]:
        tags: list[str] = ["analysis"]
        if isinstance(context, dict):
            source = str(context.get("from", "")).strip().lower()
            change_type = str(context.get("change_type", "")).strip().lower()
            if source and source not in {"", "stale_status"}:
                tags.append(source)
            if change_type and change_type not in tags:
                tags.append(change_type)
            if context.get("question"):
                tags.append("research")
        confidence = str((frame or {}).get("confidence", "")).strip().lower()
        if confidence and confidence not in tags:
            tags.append(confidence)
        seen: set[str] = set()
        ordered: list[str] = []
        for item in tags:
            token = str(item).strip().lower()
            if not token or token in seen:
                continue
            seen.add(token)
            ordered.append(token)
        return ordered[:4]

    def _fallback_post_from_frame(self, frame: dict[str, Any]) -> str:
        paragraphs: list[str] = []
        thesis = str(frame.get("thesis", "")).strip()
        why_now = str(frame.get("why_now", "")).strip()
        claims = [str(item.get("claim", "")).strip() for item in frame.get("core_claims", []) if isinstance(item, dict)]
        watchpoint = str(frame.get("watchpoint", "")).strip()
        revision = str(frame.get("revision_of_prior", "") or "").strip()
        if thesis:
            lead = thesis
            if why_now:
                lead = f"{lead} {why_now}"
            paragraphs.append(lead.strip())
        if claims:
            paragraphs.append(" ".join(claims[:2]).strip())
        if revision:
            paragraphs.append(revision)
        if watchpoint:
            paragraphs.append(watchpoint)
        cleaned = [" ".join(part.split()) for part in paragraphs if part.strip()]
        return "\n\n".join(cleaned[:4]).strip()

    @staticmethod
    def _clean_source_body(text: str) -> str:
        clean = str(text or "")
        clean = re.sub(r"\{\{[^}]+\}\}", " ", clean)
        clean = re.sub(r"\[[ivxlcdm]+\]", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
        return [part.strip() for part in parts if part and part.strip()]

    def _extract_fact_snippets(self, text: str, max_items: int, max_chars: int) -> list[str]:
        body = self._clean_source_body(text)
        lower_body = body.lower()
        marker_idx = lower_body.find("key takeaways")
        if marker_idx >= 0:
            body = body[marker_idx:]

        sentences = self._split_sentences(body)
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for idx, raw in enumerate(sentences):
            sentence = " ".join(raw.split())
            if len(sentence) < 40:
                continue
            low = sentence.lower()
            if any(pattern in low for pattern in _SOURCE_BOILERPLATE_PATTERNS):
                continue

            key = re.sub(r"[^a-z0-9]+", "", low)
            if not key or key in seen:
                continue
            seen.add(key)

            score = 0
            if re.search(r"\d", sentence):
                score += 2
            if any(token in low for token in _FACT_ACTION_KEYWORDS):
                score += 3
            if any(token in low for token in _FACT_ENTITY_KEYWORDS):
                score += 2
            if any(token in low for token in _FACT_CONTEXT_KEYWORDS):
                score += 1
            if len(sentence) <= 260:
                score += 1

            scored.append((score, idx, sentence))

        scored.sort(key=lambda item: (-item[0], item[1]))

        selected: list[tuple[int, str]] = []
        char_count = 0
        for score, idx, sentence in scored:
            if score < 2 and len(selected) >= 4:
                continue
            clipped = sentence[:320].rstrip()
            if char_count + len(clipped) > max_chars and len(selected) >= 3:
                continue
            selected.append((idx, clipped))
            char_count += len(clipped) + 1
            if len(selected) >= max_items:
                break

        if not selected:
            fallback = [s[:300].rstrip() for s in sentences[: max_items] if len(s.strip()) >= 35]
            return fallback

        selected.sort(key=lambda item: item[0])
        return [sentence for _, sentence in selected]

    @staticmethod
    def _has_current_picture_sections(text: str) -> bool:
        required = (
            "### Topline",
            "### Operational picture",
            "### Political and diplomatic picture",
            "### What changed this cycle",
            "### What matters next (12-24h)",
            "### Confidence and gaps",
        )
        body = str(text or "")
        return all(section in body for section in required)

    def _fallback_current_picture(
        self,
        primary_facts: list[str],
        secondary_facts: list[str],
        briefing_facts: list[str],
        stream_deltas: list[dict],
    ) -> str:
        frame = self._fallback_current_picture_frame(primary_facts, secondary_facts, briefing_facts, stream_deltas)
        paragraphs = [
            frame["topline"],
            f"{frame['operational_picture']} {frame['what_changed']}".strip(),
            f"{frame['political_diplomatic_picture']} {frame['what_is_continuing']}".strip(),
            f"{frame['watchpoints_12_24h']} {frame['gaps']}".strip(),
        ]
        cleaned = [" ".join(part.split()) for part in paragraphs if str(part).strip()]
        return "\n\n".join(cleaned).strip()

    def _fallback_current_picture_frame(
        self,
        primary_facts: list[str],
        secondary_facts: list[str],
        briefing_facts: list[str],
        stream_deltas: list[dict],
    ) -> dict[str, str]:
        def _join_sentences(items: list[str], count: int, fallback: str) -> str:
            picked: list[str] = []
            for raw in items[:count]:
                text = " ".join(str(raw).split()).rstrip()
                if not text:
                    continue
                if text[-1] not in ".!?":
                    text = f"{text}."
                picked.append(text)
            return " ".join(picked) if picked else fallback

        delta_lines = []
        for idx, item in enumerate(stream_deltas[-2:], start=1):
            ts = str(item.get("timestamp", ""))[:16].replace("T", " ")
            outlet = f"{item.get('platform', '')}/{item.get('outlet', '')}".strip("/")
            headline = self._compact_text(str(item.get("headline", "")), 120)
            delta_lines.append(f"{ts} UTC: {outlet} reported {headline} [S{idx}].")
        deltas_text = " ".join(delta_lines) if delta_lines else "No high-signal post-anchor stream deltas are confirmed [A1]."

        topline = _join_sentences(
            primary_facts + secondary_facts,
            2,
            "Latest anchor reporting indicates no single decisive shift, but active military pressure continues across multiple fronts [A1].",
        )
        operational = _join_sentences(
            primary_facts[1:] + secondary_facts,
            3,
            "Operational reporting remains active but fragmented across open sources [A1].",
        )
        political = _join_sentences(
            secondary_facts + briefing_facts,
            2,
            "Political signaling remains escalatory, with limited evidence of near-term de-escalation channels [A1].",
        )
        changed = _join_sentences(
            primary_facts[:1] + secondary_facts[:1],
            2,
            "This cycle mostly refines prior reporting rather than reversing the direction of events [A1].",
        )
        watch = (
            "Watch for follow-on strikes against previously hit military infrastructure, changes in Iranian or proxy targeting patterns, "
            "and any official signals that alter escalation thresholds in the next 12-24 hours [A1][A2]."
        )
        confidence = (
            "Confidence is medium where claims are anchored in the primary reports [A1][A2], and low for standalone stream deltas "
            "until corroborated by subsequent anchor reporting [S1][S2]."
        )
        return {
            "topline": topline,
            "operational_picture": operational,
            "political_diplomatic_picture": political,
            "what_changed": f"{changed} {deltas_text}".strip(),
            "what_is_continuing": "The broader direction of the conflict is still being set by the same anchored pressures rather than a wholly new strategic turn [A1][A2].",
            "watchpoints_12_24h": watch,
            "gaps": confidence,
            "source_use": "Fallback frame derived from anchored fact snippets plus limited stream deltas.",
        }

    def _snapshot_meta(self, snapshot_type: str) -> dict:
        snapshot = self.context_store.get_latest_snapshot(snapshot_type)
        if not snapshot:
            return {}
        meta = snapshot.get("meta", {})
        return meta if isinstance(meta, dict) else {}

    @staticmethod
    def _to_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def _snapshot_age_seconds(self, snapshot_type: str) -> int | None:
        snapshot = self.context_store.get_latest_snapshot(snapshot_type)
        if not snapshot:
            return None
        generated = self._to_dt(snapshot.get("generated_at"))
        if generated is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - generated).total_seconds()))

    def _provider_status_map(self) -> dict[str, str]:
        def status(age: int | None, stale_after: int) -> str:
            if age is None:
                return "error"
            if age > stale_after:
                return "stale"
            return "ok"

        anchor_age = self.context_store.document_age_seconds("critical_threats", "iran_update")
        structural_age = self.context_store.document_age_seconds("iran_monitor", "structural_overview")
        briefing_age = self.context_store.document_age_seconds("iran_monitor", "daily_briefing")
        return {
            "critical_threats": status(anchor_age, self.context_max_staleness),
            "iran_monitor_structural": status(structural_age, self.context_structural_refresh_sec),
            "iran_monitor_briefing": status(briefing_age, self.context_max_staleness),
        }

    def _authoritative_anchor_age_seconds(self, meta: dict | None = None) -> int | None:
        current_meta = dict(meta or {})
        published = current_meta.get("primary_anchor_published_at")
        if not published:
            latest = self.context_store.latest_document("critical_threats", "iran_update")
            if latest:
                published = latest.get("published_at") or latest.get("fetched_at")
        published_dt = self._to_dt(str(published) if published else None)
        if published_dt is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - published_dt).total_seconds()))

    def _build_freshness_meta(self, current_meta: dict | None = None) -> dict:
        snapshot_meta = dict(current_meta or {})
        anchor_age_seconds = self._authoritative_anchor_age_seconds(snapshot_meta)
        threshold_seconds = max(3600, int(self.authoritative_anchor_max_age_hours * 3600))
        provider_status = self._provider_status_map()
        authoritative_fresh = (
            anchor_age_seconds is not None
            and anchor_age_seconds <= threshold_seconds
            and provider_status.get("critical_threats") == "ok"
        )
        return {
            "primary_anchor_cycle": snapshot_meta.get("primary_anchor_cycle"),
            "primary_anchor_published_at": snapshot_meta.get("primary_anchor_published_at"),
            "anchor_age_seconds": anchor_age_seconds,
            "authoritative_fresh_threshold_hours": self.authoritative_anchor_max_age_hours,
            "provider_status": provider_status,
            "authoritative_fresh": authoritative_fresh,
            "stale_mode_active": not authoritative_fresh,
        }

    async def _can_publish_stale_status_note(self) -> bool:
        last_raw = await self.get_agent_state(self.stale_status_last_published_state_key)
        last_dt = self._to_dt(last_raw)
        if last_dt is None:
            return True
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return elapsed >= float(self.stale_status_note_cooldown_sec)

    async def _mark_stale_status_published(self) -> None:
        await self.set_agent_state(self.stale_status_last_published_state_key, datetime.now(timezone.utc).isoformat())

    def _post_contains_banned_phrase(self, content: str) -> bool:
        lower = str(content or "").lower()
        return any(str(phrase).strip().lower() in lower for phrase in self.contract.style_policy.banned_phrases if str(phrase).strip())

    def _prompt_eligible_prior_posts(self, posts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        if not posts:
            return []
        excluded_flags = {
            str(flag).strip().lower()
            for flag in self.contract.prior_context_policy.excluded_quality_flags
            if str(flag).strip()
        }
        max_age_days = max(1, int(self.contract.prior_context_policy.max_age_days))
        max_posts = max(1, int(self.contract.prior_context_policy.prompt_max_posts))
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        selected: list[dict[str, Any]] = []
        for post in posts:
            if not isinstance(post, dict):
                continue
            quality_flags = post.get("quality_flags", [])
            if isinstance(quality_flags, str):
                quality_flags = [quality_flags]
            quality_tokens = {str(flag).strip().lower() for flag in quality_flags if str(flag).strip()}
            if excluded_flags.intersection(quality_tokens):
                continue
            content = str(post.get("content", "") or "")
            if self.contract.prior_context_policy.exclude_banned_phrase_posts and self._post_contains_banned_phrase(content):
                continue
            timestamp = self._to_dt(str(post.get("timestamp") or ""))
            if timestamp is not None and timestamp < cutoff:
                continue
            selected.append(post)
            if len(selected) >= max_posts:
                break
        return selected

    def _is_low_confidence_stream_only(self, context: dict | str) -> bool:
        if not isinstance(context, dict):
            return False
        if str(context.get("from", "")).lower() != "stream":
            return False
        sig = str(context.get("significance", "")).lower()
        if sig in {"high", "critical"}:
            return False
        findings = context.get("findings")
        return not findings

    def _build_evidence_ledger(self, context: dict | str, context_bundle: dict, prior_posts: list[dict]) -> list[dict]:
        ledger: list[dict] = []
        next_idx = 1

        def add(kind: str, authority: str, summary: str, url: str | None = None, timestamp: str | None = None) -> None:
            nonlocal next_idx
            clean = self._compact_text(summary, 220)
            if not clean:
                return
            ledger.append(
                {
                    "id": f"E{next_idx}",
                    "kind": kind,
                    "authority": authority,
                    "summary": clean,
                    "url": url or "",
                    "timestamp": timestamp or "",
                }
            )
            next_idx += 1

        add("context_trigger", "supporting", str(context)[:240])

        current_meta = context_bundle.get("current_meta", {}) or {}
        anchor_note = (
            f"Primary anchor cycle={current_meta.get('primary_anchor_cycle')}, "
            f"published={current_meta.get('primary_anchor_published_at')}"
        )
        add("current_picture_meta", "high", anchor_note, timestamp=str(current_meta.get("primary_anchor_published_at") or ""))

        for doc in context_bundle.get("source_docs", [])[:5]:
            if not isinstance(doc, dict):
                continue
            kind = str(doc.get("doc_kind", "source_doc"))
            authority = "high" if kind == "iran_update" else "medium"
            add(
                kind,
                authority,
                f"{doc.get('provider')} | {doc.get('title')}",
                url=str(doc.get("canonical_url") or doc.get("url") or ""),
                timestamp=str(doc.get("published_at") or doc.get("fetched_at") or ""),
            )

        for item in context_bundle.get("stream_deltas", [])[:8]:
            if not isinstance(item, dict):
                continue
            add(
                "stream_delta",
                "low",
                f"{item.get('platform')}/{item.get('outlet')}: {item.get('headline')} | {item.get('why')}",
                url=str(item.get("url") or ""),
                timestamp=str(item.get("timestamp") or ""),
            )

        for post in self._prompt_eligible_prior_posts(prior_posts)[:4]:
            add(
                "prior_post",
                "supporting",
                f"{str(post.get('timestamp', ''))[:10]} | {post.get('title')}",
                timestamp=str(post.get("timestamp") or ""),
            )

        return ledger

    @staticmethod
    def _render_evidence_ledger(ledger: list[dict]) -> str:
        if not ledger:
            return "(no evidence ledger entries)"
        lines = []
        for item in ledger:
            lines.append(
                f"[{item.get('id')}] ({item.get('authority')}) {item.get('kind')} | "
                f"{item.get('summary')} | {item.get('timestamp')} | {item.get('url')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _extract_evidence_tag_ids(text: str) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for match in re.findall(r"\[(E\d+)\]", str(text or "")):
            if match not in seen:
                seen.add(match)
                ordered.append(match)
        return ordered

    async def _verify_post_grounding(
        self,
        post_title: str,
        post_content: str,
        frame: dict[str, Any],
        evidence_ledger: list[dict],
        freshness_meta: dict,
    ) -> dict:
        ledger_text = self._render_evidence_ledger(evidence_ledger[:18])
        prompt = self._render_prompt(
            "post_verifier_v2",
            {
                "title": post_title,
                "frame_json": json.dumps(frame, ensure_ascii=False, indent=2),
                "post_content": self._compact_text(post_content, 2000),
                "freshness": json.dumps(freshness_meta, ensure_ascii=False),
                "evidence_ledger": ledger_text,
            },
        )
        result = await self.llm(
            prompt,
            model="fast",
            max_tokens=320,
            temperature=self._temperature_for("post_verifier_v2", 0.10),
            lane="background",
        )
        if not isinstance(result, dict):
            return {
                "passes": False,
                "issues": ["Verifier returned invalid payload"],
                "needs_rewrite": True,
                "claim_map": [],
                "quality_flags": ["verifier_invalid"],
            }
        result.setdefault("passes", False)
        result.setdefault("issues", [])
        result.setdefault("needs_rewrite", not bool(result.get("passes")))
        result["claim_map"] = self._normalize_claim_map(result.get("claim_map", []), evidence_ledger, frame)
        quality_flags = result.get("quality_flags", [])
        if isinstance(quality_flags, str):
            quality_flags = [quality_flags]
        result["quality_flags"] = [str(flag).strip() for flag in quality_flags if str(flag).strip()]
        return result

    def _compose_stale_status_post(
        self,
        context: dict | str,
        freshness_meta: dict,
        evidence_ledger: list[dict],
    ) -> tuple[str, str, list[str]]:
        now = datetime.now(timezone.utc)
        anchor_published = str(freshness_meta.get("primary_anchor_published_at") or "unknown")
        anchor_age_hours = None
        if freshness_meta.get("anchor_age_seconds") is not None:
            anchor_age_hours = round(float(freshness_meta.get("anchor_age_seconds")) / 3600.0, 1)
        provider_status = freshness_meta.get("provider_status", {})
        details = []
        if isinstance(context, dict):
            details.append(str(context.get("context", "")))
        else:
            details.append(str(context))
        details_text = self._compact_text(" ".join(part for part in details if part), 320)
        evidence_tag = evidence_ledger[0]["id"] if evidence_ledger else "E1"
        age_text = f"{anchor_age_hours}h old" if anchor_age_hours is not None else "unknown age"
        content = (
            f"Authoritative anchor context is stale as of {now.strftime('%Y-%m-%d %H:%M UTC')} "
            f"(latest anchor: {anchor_published}, {age_text}) [{evidence_tag}]. "
            "This is a status note, not a fresh strategic assessment.\n\n"
            f"What is still grounded: last anchored picture remains the baseline until new authoritative reporting lands [{evidence_tag}]. "
            "What cannot be inferred right now: day-of tactical shifts, intent updates, or outcome claims beyond the anchor horizon.\n\n"
            f"Provider health: critical_threats={provider_status.get('critical_threats')}, "
            f"iran_monitor_structural={provider_status.get('iran_monitor_structural')}, "
            f"iran_monitor_briefing={provider_status.get('iran_monitor_briefing')}. "
            f"Trigger context: {details_text or 'periodic stale-context safeguard'}."
        )
        title = f"Stale Context Status {now.strftime('%Y-%m-%d %H:%M UTC')}"
        return title, content, ["status", "stale-context"]

    async def context_refresh_loop(self) -> None:
        if self.context_startup_jitter_sec > 0:
            await asyncio.sleep(random.uniform(0, float(self.context_startup_jitter_sec)))

        while True:
            try:
                await self.refresh_context_once(force_missing=False, reason="scheduled")
            except Exception as exc:  # noqa: BLE001
                logger.exception("context refresh loop error")
                await self.observe("decide", f"Context refresh error: {exc}")
            await asyncio.sleep(self.context_discovery_interval)

    def _recent_posts_for_pack(self, limit: int) -> list[dict[str, Any]]:
        if self.db is None:
            return []
        safe_limit = max(1, min(int(limit), 50))
        rows = self.db.execute(
            """
            SELECT id, timestamp, title, content, tags,
                   COALESCE(quality_flags, '[]') AS quality_flags,
                   COALESCE(freshness_meta, '{}') AS freshness_meta
            FROM posts
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "title": row[2],
                "content": row[3],
                "tags": row[4] or "",
                "quality_flags": json.loads(row[5] or "[]"),
                "freshness_meta": json.loads(row[6] or "{}"),
            }
            for row in rows
        ]
        return self._prompt_eligible_prior_posts(posts)

    @staticmethod
    def _doc_ref_for_pack(doc: dict[str, Any] | None) -> dict[str, Any] | None:
        if not doc:
            return None
        return {
            "id": str(doc.get("id") or ""),
            "provider": str(doc.get("provider") or ""),
            "doc_kind": str(doc.get("doc_kind") or ""),
            "title": str(doc.get("title") or ""),
            "url": str(doc.get("canonical_url") or doc.get("url") or ""),
            "published_at": str(doc.get("published_at") or doc.get("fetched_at") or ""),
            "cycle": str(doc.get("cycle") or ""),
        }

    def _build_pack_evidence_ledger(
        self,
        source_docs: list[dict[str, Any]],
        stream_deltas: list[dict[str, Any]],
        prior_posts: list[dict[str, Any]],
        current_meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ledger: list[dict[str, Any]] = []
        idx = 1

        def add(kind: str, authority: str, summary: str, source_ref: str = "", timestamp: str = "", url: str = "") -> None:
            nonlocal idx
            clean = self._compact_text(summary, 220)
            if not clean:
                return
            ledger.append(
                {
                    "id": f"E{idx}",
                    "kind": kind,
                    "authority": authority,
                    "summary": clean,
                    "source_ref": source_ref,
                    "timestamp": timestamp,
                    "url": url,
                }
            )
            idx += 1

        add(
            "current_picture_meta",
            "high",
            (
                f"Anchor cycle={current_meta.get('primary_anchor_cycle') or 'unknown'} | "
                f"published={current_meta.get('primary_anchor_published_at') or 'unknown'}"
            ),
            source_ref="context_snapshots.current_picture",
            timestamp=str(current_meta.get("primary_anchor_published_at") or ""),
        )

        for doc in source_docs[:6]:
            authority = "high" if str(doc.get("doc_kind")) == "iran_update" else "medium"
            add(
                kind=str(doc.get("doc_kind") or "context_document"),
                authority=authority,
                summary=f"{doc.get('provider')} | {doc.get('title')}",
                source_ref=str(doc.get("id") or ""),
                timestamp=str(doc.get("published_at") or doc.get("fetched_at") or ""),
                url=str(doc.get("canonical_url") or ""),
            )

        for item in stream_deltas[:10]:
            add(
                kind="stream_delta",
                authority="low",
                summary=f"{item.get('platform')}/{item.get('outlet')}: {item.get('headline')} | {item.get('why')}",
                source_ref="memory/stream.md",
                timestamp=str(item.get("timestamp") or ""),
                url=str(item.get("url") or ""),
            )

        for post in prior_posts[:6]:
            add(
                kind="prior_post",
                authority="supporting",
                summary=f"{str(post.get('timestamp', ''))[:10]} | {post.get('title')}",
                source_ref=str(post.get("id") or ""),
                timestamp=str(post.get("timestamp") or ""),
                url="",
            )

        return ledger

    async def briefing_pack_loop(self) -> None:
        await asyncio.sleep(random.uniform(1, 5))
        while True:
            try:
                await self._reload_contract_and_templates()
                await self.compile_briefing_pack_once(force=False, reason="scheduled")
            except Exception as exc:  # noqa: BLE001
                logger.exception("briefing-pack loop error")
                await self.observe("decide", f"Briefing-pack loop error: {exc}")
            await asyncio.sleep(self.pack_compile_tick_sec)

    async def compile_briefing_pack_once(self, force: bool = False, reason: str = "manual") -> bool:
        structural_snapshot = self.context_store.get_latest_snapshot("structural_context")
        current_snapshot = self.context_store.get_latest_snapshot("current_picture")
        if structural_snapshot is None or current_snapshot is None:
            await self.observe_throttled(
                "briefing_pack:missing_context",
                "decide",
                "Briefing pack compile skipped: required context snapshots missing",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            return False

        current_meta = current_snapshot.get("meta", {})
        if not isinstance(current_meta, dict):
            current_meta = {}

        source_doc_ids: list[str] = []
        for doc_id in list(current_snapshot.get("source_doc_ids", [])) + list(structural_snapshot.get("source_doc_ids", [])):
            token = str(doc_id or "").strip()
            if token and token not in source_doc_ids:
                source_doc_ids.append(token)
        source_docs = self.context_store.get_documents_by_ids(source_doc_ids)
        source_docs_by_id = {str(doc.get("id")): doc for doc in source_docs}
        primary_anchor = source_docs_by_id.get(str(current_meta.get("primary_anchor_id") or ""))
        secondary_anchor = source_docs_by_id.get(str(current_meta.get("secondary_anchor_id") or ""))
        if primary_anchor is None:
            primary_anchor, secondary_anchor, _ = self.context_store.select_current_picture_sources()

        after_ts = current_meta.get("stream_last_included_at")
        stream_deltas = self.stream_delta_extractor.extract(after_ts=after_ts, limit=self.pack_max_stream_deltas)
        prior_posts = self._recent_posts_for_pack(self.pack_max_prior_posts)
        working_theories = self._theories_text()

        freshness = self._build_freshness_meta(current_meta)
        freshness["anchor_max_age_hours"] = self.authoritative_anchor_max_age_hours
        freshness["primary_anchor"] = self._doc_ref_for_pack(primary_anchor) or {}
        freshness["secondary_anchor"] = self._doc_ref_for_pack(secondary_anchor)
        freshness.setdefault("provider_status", self._provider_status_map())

        sections = {
            "structural_context": str(structural_snapshot.get("content", "")),
            "current_picture": str(current_snapshot.get("content", "")),
            "latest_stream_deltas": stream_deltas,
            "relevant_prior_posts": prior_posts,
            "working_theories": working_theories,
        }
        evidence_ledger = self._build_pack_evidence_ledger(source_docs, stream_deltas, prior_posts, current_meta)
        weights = {
            "structural_context": self.contract.weights.structural_context,
            "current_picture": self.contract.weights.current_picture,
            "latest_stream_deltas": self.contract.weights.latest_stream_deltas,
            "relevant_prior_posts": self.contract.weights.relevant_prior_posts,
        }
        input_refs = {
            "reason": reason,
            "structural_snapshot_id": str(structural_snapshot.get("id") or ""),
            "structural_snapshot_hash": str(structural_snapshot.get("content_hash") or ""),
            "current_picture_snapshot_id": str(current_snapshot.get("id") or ""),
            "current_picture_snapshot_hash": str(current_snapshot.get("content_hash") or ""),
            "current_picture_meta": current_meta,
            "source_doc_ids": source_doc_ids,
            "source_docs": [self._doc_ref_for_pack(doc) for doc in source_docs if doc],
            "stream_after_ts": str(after_ts or ""),
            "stream_deltas_hash": stable_hash(stream_deltas),
            "prior_post_ids": [str(post.get("id") or "") for post in prior_posts],
        }
        quality_flags: list[str] = []
        if freshness.get("stale_mode_active"):
            quality_flags.append("stale_mode_active")

        input_hash_payload = {
            "contract_hash": self.contract_hash,
            "structural_snapshot_hash": input_refs["structural_snapshot_hash"],
            "current_picture_snapshot_hash": input_refs["current_picture_snapshot_hash"],
            "stream_deltas_hash": input_refs["stream_deltas_hash"],
            "prior_post_ids": input_refs["prior_post_ids"],
            "working_theories_hash": hashlib.sha256(working_theories.encode("utf-8")).hexdigest(),
            "stale_mode_active": bool(freshness.get("stale_mode_active")),
        }
        input_hash = stable_hash(input_hash_payload)
        latest_pack = self._latest_briefing_pack()
        change_flags: list[str] = []
        if force or latest_pack is None:
            change_flags.append("no_existing_pack" if latest_pack is None else "force_compile")
        if latest_pack is not None:
            prev_refs = latest_pack.get("input_refs", {}) if isinstance(latest_pack.get("input_refs"), dict) else {}
            if prev_refs.get("structural_snapshot_hash") != input_refs["structural_snapshot_hash"]:
                change_flags.append("structural_snapshot_changed")
            if prev_refs.get("current_picture_snapshot_hash") != input_refs["current_picture_snapshot_hash"]:
                change_flags.append("current_picture_snapshot_changed")
            if prev_refs.get("stream_deltas_hash") != input_refs["stream_deltas_hash"]:
                change_flags.append("stream_deltas_changed")
            age_seconds = pack_age_seconds(latest_pack)
            if age_seconds is None or age_seconds >= self.pack_max_age_sec:
                change_flags.append("max_pack_age_reached")
            if str(latest_pack.get("contract_hash") or "") != self.contract_hash:
                change_flags.append("contract_hash_changed")
        last_input_hash = await self.get_agent_state(self.brief_pack_state_input_hash_key)
        if last_input_hash and last_input_hash != input_hash:
            if "input_hash_changed" not in change_flags:
                change_flags.append("input_hash_changed")
        if not change_flags:
            await self.observe_throttled(
                "briefing_pack:unchanged",
                "decide",
                "Briefing pack unchanged",
                throttle_seconds=self.contract.observability.unchanged_throttle_sec,
            )
            return False

        cycle_id = cycle_id_now()
        pack = {
            "pack_version": 1,
            "cycle_id": cycle_id,
            "generated_at": utc_now_iso(),
            "generated_by": "researcher",
            "contract_hash": self.contract_hash,
            "freshness": freshness,
            "weights": weights,
            "sections": sections,
            "evidence_ledger": evidence_ledger,
            "input_refs": input_refs,
            "quality_flags": quality_flags,
            "change_flags": change_flags,
        }
        markdown = pack_to_markdown(pack)
        self.briefing_pack.write_pack(pack, markdown)
        await self.set_agent_state(self.brief_pack_state_cycle_key, cycle_id)
        await self.set_agent_state(self.brief_pack_state_generated_at_key, str(pack["generated_at"]))
        await self.set_agent_state(self.brief_pack_state_input_hash_key, input_hash)
        await self.set_agent_state(self.brief_pack_state_contract_hash_key, self.contract_hash)
        await self.observe(
            "write",
            (
                f"Briefing pack compiled (cycle={cycle_id}, "
                f"fresh={'true' if freshness.get('authoritative_fresh') else 'false'}, deltas={len(stream_deltas)})"
            ),
        )
        return True

    async def refresh_context_once(self, force_missing: bool = False, reason: str = "manual") -> bool:
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.set_agent_state(self.context_state_last_discovery_key, now_iso)

        fetched = await self._fetch_context_documents()

        structural_snapshot = self.context_store.get_latest_snapshot("structural_context")
        current_snapshot = self.context_store.get_latest_snapshot("current_picture")
        structural_age = self._snapshot_age_seconds("structural_context")
        current_age = self._snapshot_age_seconds("current_picture")

        needs_structural = (
            structural_snapshot is None
            or fetched["structural_new"]
            or (structural_age is None or structural_age >= self.context_structural_refresh_sec)
        )
        if force_missing and structural_snapshot is None:
            needs_structural = True

        rebuilt_structural = False
        if needs_structural:
            rebuilt_structural = await self._build_structural_snapshot()

        needs_current = (
            current_snapshot is None
            or fetched["anchors_new"]
            or (fetched["briefing_new"] and (current_age is None or current_age >= self.context_max_staleness))
            or (current_age is None or current_age >= self.context_max_staleness)
        )
        if force_missing and current_snapshot is None:
            needs_current = True

        rebuilt_picture = False
        if needs_current:
            rebuilt_picture = await self._build_current_picture_snapshot()
        else:
            await self.observe_throttled(
                "context:current:unchanged",
                "decide",
                "Current picture unchanged",
                throttle_seconds=1800,
            )

        self.context_ready = self._has_required_context() and self._has_latest_briefing_pack()
        if self.context_ready:
            current = self.context_store.get_latest_snapshot("current_picture")
            structural = self.context_store.get_latest_snapshot("structural_context")
            await self.set_agent_state(self.context_state_last_success_key, datetime.now(timezone.utc).isoformat())
            if structural:
                await self.set_agent_state(self.context_state_last_structural_hash_key, str(structural.get("content_hash", "")))
            if current:
                await self.set_agent_state(self.context_state_last_picture_hash_key, str(current.get("content_hash", "")))
                await self.set_agent_state(
                    self.context_state_last_picture_at_key,
                    str(current.get("generated_at", datetime.now(timezone.utc).isoformat())),
                )
            await self.ensure_theory_hygiene_reset()

        if rebuilt_structural or rebuilt_picture:
            try:
                await self.compile_briefing_pack_once(force=True, reason=f"context_refresh:{reason}")
            except Exception as exc:  # noqa: BLE001
                await self.observe_throttled(
                    "briefing_pack:compile_error",
                    "decide",
                    f"Briefing pack compile failed after context refresh ({exc})",
                    throttle_seconds=300,
                )
        self.context_ready = self._has_required_context() and self._has_latest_briefing_pack()

        return rebuilt_structural or rebuilt_picture

    async def _fetch_context_documents(self) -> dict[str, bool]:
        discovered = {"anchors_new": False, "briefing_new": False, "structural_new": False}

        ct_cfg = self.context_cfg.get("critical_threats", {})
        if bool(ct_cfg.get("enabled", True)):
            try:
                docs = await self.ct_adapter.fetch_latest(
                    allow_tavily_fallback=self.context_allow_tavily_fallback,
                    tavily_search=self.search_web if self.tavily_key else None,
                )
                for doc in docs:
                    inserted, _ = self.context_store.insert_document(doc)
                    if inserted:
                        discovered["anchors_new"] = True
                        await self.observe(
                            "read",
                            f"Context doc fetched: {doc.provider} {doc.doc_kind} {doc.title[:80]}",
                        )
            except Exception as exc:  # noqa: BLE001
                await self.observe_throttled(
                    "context:fetch:critical_threats",
                    "decide",
                    f"Context source fetch failed for critical_threats ({exc})",
                    throttle_seconds=600,
                )

        struct_cfg = self.context_cfg.get("iran_monitor_structural", {})
        if bool(struct_cfg.get("enabled", True)):
            try:
                docs = await self.iran_struct_adapter.fetch_latest()
                for doc in docs:
                    inserted, _ = self.context_store.insert_document(doc)
                    if inserted:
                        discovered["structural_new"] = True
                        await self.observe(
                            "read",
                            f"Context doc fetched: {doc.provider} {doc.doc_kind} {doc.title[:80]}",
                        )
            except Exception as exc:  # noqa: BLE001
                await self.observe_throttled(
                    "context:fetch:iran_monitor_structural",
                    "decide",
                    f"Context source fetch failed for iran_monitor_structural ({exc})",
                    throttle_seconds=600,
                )

        brief_cfg = self.context_cfg.get("iran_monitor_briefing", {})
        if bool(brief_cfg.get("enabled", True)):
            try:
                docs = await self.iran_brief_adapter.fetch_latest(
                    allow_tavily_fallback=self.context_allow_tavily_fallback,
                    tavily_search=self.search_web if self.tavily_key else None,
                )
                for doc in docs:
                    inserted, _ = self.context_store.insert_document(doc)
                    if inserted:
                        discovered["briefing_new"] = True
                        await self.observe(
                            "read",
                            f"Context doc fetched: {doc.provider} {doc.doc_kind} {doc.title[:80]}",
                        )
            except Exception as exc:  # noqa: BLE001
                await self.observe_throttled(
                    "context:fetch:iran_monitor_briefing",
                    "decide",
                    f"Context source fetch failed for iran_monitor_briefing ({exc})",
                    throttle_seconds=600,
                )

        return discovered

    async def _build_structural_snapshot(self) -> bool:
        structural_doc = self.context_store.latest_document(provider="iran_monitor", doc_kind="structural_overview")
        if not structural_doc:
            await self.observe("decide", "Structural context rebuild skipped; no structural source doc")
            return False

        source_excerpt = self._compact_text(str(structural_doc.get("body", "")), 1200)
        prompt = f"""You are building structural background context for Iran conflict analysis.
Tether rule: {self.domain.get('tether_rule', '')}

Use only this source material:
{source_excerpt}

Output format (exact heading order):
STRUCTURAL CONTEXT
1. Regime priorities
2. Escalation logic
3. Proxy and regional leverage
4. Domestic and economic constraints
5. External constraints and foreign actors
6. Persistent watchpoints

Rules:
- 6 sections only.
- Bullet style, not essay.
- 500-800 words total.
- No day-specific stream facts.
- No references to prior model outputs.
"""
        content = await self.llm(
            prompt,
            model="standard",
            max_tokens=260,
            expect_json=False,
            lane="background",
            background_prompt_char_limit=1700,
            background_max_tokens_limit=260,
        )
        if not str(content).strip():
            return False

        changed, _ = self.context_store.save_snapshot(
            "structural_context",
            content=str(content).strip(),
            source_doc_ids=[str(structural_doc.get("id"))],
            meta={"source_kind": "iran_monitor_structural"},
        )
        if changed:
            await self.observe("write", "Structural context rebuilt")
        return changed

    async def _build_current_picture_snapshot(self) -> bool:
        primary, secondary, briefing = self.context_store.select_current_picture_sources()
        if primary is None:
            await self.observe_throttled(
                "context:no_primary_anchor",
                "decide",
                "Context refresh skipped; no authoritative anchor",
                throttle_seconds=600,
            )
            return False

        primary_published = primary.get("published_at") or primary.get("fetched_at")
        stream_deltas = self.stream_delta_extractor.extract(
            after_ts=primary_published,
            limit=self.context_max_stream_snapshot,
        )

        previous_snapshot = self.context_store.get_latest_snapshot("current_picture")
        previous_content = previous_snapshot.get("content", "") if previous_snapshot else ""

        source_docs = [primary]
        if secondary:
            source_docs.append(secondary)
        if briefing:
            source_docs.append(briefing)

        primary_facts = self._extract_fact_snippets(str(primary.get("body", "")), max_items=10, max_chars=1600)
        secondary_facts = self._extract_fact_snippets(str((secondary or {}).get("body", "")), max_items=6, max_chars=900)
        briefing_facts = self._extract_fact_snippets(str((briefing or {}).get("body", "")), max_items=6, max_chars=900)
        previous_excerpt = self._compact_text(str(previous_content), 180)
        compact_deltas = [
            {
                "id": f"S{idx + 1}",
                "ts": item.get("timestamp"),
                "sig": item.get("significance"),
                "platform": item.get("platform"),
                "outlet": item.get("outlet"),
                "headline": self._compact_text(str(item.get("headline", "")), 96),
                "why": self._compact_text(str(item.get("why", "")), 72),
            }
            for idx, item in enumerate(stream_deltas[-5:])
        ]

        source_map_lines = [
            (
                f"[A1] Primary anchor | cycle={primary.get('cycle')} | published={primary.get('published_at') or primary.get('fetched_at')} "
                f"| title={primary.get('title')}"
            ),
        ]
        if primary_facts:
            source_map_lines.extend(f"[A1F{idx + 1}] {fact}" for idx, fact in enumerate(primary_facts))
        if secondary:
            source_map_lines.append(
                (
                    f"[A2] Secondary anchor | cycle={secondary.get('cycle')} | published={secondary.get('published_at') or secondary.get('fetched_at')} "
                    f"| title={secondary.get('title')}"
                )
            )
            if secondary_facts:
                source_map_lines.extend(f"[A2F{idx + 1}] {fact}" for idx, fact in enumerate(secondary_facts))
        if briefing:
            source_map_lines.append(
                (
                    f"[B1] Briefing supplement | published={briefing.get('published_at') or briefing.get('fetched_at')} "
                    f"| title={briefing.get('title')}"
                )
            )
            if briefing_facts:
                source_map_lines.extend(f"[B1F{idx + 1}] {fact}" for idx, fact in enumerate(briefing_facts))

        delta_lines = (
            "\n".join(
                (
                    f"[{item['id']}] {item['ts']} | {str(item['sig']).upper()} | {item['platform']}/{item['outlet']} "
                    f"| {item['headline']} | why={item['why']}"
                )
                for item in compact_deltas
            )
            if compact_deltas
            else "(none)"
        )

        generation_model = "standard"
        frame_payload = self._fallback_current_picture_frame(primary_facts, secondary_facts, briefing_facts, stream_deltas)
        if self.writer_pipeline_v2:
            frame_prompt = self._render_prompt(
                "current_picture_frame",
                {
                    "current_picture_brief": self.current_picture_brief,
                    "source_map": "\n".join(source_map_lines),
                    "delta_lines": delta_lines,
                    "previous_excerpt": previous_excerpt,
                },
            )
            frame_result = await self.llm(
                frame_prompt,
                model=generation_model,
                max_tokens=320,
                lane="interactive",
                temperature=self._temperature_for("current_picture_frame", 0.25),
                background_prompt_char_limit=2600,
                background_max_tokens_limit=320,
            )
            normalized_frame = self._normalize_current_picture_frame(frame_result)
            if any(normalized_frame.values()):
                frame_payload.update({key: value for key, value in normalized_frame.items() if value})

            prose_prompt = self._render_prompt(
                "current_picture_prose",
                {
                    "current_picture_brief": self.current_picture_brief,
                    "frame_json": json.dumps(frame_payload, ensure_ascii=False, indent=2),
                },
            )
            content = await self.llm(
                prose_prompt,
                model=generation_model,
                max_tokens=420,
                expect_json=False,
                lane="interactive",
                temperature=self._temperature_for("current_picture_prose", 0.65),
                background_prompt_char_limit=2600,
                background_max_tokens_limit=420,
            )
            if not str(content).strip():
                content = self._fallback_current_picture(primary_facts, secondary_facts, briefing_facts, stream_deltas)
                generation_model = f"{generation_model}_fallback"
            verified_content = self._strip_public_evidence_tags(str(content))
        else:
            verified_content = self._fallback_current_picture(primary_facts, secondary_facts, briefing_facts, stream_deltas)
            generation_model = "legacy_fallback"

        verifier_issues: list[str] = []
        verifier_passed = True
        if self.context_verifier_enabled:
            verifier = await self._verify_current_picture(frame_payload, verified_content, source_docs, stream_deltas)
            verifier_passed = bool(verifier.get("passes", False))
            verifier_issues = [str(item) for item in verifier.get("issues", []) if str(item).strip()]
            if not verifier_passed and bool(verifier.get("needs_rewrite", True)):
                revised_prompt = self._render_prompt(
                    "current_picture_prose",
                    {
                        "current_picture_brief": self.current_picture_brief,
                        "frame_json": json.dumps(frame_payload, ensure_ascii=False, indent=2),
                    },
                )
                revised_prompt = (
                    f"{revised_prompt}\n\nVerifier issues:\n"
                    + "\n".join(f"- {issue}" for issue in verifier_issues)
                    + f"\n\nCurrent draft:\n{verified_content}\n\nRewrite the brief only."
                )
                retry_content = await self.llm(
                    revised_prompt,
                    model="standard",
                    max_tokens=420,
                    expect_json=False,
                    lane="interactive",
                    temperature=self._temperature_for("current_picture_prose", 0.65),
                    background_prompt_char_limit=2600,
                    background_max_tokens_limit=420,
                )
                if str(retry_content).strip():
                    verified_content = self._strip_public_evidence_tags(str(retry_content))
                    second = await self._verify_current_picture(frame_payload, verified_content, source_docs, stream_deltas)
                    verifier_passed = bool(second.get("passes", False))
                    verifier_issues = [str(item) for item in second.get("issues", []) if str(item).strip()]

        if self.context_verifier_enabled and not verifier_passed:
            if previous_snapshot is not None:
                await self.observe_throttled(
                    "context:verifier:failed",
                    "decide",
                    "Current picture verifier failed; retained previous snapshot",
                    throttle_seconds=600,
                )
                return False
            if verifier_issues:
                await self.observe_throttled(
                    "context:verifier:bootstrap_fallback",
                    "decide",
                    "Current picture verifier failed; saving bootstrap snapshot with verifier issues",
                    throttle_seconds=600,
                )
            else:
                verifier_issues = ["verifier_inconclusive"]
                await self.observe_throttled(
                    "context:verifier:inconclusive",
                    "decide",
                    "Current picture verifier inconclusive; publishing snapshot with caution",
                    throttle_seconds=600,
                )

        stream_last_included_at = stream_deltas[-1]["timestamp"] if stream_deltas else None
        meta = {
            "primary_anchor_id": primary.get("id"),
            "primary_anchor_cycle": primary.get("cycle"),
            "primary_anchor_published_at": primary_published,
            "secondary_anchor_id": (secondary or {}).get("id"),
            "briefing_doc_id": (briefing or {}).get("id"),
            "stream_last_included_at": stream_last_included_at,
            "generation_model": generation_model,
            "verifier_passed": verifier_passed,
            "verifier_issues": verifier_issues,
        }
        source_ids = [str(doc.get("id")) for doc in source_docs if doc.get("id")]
        changed, _ = self.context_store.save_snapshot(
            "current_picture",
            content=verified_content,
            source_doc_ids=source_ids,
            meta=meta,
        )
        if changed:
            await self.observe(
                "write",
                f"Current picture rebuilt (anchor={primary.get('cycle')}, sources={len(source_ids)}, deltas={len(stream_deltas)})",
            )
        return changed

    async def _verify_current_picture(
        self,
        frame: dict[str, Any],
        snapshot_text: str,
        source_docs: list[dict],
        stream_deltas: list[dict],
    ) -> dict:
        snapshot_excerpt = self._compact_text(snapshot_text, 700)
        source_brief = [
            {
                "title": self._compact_text(str(doc.get("title", "")), 80),
                "cycle": doc.get("cycle"),
                "provider": doc.get("provider"),
            }
            for doc in source_docs[:3]
        ]
        prompt = self._render_prompt(
            "current_picture_verifier_v2",
            {
                "frame_json": json.dumps(frame, ensure_ascii=False, indent=2),
                "snapshot_text": snapshot_excerpt,
                "source_brief": json.dumps(source_brief, ensure_ascii=False),
                "stream_delta_count": len(stream_deltas),
            },
        )
        result = await self.llm(
            prompt,
            model="fast",
            max_tokens=180,
            temperature=self._temperature_for("current_picture_verifier_v2", 0.10),
            lane="background",
        )
        if not isinstance(result, dict):
            return {"passes": False, "issues": ["Verifier returned invalid payload"], "needs_rewrite": True}
        result.setdefault("passes", False)
        result.setdefault("issues", [])
        result.setdefault("needs_rewrite", not bool(result.get("passes")))
        return result

    def build_analysis_context(
        self,
        focus_text: str,
        prior_posts: list[dict],
        include_stream: bool = True,
    ) -> dict:
        pack = self._latest_briefing_pack()
        if isinstance(pack, dict):
            sections = pack.get("sections", {}) if isinstance(pack.get("sections"), dict) else {}
            input_refs = pack.get("input_refs", {}) if isinstance(pack.get("input_refs"), dict) else {}
            current_meta = input_refs.get("current_picture_meta", {})
            if not isinstance(current_meta, dict):
                current_meta = {}

            structural_context = str(sections.get("structural_context", ""))
            current_picture = str(sections.get("current_picture", ""))
            base_stream = sections.get("latest_stream_deltas", [])
            if not isinstance(base_stream, list):
                base_stream = []
            stream_deltas = base_stream if include_stream else []
            if include_stream:
                after_ts = current_meta.get("stream_last_included_at")
                latest_deltas = self.stream_delta_extractor.extract(after_ts=after_ts, limit=self.pack_max_stream_deltas)
                if latest_deltas:
                    dedup: dict[str, dict[str, Any]] = {}
                    for item in [*stream_deltas, *latest_deltas]:
                        key = "|".join(
                            [
                                str(item.get("timestamp") or ""),
                                str(item.get("platform") or ""),
                                str(item.get("outlet") or ""),
                                str(item.get("headline") or ""),
                                str(item.get("url") or ""),
                            ]
                        )
                        dedup[key] = item
                    stream_deltas = list(dedup.values())[-self.pack_max_stream_deltas :]

            source_docs = input_refs.get("source_docs", [])
            if not isinstance(source_docs, list):
                source_docs = []
            selected_prior = self._prompt_eligible_prior_posts(prior_posts)[: self.pack_max_prior_posts] if prior_posts else []
            if not selected_prior:
                pack_prior = sections.get("relevant_prior_posts", [])
                if isinstance(pack_prior, list):
                    selected_prior = self._prompt_eligible_prior_posts(pack_prior)[: self.pack_max_prior_posts]
            rendered = render_analysis_context(
                structural_context=structural_context,
                current_picture=current_picture,
                stream_deltas=stream_deltas if include_stream else [],
                prior_posts=selected_prior,
            )
            freshness_meta = pack.get("freshness", {})
            if not isinstance(freshness_meta, dict):
                freshness_meta = self._build_freshness_meta(current_meta)
            freshness_meta = dict(freshness_meta)
            freshness_meta.setdefault("anchor_max_age_hours", self.authoritative_anchor_max_age_hours)
            return {
                "focus_text": focus_text,
                "structural_context": structural_context,
                "current_picture": current_picture,
                "stream_deltas": stream_deltas if include_stream else [],
                "source_docs": source_docs,
                "rendered": rendered,
                "selected_prior_posts": selected_prior,
                "current_meta": current_meta,
                "freshness_meta": freshness_meta,
                "pack_loaded": True,
                "pack_cycle_id": str(pack.get("cycle_id") or ""),
                "pack_contract_hash": str(pack.get("contract_hash") or ""),
                "pack_evidence_ledger": (
                    pack.get("evidence_ledger", []) if isinstance(pack.get("evidence_ledger"), list) else []
                ),
            }

        structural_snapshot = self.context_store.get_latest_snapshot("structural_context")
        current_snapshot = self.context_store.get_latest_snapshot("current_picture")
        structural_context = str((structural_snapshot or {}).get("content", ""))
        current_picture = str((current_snapshot or {}).get("content", ""))
        structural_excerpt = self._compact_text(structural_context, 700)
        current_excerpt = self._compact_text(current_picture, 850)
        current_meta = (current_snapshot or {}).get("meta", {}) if current_snapshot else {}
        if not isinstance(current_meta, dict):
            current_meta = {}
        freshness_meta = self._build_freshness_meta(current_meta)
        after_ts = current_meta.get("stream_last_included_at")
        stream_deltas = (
            self.stream_delta_extractor.extract(after_ts=after_ts, limit=self.context_max_stream_prompt)
            if include_stream
            else []
        )
        source_doc_ids = list((current_snapshot or {}).get("source_doc_ids", [])) if current_snapshot else []
        source_docs = self.context_store.get_documents_by_ids(source_doc_ids)
        filtered_prior_posts = self._prompt_eligible_prior_posts(prior_posts)
        rendered = render_analysis_context(
            structural_context=structural_excerpt,
            current_picture=current_excerpt,
            stream_deltas=stream_deltas,
            prior_posts=filtered_prior_posts,
        )
        return {
            "focus_text": focus_text,
            "structural_context": structural_context,
            "current_picture": current_picture,
            "stream_deltas": stream_deltas,
            "source_docs": source_docs,
            "rendered": rendered,
            "selected_prior_posts": filtered_prior_posts,
            "current_meta": current_meta,
            "freshness_meta": freshness_meta,
            "pack_loaded": False,
            "pack_cycle_id": "",
            "pack_contract_hash": "",
            "pack_evidence_ledger": [],
        }

    async def ensure_context_for_query(self) -> bool:
        if self._has_required_context() and self._has_latest_briefing_pack():
            return True
        try:
            await self.refresh_context_once(force_missing=True, reason="query")
            await self.compile_briefing_pack_once(force=True, reason="query")
        except Exception as exc:  # noqa: BLE001
            await self.observe("decide", f"On-demand context refresh failed: {exc}")
        self.context_ready = self._has_required_context() and self._has_latest_briefing_pack()
        return self.context_ready

    def _theories_text(self) -> str:
        return self.theories_path.read_text(encoding="utf-8") if self.theories_path.exists() else ""

    def _latest_post_age_hours(self) -> float | None:
        if self.db is None:
            return None
        row = self.db.execute(
            "SELECT timestamp FROM posts ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        dt = self._to_dt(row[0])
        if dt is None:
            return None
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0

    async def _theories_age_hours(self) -> float | None:
        updated_raw = await self.get_agent_state(self.theories_last_updated_state_key)
        updated_dt = self._to_dt(updated_raw)
        if updated_dt is None and self.theories_path.exists():
            try:
                updated_dt = datetime.fromtimestamp(self.theories_path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                updated_dt = None
        if updated_dt is None:
            return None
        return (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600.0

    def _should_force_post_backstop(self, context: dict | str) -> bool:
        age_hours = self._latest_post_age_hours()
        if age_hours is not None and age_hours < float(self.post_idle_backstop_hours):
            return False
        if isinstance(context, dict):
            change_type = str(context.get("change_type", "")).lower()
            if change_type in {"delta", "contradiction", "confirmation"}:
                return True
            significance = str(context.get("significance", "")).lower()
            if significance in {"high", "critical"}:
                return True
            if context.get("from") == "stream" and str(context.get("context", "")).strip():
                return True
        return bool(str(context).strip())

    async def ensure_theory_hygiene_reset(self) -> bool:
        if not self.contract.theory_policy.bootstrap_reset_once:
            return False
        already = await self.get_agent_state(self.theory_hygiene_reset_state_key)
        if str(already or "").lower() == "done":
            return False
        if not self._has_required_context():
            return False

        structural = self._snapshot_text("structural_context")
        primary, secondary, _ = self.context_store.select_current_picture_sources()
        if not structural.strip() or primary is None:
            return False

        anchor_blocks = [
            f"PRIMARY: {primary.get('title')} | {primary.get('published_at') or primary.get('fetched_at')}\n{self._compact_text(str(primary.get('body', '')), 1300)}"
        ]
        if secondary is not None:
            anchor_blocks.append(
                f"SECONDARY: {secondary.get('title')} | {secondary.get('published_at') or secondary.get('fetched_at')}\n"
                f"{self._compact_text(str(secondary.get('body', '')), 1000)}"
            )

        reset_prompt = f"""Reset working theories from authoritative context only.

Structural context:
{self._compact_text(structural, 2200)}

Anchor reporting:
{chr(10).join(anchor_blocks)}

Rules:
- Use structural context + anchor reports only.
- Do not use stream deltas, prior posts, or prior theories as factual anchors.
- Output compact theory lenses (priors, triggers, invalidation conditions).
- Remove stale framing and generic boilerplate.
- No scenario templates and no recycled example language.
"""
        updated = await self.llm(
            reset_prompt,
            model=self._model_for("update_theories"),
            max_tokens=420,
            expect_json=False,
            lane="background",
        )
        if not str(updated).strip():
            return False
        self.theories_path.write_text(str(updated).strip() + "\n", encoding="utf-8")
        await self.set_agent_state(self.theories_last_updated_state_key, datetime.now(timezone.utc).isoformat())
        await self.set_agent_state(self.theory_hygiene_reset_state_key, "done")
        await self.observe("write", "Theory hygiene reset from structural + authoritative anchors")
        return True

    async def seed_theories_if_empty(self) -> None:
        content = self._theories_text()
        if len(content.strip()) >= 20:
            return

        await self.observe("decide", "Seeding initial working theories")
        seed = await self.llm(
            self.domain["initial_priors_prompt"],
            model=self._model_for("seed_theories"),
            max_tokens=320,
            expect_json=False,
            lane="background",
        )
        self.theories_path.write_text(seed.strip() + "\n", encoding="utf-8")
        await self.set_agent_state(self.theories_last_updated_state_key, datetime.now(timezone.utc).isoformat())
        await self.observe("write", "Working theories seeded", detail=seed)

    async def handle(self, message: AgentMessage) -> None:
        if message.type == "interrupt":
            await self.handle_interrupt(message.payload, message.significance)
            return

        if message.type == "query":
            await self.handle_query(message.payload)
            return

        if message.type == "resource_update":
            self.mode = str(message.payload.get("mode", "full")).lower()
            await self.observe("decide", f"Mode updated to {self.mode}")
            return

    async def main_loop(self) -> None:
        while True:
            try:
                if self.state == "idle":
                    if not self.context_ready:
                        await self.refresh_context_once(force_missing=True, reason="main_loop")
                        await self.compile_briefing_pack_once(force=True, reason="main_loop")
                        self.context_ready = self._has_required_context() and self._has_latest_briefing_pack()
                    await self.check_stream()
                    await self.prioritize_questions()
                    await self.maybe_force_idle_post()
                    questions = self.get_open_questions()
                    if questions and self.mode == "full":
                        top = questions[0]
                        await self.deep_dive(top["question"], top["id"])
            except Exception as exc:  # noqa: BLE001
                logger.exception("researcher main loop error")
                await self.observe("decide", f"Researcher loop error: {exc}")
            await asyncio.sleep(30 + random.uniform(0, 5))

    def _stream_recent(self, n: int) -> list[str]:
        if not self.stream_path.exists():
            return []
        return [line for line in self.stream_path.read_text(encoding="utf-8").splitlines()[-n:] if line.strip()]

    def _stream_all(self) -> list[str]:
        if not self.stream_path.exists():
            return []
        return [line for line in self.stream_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def _line_is_material_signal(line: str) -> bool:
        upper = line.upper()
        return any(level in upper for level in ("[MEDIUM]", "[HIGH]", "[CRITICAL]"))

    async def check_stream(self) -> None:
        all_lines = self._stream_all()
        if not all_lines:
            return

        if self.last_stream_line_offset > len(all_lines):
            self.last_stream_line_offset = max(0, len(all_lines) - 30)

        new_lines = all_lines[self.last_stream_line_offset :]
        if not new_lines:
            return

        recent = all_lines[-30:]
        fingerprint = "\n".join(recent)
        if not any(self._line_is_material_signal(line) for line in new_lines):
            self.last_stream_line_offset = len(all_lines)
            self.last_stream_fingerprint = fingerprint
            await self.set_agent_state(self.stream_offset_state_key, str(self.last_stream_line_offset))
            await self.set_agent_state(self.stream_fingerprint_state_key, self.last_stream_fingerprint)
            return

        if self.last_stream_analysis_at is not None:
            elapsed = (datetime.now(timezone.utc) - self.last_stream_analysis_at).total_seconds()
            if elapsed < self.stream_analysis_min_interval:
                return

        if fingerprint == self.last_stream_fingerprint:
            self.last_stream_line_offset = len(all_lines)
            await self.set_agent_state(self.stream_offset_state_key, str(self.last_stream_line_offset))
            return

        if not self._has_required_context():
            await self.observe_throttled(
                "context:stream:waiting",
                "decide",
                "Stream assessment paused: context snapshots not ready",
                throttle_seconds=300,
            )
            return

        await self.observe("read", "Checking stream", detail=fingerprint)
        context_bundle = self.build_analysis_context(
            focus_text="stream delta assessment",
            prior_posts=[],
            include_stream=True,
        )
        if not bool(context_bundle.get("pack_loaded")):
            await self.observe_throttled(
                "context:stream:waiting_pack",
                "decide",
                "Stream assessment paused: briefing pack not ready",
                throttle_seconds=300,
            )
            return

        stream_prompt = self._render_prompt(
            "stream_assessment",
            {
                "recent_stream": "\n".join(recent),
                "layered_context": context_bundle["rendered"],
            },
        )
        result = await self.llm(
            stream_prompt,
            model=self._model_for("stream_assessment"),
            max_tokens=180,
            lane="background",
        )

        if not isinstance(result, dict) or "changes_picture" not in result:
            await self.observe_throttled(
                "stream:analysis:deferred",
                "decide",
                "Stream assessment deferred; retaining backlog for retry",
                throttle_seconds=300,
            )
            return

        new_question = result.get("new_question")
        if new_question:
            self.add_question(str(new_question))
            await self.observe("decide", f"New question: {new_question}")

        if result.get("changes_picture") and result.get("what"):
            await self.consider_post(
                {
                    "context": result["what"],
                    "from": "stream",
                    "change_type": result.get("change_type", "delta"),
                    "recent_stream": recent[-8:],
                },
                lane="background",
            )

        self.last_stream_fingerprint = fingerprint
        self.last_stream_line_offset = len(all_lines)
        self.last_stream_analysis_at = datetime.now(timezone.utc)
        await self.set_agent_state(self.stream_offset_state_key, str(self.last_stream_line_offset))
        await self.set_agent_state(self.stream_fingerprint_state_key, self.last_stream_fingerprint)
        await self.set_agent_state(self.stream_last_analysis_state_key, self.last_stream_analysis_at.isoformat())

    async def prioritize_questions(self) -> None:
        questions = self.get_open_questions(limit=20)
        if len(questions) < 2:
            return

        stream_recent = self._stream_recent(15)
        context_bundle = self.build_analysis_context(
            focus_text="question prioritization",
            prior_posts=[],
            include_stream=True,
        )
        if not bool(context_bundle.get("pack_loaded")):
            await self.observe_throttled(
                "context:questions:waiting_pack",
                "decide",
                "Question prioritization paused: briefing pack not ready",
                throttle_seconds=300,
            )
            return
        priority_prompt = self._render_prompt(
            "question_priority",
            {
                "questions": [{"id": q["id"], "question": q["question"], "age_hours": q["age_hours"]} for q in questions],
                "recent_stream": "\n".join(stream_recent),
                "current_picture": self._compact_text(str(context_bundle.get("current_picture", "")), 1700),
            },
        )
        ranked = await self.llm(
            priority_prompt,
            model=self._model_for("question_priority"),
            max_tokens=220,
            lane="background",
        )
        if not isinstance(ranked, dict):
            return

        for item in ranked.get("ranked", []):
            self.db.execute(
                "UPDATE questions SET priority_score=?, last_scored=? WHERE id=?",
                (
                    float(item.get("score", 0.5)),
                    datetime.now(timezone.utc).isoformat(),
                    item.get("id"),
                ),
            )
        self.db.commit()

    def get_open_questions(self, limit: int = 10) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT id, question, added_at, priority_score,
            ROUND((julianday('now') - julianday(added_at)) * 24, 1) as age_hours
            FROM questions
            WHERE answered_at IS NULL
            ORDER BY priority_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "id": row[0],
                "question": row[1],
                "added_at": row[2],
                "priority_score": row[3],
                "age_hours": row[4],
            }
            for row in rows
        ]

    def add_question(self, question: str) -> None:
        q = question.strip()
        if not q:
            return

        exists = self.db.execute(
            "SELECT id FROM questions WHERE question=? AND answered_at IS NULL",
            (q,),
        ).fetchone()
        if exists:
            return

        self.db.execute(
            "INSERT INTO questions (id, question, added_at, priority_score) VALUES (?, ?, ?, ?)",
            (str(uuid4()), q, datetime.now(timezone.utc).isoformat(), 0.5),
        )
        self.db.commit()

    @staticmethod
    def _fts_query(text: str) -> str:
        words = [w for w in "".join(ch if ch.isalnum() else " " for ch in text).split() if len(w) > 2]
        if not words:
            return "iran"
        return " OR ".join(words[:6])

    def search_posts(self, query: str, limit: int = 5) -> list[dict]:
        fts = self._fts_query(query)
        rows = self.db.execute(
            """
            SELECT p.id, p.timestamp, p.title, p.content, p.tags, p.supersedes,
                   COALESCE(p.quality_flags, '[]') AS quality_flags,
                   COALESCE(p.freshness_meta, '{}') AS freshness_meta
            FROM posts p
            JOIN posts_fts f ON p.rowid = f.rowid
            WHERE posts_fts MATCH ?
            ORDER BY p.timestamp DESC
            LIMIT ?
            """,
            (fts, limit),
        ).fetchall()

        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "title": row[2],
                "content": row[3],
                "tags": row[4],
                "supersedes": row[5],
                "quality_flags": json.loads(row[6] or "[]"),
                "freshness_meta": json.loads(row[7] or "{}"),
            }
            for row in rows
        ]

    def save_post(self, post: Post) -> None:
        self.db.execute(
            """
            INSERT INTO posts (
                id, timestamp, title, content, tags, supersedes,
                evidence_refs, claim_map_json, freshness_meta, quality_flags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post.id,
                post.timestamp.isoformat(),
                post.title,
                post.content,
                ",".join(post.tags),
                post.supersedes,
                json.dumps(post.evidence_refs, ensure_ascii=False),
                json.dumps(post.claim_map, ensure_ascii=False),
                json.dumps(post.freshness_meta, ensure_ascii=False),
                json.dumps(post.quality_flags, ensure_ascii=False),
            ),
        )
        self.db.commit()

    async def handle_interrupt(self, payload: dict, significance: str) -> None:
        # Urgent user query is routed as interrupt for priority handling.
        if payload.get("question") and payload.get("trace_id"):
            await self.handle_query(payload)
            return

        await self.report_state("interrupted", payload.get("headline", ""))
        await self.observe(
            "interrupt",
            f"[{significance}] {payload.get('headline', '')[:80]}",
            detail=json.dumps(payload, ensure_ascii=False),
            significance=significance,
        )
        lane = "interactive" if str(significance).lower() in {"critical", "high"} else "background"
        await self.consider_post(payload, lane=lane)
        await self.report_state("idle")

    async def consider_post(self, context: dict | str, lane: str = "background") -> bool:
        if lane == "background" and not self._has_required_context():
            await self.observe_throttled(
                "context:post:blocked",
                "decide",
                "Background post evaluation skipped: context snapshots missing",
                throttle_seconds=300,
            )
            return False

        if isinstance(context, dict):
            fts_query = (
                context.get("headline")
                or context.get("question")
                or context.get("context")
                or " ".join(str(v) for v in list(context.values())[:2])
            )
        else:
            fts_query = str(context)

        prior_posts = self.search_posts(fts_query[:120].strip())
        context_bundle = self.build_analysis_context(
            focus_text=str(context)[:800],
            prior_posts=prior_posts,
            include_stream=True,
        )
        if not bool(context_bundle.get("pack_loaded")):
            await self.observe_throttled(
                "context:post:waiting_pack",
                "decide",
                "Post evaluation skipped: briefing pack missing",
                throttle_seconds=300,
            )
            return False
        source_docs = context_bundle.get("source_docs", [])
        source_refs = [
            f"{doc.get('provider')} | {doc.get('doc_kind')} | {doc.get('title')}"
            for doc in source_docs[:5]
            if isinstance(doc, dict)
        ]
        freshness_meta = dict(context_bundle.get("freshness_meta", {}) or {})
        authoritative_fresh = bool(freshness_meta.get("authoritative_fresh"))
        stale_mode_active = bool(freshness_meta.get("stale_mode_active"))
        allow_stale_note = bool(self.contract.publish_policy.allow_stale_status_note)
        can_stale_note = await self._can_publish_stale_status_note() if stale_mode_active and allow_stale_note else False

        if self.contract.publish_policy.block_low_confidence_stream_only and self._is_low_confidence_stream_only(context):
            await self.observe_throttled(
                "blocked_low_signal",
                "decide",
                "blocked_low_signal: stream-only low-confidence trigger blocked by contract",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            return False

        if stale_mode_active and self.contract.publish_policy.require_authoritative_fresh and not can_stale_note:
            await self.observe_throttled(
                "blocked_stale_context",
                "decide",
                "blocked_stale_context: authoritative anchor is stale and stale-status note cooldown is active",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            return False

        judgment_prompt = self._render_prompt(
            "post_judgment",
            {
                "context": str(context)[:600],
                "layered_context": context_bundle["rendered"],
                "anchor_documents": "\n".join(source_refs),
                "weight_structural": self.contract.weights.structural_context,
                "weight_current": self.contract.weights.current_picture,
                "weight_deltas": self.contract.weights.latest_stream_deltas,
                "weight_priors": self.contract.weights.relevant_prior_posts,
            },
        )
        judgment = await self.llm(
            judgment_prompt,
            model=self._model_for("post_judgment"),
            max_tokens=160,
            lane=lane,
        )
        if not isinstance(judgment, dict):
            return False

        worth_posting = bool(judgment.get("worth_posting"))
        reason = str(judgment.get("reason", "no reason"))
        if not worth_posting and self._should_force_post_backstop(context):
            if authoritative_fresh:
                worth_posting = True
                reason = f"{reason} | forced by idle backstop"
            elif can_stale_note:
                worth_posting = True
                reason = f"{reason} | forced stale-status note (stale context)"
                stale_note_context = {
                    "from": "stale_status",
                    "context": str(context)[:500],
                    "stale_status_mode": True,
                    "freshness_meta": freshness_meta,
                    "quality_flags": ["stale_status"],
                }
                context = stale_note_context

        if stale_mode_active and worth_posting and not isinstance(context, dict):
            context = {
                "from": "stale_status",
                "context": str(context)[:500],
                "stale_status_mode": True,
                "freshness_meta": freshness_meta,
                "quality_flags": ["stale_status"],
            }
        elif stale_mode_active and worth_posting and isinstance(context, dict):
            context = dict(context)
            context["stale_status_mode"] = True
            context["freshness_meta"] = freshness_meta
            raw_flags = context.get("quality_flags", [])
            if isinstance(raw_flags, str):
                raw_flags = [raw_flags]
            elif not isinstance(raw_flags, list):
                raw_flags = []
            if "stale_status" not in raw_flags:
                raw_flags.append("stale_status")
            context["quality_flags"] = raw_flags

        if not worth_posting:
            await self.observe_throttled(
                "blocked_low_signal",
                "decide",
                f"blocked_low_signal: post rejected ({reason})",
                throttle_seconds=180,
            )
        await self.observe("decide", f"Post: {'YES' if worth_posting else 'NO'} - {reason}")

        if worth_posting:
            await self.write_post(context, judgment.get("supersedes_id"), lane=lane)
            return True
        return False

    async def maybe_force_idle_post(self) -> None:
        if self.post_idle_backstop_hours <= 0:
            return
        if not self._has_required_context():
            return

        age_hours = self._latest_post_age_hours()
        if age_hours is not None and age_hours < float(self.post_idle_backstop_hours):
            return

        last_forced_raw = await self.get_agent_state(self.post_idle_last_forced_state_key)
        last_forced_dt = self._to_dt(last_forced_raw)
        if last_forced_dt is not None:
            elapsed = (datetime.now(timezone.utc) - last_forced_dt).total_seconds()
            if elapsed < float(self.post_idle_force_cooldown_sec):
                return

        await self.observe_throttled(
            "post:idle_backstop:trigger",
            "decide",
            "Post cadence backstop triggered: no recent posts despite low-signal stream",
            throttle_seconds=900,
        )
        await self.set_agent_state(self.post_idle_last_forced_state_key, datetime.now(timezone.utc).isoformat())
        current_meta = self._snapshot_meta("current_picture")
        freshness_meta = self._build_freshness_meta(current_meta)
        stale_mode_active = bool(freshness_meta.get("stale_mode_active"))
        require_fresh = bool(self.contract.publish_policy.require_authoritative_fresh)
        if stale_mode_active and require_fresh and (
            not self.contract.publish_policy.allow_stale_status_note or not await self._can_publish_stale_status_note()
        ):
            await self.observe_throttled(
                "blocked_stale_context",
                "decide",
                "blocked_stale_context: idle backstop skipped because authoritative context is stale",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            return

        if stale_mode_active and require_fresh:
            context_payload = {
                "from": "stale_status",
                "stale_status_mode": True,
                "quality_flags": ["stale_status"],
                "freshness_meta": freshness_meta,
                "context": (
                    "Authoritative anchors are stale. Publish one explicit stale-status note with timestamped caveat, "
                    "what remains known from last anchor, and what cannot be inferred until refresh."
                ),
            }
        else:
            context_payload = {
                "from": "idle_backstop",
                "change_type": "delta",
                "significance": "medium",
                "context": (
                    "No new posts for extended interval. Produce a concise update anchored in structural context and current picture, "
                    "including what remains stable, what has shifted, and the highest-value watchpoints."
                ),
            }

        await self.consider_post(
            context_payload,
            lane="background",
        )

    async def write_post(self, context: dict | str, supersedes_id: str | None = None, lane: str = "background") -> None:
        if lane == "background" and not self._has_required_context():
            await self.observe_throttled(
                "context:write:blocked",
                "decide",
                "Background write skipped: context snapshots missing",
                throttle_seconds=300,
            )
            return

        await self.report_state("writing")

        if isinstance(context, dict):
            fts_query = (
                context.get("headline")
                or context.get("question")
                or context.get("context")
                or " ".join(str(v) for v in list(context.values())[:2])
            )
        else:
            fts_query = str(context)

        prior_posts = self.search_posts(fts_query[:120].strip())
        theories = self._theories_text()
        context_bundle = self.build_analysis_context(
            focus_text=str(context)[:800],
            prior_posts=prior_posts,
            include_stream=True,
        )
        if not bool(context_bundle.get("pack_loaded")):
            await self.observe_throttled(
                "context:write:waiting_pack",
                "decide",
                "Publish blocked by contract: briefing pack missing",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            await self.report_state("idle")
            return
        freshness_meta = dict(context_bundle.get("freshness_meta", {}) or {})
        context_quality_flags: list[str] = []
        stale_status_mode = False
        if isinstance(context, dict):
            override_meta = context.get("freshness_meta")
            if isinstance(override_meta, dict):
                freshness_meta.update(override_meta)
            context_flags_raw = context.get("quality_flags", [])
            if isinstance(context_flags_raw, str):
                context_quality_flags = [context_flags_raw]
            elif isinstance(context_flags_raw, list):
                context_quality_flags = [str(item) for item in context_flags_raw if str(item).strip()]
            stale_status_mode = bool(context.get("stale_status_mode"))
        if not stale_status_mode:
            stale_status_mode = bool(freshness_meta.get("stale_mode_active"))
        if stale_status_mode and not self.contract.publish_policy.allow_stale_status_note:
            await self.observe_throttled(
                "blocked_stale_context",
                "decide",
                "Publish blocked by contract: stale status notes are disabled",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            await self.report_state("idle")
            return
        if (
            bool(freshness_meta.get("stale_mode_active"))
            and self.contract.publish_policy.require_authoritative_fresh
            and not stale_status_mode
        ):
            await self.observe_throttled(
                "blocked_stale_context",
                "decide",
                "Publish blocked by contract: stale_context",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            await self.report_state("idle")
            return
        evidence_ledger = self._build_evidence_ledger(context, context_bundle, prior_posts)
        if not evidence_ledger:
            await self.observe_throttled(
                "blocked_ungrounded_claims",
                "decide",
                "blocked_ungrounded_claims: evidence ledger empty, skipping post publish",
                throttle_seconds=300,
            )
            await self.report_state("idle")
            return
        ledger_text = self._render_evidence_ledger(evidence_ledger)

        superseded_note = ""
        if supersedes_id:
            prior = self.db.execute(
                "SELECT title, timestamp FROM posts WHERE id=?",
                (supersedes_id,),
            ).fetchone()
            if prior:
                superseded_note = (
                    f"\nThis updates: '{prior[0]}' ({str(prior[1])[:10]}). "
                    "Acknowledge what changed and why."
                )

        title = ""
        content = ""
        tags: list[str] | str = []
        claim_map: list[dict[str, Any]] = []
        frame: dict[str, Any] = {}
        verifier_result: dict = {"passes": True, "issues": [], "quality_flags": [], "claim_map": []}
        prompt_prior_posts = context_bundle.get("selected_prior_posts", prior_posts)
        if not isinstance(prompt_prior_posts, list):
            prompt_prior_posts = prior_posts

        if stale_status_mode:
            title, content, tags = self._compose_stale_status_post(context, freshness_meta, evidence_ledger)
            context_quality_flags = [*context_quality_flags, "stale_status"]
        else:
            if self.writer_pipeline_v2:
                frame_prompt = self._render_prompt(
                    "post_frame",
                    {
                        "editorial_brief": self.editorial_brief,
                        "superseded_note": superseded_note,
                        "context": str(context)[:1000],
                        "layered_context": context_bundle["rendered"],
                        "freshness_contract": json.dumps(freshness_meta, ensure_ascii=False),
                        "working_theories": theories,
                        "relevant_prior_posts": [p["timestamp"][:10] + ": " + p["content"][:280] for p in prompt_prior_posts],
                        "evidence_ledger": ledger_text,
                    },
                )
                frame_result = await self.llm(
                    frame_prompt,
                    model=self._model_for("write_post"),
                    max_tokens=420,
                    lane=lane,
                    temperature=self._temperature_for("post_frame", 0.25),
                    background_prompt_char_limit=2600,
                    background_max_tokens_limit=420,
                )
                frame = self._normalize_post_frame(frame_result, evidence_ledger)
                if not frame.get("thesis") and not frame.get("core_claims"):
                    await self.observe_throttled(
                        "blocked_ungrounded_claims",
                        "decide",
                        "blocked_ungrounded_claims: post frame generation failed",
                        throttle_seconds=self.contract.observability.blocked_throttle_sec,
                    )
                    await self.report_state("idle")
                    return
                title = str(frame.get("title", "")).strip()
                prose_prompt = self._render_prompt(
                    "post_prose",
                    {
                        "editorial_brief": self.editorial_brief,
                        "frame_json": json.dumps(frame, ensure_ascii=False, indent=2),
                        "freshness_contract": json.dumps(freshness_meta, ensure_ascii=False),
                    },
                )
                content = await self.llm(
                    prose_prompt,
                    model=self._model_for("write_post"),
                    max_tokens=650,
                    expect_json=False,
                    lane=lane,
                    temperature=self._temperature_for("post_prose", 0.75),
                    background_prompt_char_limit=3200,
                    background_max_tokens_limit=650,
                )
                content = self._strip_public_evidence_tags(str(content or ""))
                if not content:
                    content = self._fallback_post_from_frame(frame)
            else:
                write_prompt = self._render_prompt(
                    "write_post",
                    {
                        "editorial_brief": self.editorial_brief,
                        "superseded_note": superseded_note,
                        "context": str(context)[:1000],
                        "layered_context": context_bundle["rendered"],
                        "freshness_contract": json.dumps(freshness_meta, ensure_ascii=False),
                        "working_theories": theories,
                        "relevant_prior_posts": [p["timestamp"][:10] + ": " + p["content"][:280] for p in prompt_prior_posts],
                        "evidence_ledger": ledger_text,
                    },
                )
                result = await self.llm(
                    write_prompt,
                    model=self._model_for("write_post"),
                    max_tokens=800,
                    lane=lane,
                )
                title = str((result or {}).get("title", "")).strip() if isinstance(result, dict) else ""
                content = str((result or {}).get("content", "")).strip() if isinstance(result, dict) else ""
                tags = result.get("tags", []) if isinstance(result, dict) else []
                legacy_ids = self._extract_evidence_tag_ids(content)
                frame = self._normalize_post_frame(
                    {
                        "title": title,
                        "thesis": self._compact_text(content.split(".")[0], 220),
                        "why_now": str(context)[:220],
                        "core_claims": [{"claim": self._compact_text(content, 220), "evidence_ids": legacy_ids[:3]}],
                        "supporting_evidence_ids": legacy_ids,
                        "revision_of_prior": None,
                        "watchpoint": "",
                        "confidence": "medium",
                        "quality_risks": [],
                    },
                    evidence_ledger,
                )

        content = str(content or "").strip()
        if len(content) < 40:
            await self.observe_throttled(
                "post:write:empty_abort",
                "decide",
                "Post generation returned empty content; skipping publish",
                throttle_seconds=300,
            )
            await self.report_state("idle")
            return

        style_violations = self._style_violations(
            content,
            require_evidence_tags=False,
            allow_visible_evidence_tags=stale_status_mode or not self.writer_pipeline_v2,
        )
        if style_violations and not stale_status_mode:
            await self.observe_throttled(
                "blocked_ungrounded_claims",
                "decide",
                "Publish blocked by contract: ungrounded_claims",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            await self.observe(
                "decide",
                "Post style-policy violations",
                detail=json.dumps(style_violations, ensure_ascii=False),
            )
            await self.report_state("idle")
            return

        evidence_map = {item.get("id"): item for item in evidence_ledger if item.get("id")}
        evidence_refs: list[dict[str, Any]] = []
        min_refs = max(1, int(self.contract.publish_policy.min_evidence_refs))

        if not stale_status_mode:
            verifier_result = await self._verify_post_grounding(
                post_title=title or "(untitled)",
                post_content=content,
                frame=frame,
                evidence_ledger=evidence_ledger,
                freshness_meta=freshness_meta,
            )
            verifier_passed = bool(verifier_result.get("passes", False))
            verifier_issues = [str(item) for item in verifier_result.get("issues", []) if str(item).strip()]
            if not verifier_passed and bool(verifier_result.get("needs_rewrite", True)):
                if self.writer_pipeline_v2:
                    rewrite_prompt = self._render_prompt(
                        "post_prose_rewrite",
                        {
                            "editorial_brief": self.editorial_brief,
                            "issues": "\n".join(f"- {issue}" for issue in verifier_issues),
                            "draft": content,
                            "frame_json": json.dumps(frame, ensure_ascii=False, indent=2),
                            "freshness_contract": json.dumps(freshness_meta, ensure_ascii=False),
                        },
                    )
                    rewrite_text = await self.llm(
                        rewrite_prompt,
                        model=self._model_for("write_post"),
                        max_tokens=650,
                        expect_json=False,
                        lane=lane,
                        temperature=self._temperature_for("post_prose_rewrite", 0.65),
                        background_prompt_char_limit=3200,
                        background_max_tokens_limit=650,
                    )
                    if str(rewrite_text).strip():
                        content = self._strip_public_evidence_tags(str(rewrite_text))
                        verifier_result = await self._verify_post_grounding(
                            post_title=title or "(untitled)",
                            post_content=content,
                            frame=frame,
                            evidence_ledger=evidence_ledger,
                            freshness_meta=freshness_meta,
                        )
                        verifier_passed = bool(verifier_result.get("passes", False))
                        verifier_issues = [str(item) for item in verifier_result.get("issues", []) if str(item).strip()]
            if not verifier_result.get("passes", False):
                await self.observe_throttled(
                    "blocked_ungrounded_claims",
                    "decide",
                    "blocked_ungrounded_claims: post verifier failed, publish blocked",
                    throttle_seconds=300,
                )
                if verifier_result.get("issues"):
                    await self.observe(
                        "decide",
                        "Post verifier issues",
                        detail=json.dumps(verifier_result.get("issues", []), ensure_ascii=False),
                )
                await self.report_state("idle")
                return
            claim_map = self._normalize_claim_map(verifier_result.get("claim_map", []), evidence_ledger, frame)
            evidence_ids = []
            for item in claim_map:
                for evidence_id in item.get("evidence_ids", []):
                    if evidence_id not in evidence_ids:
                        evidence_ids.append(evidence_id)
            evidence_refs = [evidence_map[item_id] for item_id in evidence_ids if item_id in evidence_map]
            if len(evidence_refs) < min_refs:
                await self.observe_throttled(
                    "blocked_ungrounded_claims",
                    "decide",
                    (
                        "blocked_ungrounded_claims: post missing required internal provenance refs, "
                        f"required={min_refs}, found={len(evidence_refs)}"
                    ),
                    throttle_seconds=self.contract.observability.blocked_throttle_sec,
                )
                await self.report_state("idle")
                return
        else:
            claim_map = []
            evidence_refs = evidence_ledger[:1]

        title = self._derive_post_title(title, content, str(context), thesis=str(frame.get("thesis", "")))

        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if not tags:
            tags = self._post_tags_from_context(context, frame if frame else None)
        quality_flags = []
        quality_flags.extend(context_quality_flags)
        verifier_flags_raw = verifier_result.get("quality_flags", []) if isinstance(verifier_result, dict) else []
        if isinstance(verifier_flags_raw, str):
            verifier_flags_raw = [verifier_flags_raw]
        quality_flags.extend([str(flag) for flag in verifier_flags_raw if str(flag).strip()])
        if self._is_low_confidence_stream_only(context):
            quality_flags.append("low_confidence_stream_only")
        dedup_quality_flags: list[str] = []
        seen_flags: set[str] = set()
        for flag in quality_flags:
            token = str(flag).strip()
            if not token or token in seen_flags:
                continue
            seen_flags.add(token)
            dedup_quality_flags.append(token)

        freshness_meta_for_post = dict(freshness_meta)
        freshness_meta_for_post["written_at"] = datetime.now(timezone.utc).isoformat()
        freshness_meta_for_post["stale_status_mode"] = stale_status_mode

        post = Post(
            id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
            title=title,
            content=content,
            tags=tags,
            supersedes=supersedes_id,
            evidence_refs=evidence_refs,
            claim_map=claim_map,
            freshness_meta=freshness_meta_for_post,
            quality_flags=dedup_quality_flags,
        )
        self.save_post(post)
        await self.observe("write", f"Post: {post.title}", detail=post.content)

        if stale_status_mode:
            await self._mark_stale_status_published()
            await self.observe_throttled(
                "published_stale_status",
                "write",
                "published_stale_status: stale-context note published",
                throttle_seconds=300,
            )
            await self.report_state("idle")
            return

        await self.maybe_update_theories(
            post.content,
            lane=lane,
            update_context={
                "evidence_refs": evidence_refs,
                "freshness_meta": freshness_meta_for_post,
                "quality_flags": dedup_quality_flags,
                "is_low_confidence_stream_only": self._is_low_confidence_stream_only(context),
            },
        )
        await self.report_state("idle")

    async def maybe_update_theories(
        self,
        post_content: str,
        lane: str = "background",
        update_context: dict | None = None,
    ) -> None:
        ctx = dict(update_context or {})
        if bool(ctx.get("is_low_confidence_stream_only")) and self.contract.publish_policy.block_low_confidence_stream_only:
            await self.observe_throttled(
                "blocked_low_signal",
                "decide",
                "blocked_low_signal: theory update skipped for low-confidence stream-only post",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            return

        freshness_meta = ctx.get("freshness_meta", {})
        if (
            self.contract.theory_policy.update_requires_authoritative_fresh
            and isinstance(freshness_meta, dict)
            and freshness_meta
            and not bool(freshness_meta.get("authoritative_fresh", True))
        ):
            await self.observe_throttled(
                "blocked_stale_context",
                "decide",
                "blocked_stale_context: theory update skipped under stale authoritative context",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            return

        theories = self._theories_text()
        evidence_refs = ctx.get("evidence_refs", [])
        if isinstance(evidence_refs, dict):
            evidence_refs = [evidence_refs]
        if len(evidence_refs) < max(1, int(self.contract.theory_policy.min_evidence_refs)):
            await self.observe_throttled(
                "blocked_ungrounded_claims",
                "decide",
                "Theory update blocked by contract",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            return
        evidence_snippets = [self._compact_text(str(item.get("summary", "")), 180) for item in evidence_refs[:8] if isinstance(item, dict)]
        theory_check_prompt = self._render_prompt(
            "theory_update_check",
            {
                "post_content": post_content[:800],
                "current_theories": theories,
                "evidence_snippets": evidence_snippets,
            },
        )
        check = await self.llm(
            theory_check_prompt,
            model=self._model_for("theories_update_check"),
            max_tokens=160,
            lane=lane,
        )
        if not isinstance(check, dict):
            return

        forced_refresh = False
        update_reason = str(check.get("what_changes") or "").strip()
        if not check.get("update_warranted"):
            theory_age = await self._theories_age_hours()
            if theory_age is not None and theory_age < float(self.theory_idle_backstop_hours):
                return
            if isinstance(freshness_meta, dict) and freshness_meta and not bool(freshness_meta.get("authoritative_fresh", True)):
                return
            forced_refresh = True
            update_reason = (
                "Scheduled refresh after prolonged inactivity. Re-state active priors against the latest current picture, "
                "remove stale framing, and tighten uncertainty bounds."
            )

        analysis_bundle = self.build_analysis_context(
            focus_text="theory_update",
            prior_posts=[],
            include_stream=False,
        )
        structural_context = str(analysis_bundle.get("structural_context", ""))
        current_picture = str(analysis_bundle.get("current_picture", ""))
        theory_rewrite_prompt = self._render_prompt(
            "theory_rewrite",
            {
                "editorial_brief": self.editorial_brief,
                "current_theories": theories,
                "structural_context": structural_context[:1600],
                "current_picture": current_picture[:1800],
                "evidence_snippets": evidence_snippets,
                "update_reason": update_reason,
            },
        )
        updated = await self.llm(
            theory_rewrite_prompt,
            model=self._model_for("update_theories"),
            max_tokens=500,
            expect_json=False,
            lane=lane,
            temperature=self._temperature_for("theory_rewrite", 0.50),
        )
        if not str(updated).strip():
            return

        theory_style_issues = self._style_violations(str(updated), require_evidence_tags=False)
        if any(item.startswith("banned_phrase:") for item in theory_style_issues):
            await self.observe_throttled(
                "blocked_ungrounded_claims",
                "decide",
                "Theory update blocked by contract",
                throttle_seconds=self.contract.observability.blocked_throttle_sec,
            )
            return

        verify_prompt = self._render_prompt(
            "theory_verifier",
            {
                "updated_theories": self._compact_text(str(updated), 2200),
                "evidence_snippets": evidence_snippets,
            },
        )
        verify = await self.llm(
            verify_prompt,
            model=self._model_for("theories_update_check"),
            max_tokens=160,
            lane=lane,
            temperature=self._temperature_for("theory_verifier", 0.10),
        )
        if not isinstance(verify, dict) or not bool(verify.get("passes")):
            await self.observe_throttled(
                "blocked_ungrounded_claims",
                "decide",
                "blocked_ungrounded_claims: theory update rejected by verifier",
                throttle_seconds=300,
            )
            return

        self.theories_path.write_text(updated.strip() + "\n", encoding="utf-8")
        await self.set_agent_state(self.theories_last_updated_state_key, datetime.now(timezone.utc).isoformat())
        if forced_refresh:
            await self.observe("write", "Theories updated (idle backstop refresh)", detail=updated)
        else:
            await self.observe("write", "Theories updated", detail=updated)

    async def deep_dive(self, question: str, question_id: str) -> None:
        budget = int(self.res_config.get("dive_budget", {}).get(self.mode, 0))
        if budget == 0:
            await self.observe("decide", f"{self.mode.upper()} mode - skipping dive: {question}")
            return

        await self.report_state("diving", question)

        readings: list[dict] = []
        calls = 0
        current_q = question
        dive_bundle = self.build_analysis_context(
            focus_text=question,
            prior_posts=[],
            include_stream=False,
        )
        structural_context = str(dive_bundle.get("structural_context", ""))
        current_picture = str(dive_bundle.get("current_picture", ""))

        while calls < budget:
            results = await self.search_web(current_q)
            calls += 1
            await self.observe(
                "search",
                f"Search: {current_q}",
                detail=str([r.get("title", r.get("url")) for r in results[:5]]),
            )

            for result in results[:3]:
                if calls >= budget:
                    break
                try:
                    content = await self.fetch_content(result["url"])
                    readings.append(
                        {
                            "source": result["url"],
                            "title": result.get("title", ""),
                            "content": content[:3000],
                        }
                    )
                    calls += 1
                    await self.observe("read", f"Read: {result.get('title', result['url'])[:80]}", detail=content[:2000])
                except Exception as exc:  # noqa: BLE001
                    await self.observe("decide", f"Fetch error: {exc}")

            if not readings:
                break

            check = await self.llm(
                f"""Researching: \"{question}\"
Sub-question: \"{current_q}\"
Tether: {self.domain['tether_rule']}

Structural context:
{structural_context[:1400]}

Current picture:
{current_picture[:1400]}

Recent readings:
{[r['content'][:250] for r in readings[-3:]]}

1. Does continuing sharpen understanding of the Iran conflict specifically?
2. Follow-up question? (null if exhausted or diverging)

Return JSON: {{"sharpens_conflict": bool, "follow_up": "str or null", "reason": "brief"}}""",
                model=self._model_for("tether_check"),
                max_tokens=150,
                lane="background",
            )
            calls += 1

            await self.observe(
                "decide",
                f"Tether: {'CONTINUE' if check.get('sharpens_conflict') else 'STOP'} - {check.get('reason', '')}",
            )

            if not check.get("sharpens_conflict"):
                break
            if not check.get("follow_up"):
                break
            current_q = str(check["follow_up"])

        self.db.execute(
            "UPDATE questions SET answered_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), question_id),
        )
        self.db.commit()

        if readings:
            await self.consider_post(
                {
                    "question": question,
                    "findings": [r["content"][:400] for r in readings[:3]],
                    "sources": [r["source"] for r in readings],
                },
                lane="background",
            )

        await self.report_state("idle")

    async def handle_query(self, payload: dict) -> None:
        question = str(payload.get("question", "")).strip()
        if not question:
            return

        trace_id = str(payload.get("trace_id", str(uuid4())))
        await self.report_state("answering", question)
        context_ready = await self.ensure_context_for_query()

        relevant = self._prompt_eligible_prior_posts(self.search_posts(question, limit=5))
        theories = self._theories_text()
        context_bundle = self.build_analysis_context(
            focus_text=question,
            prior_posts=relevant,
            include_stream=True,
        )
        if not bool(context_bundle.get("pack_loaded")):
            uncertainty_note = (
                "Briefing pack is not ready yet. Answering from partial context; treat this as provisional."
            )
        else:
            uncertainty_note = ""
        if not context_ready:
            uncertainty_note = (
                "Context refresh is degraded right now. Answer conservatively from available memory and flag uncertainty."
            )
        changed_tokens = [
            token.strip().lower()
            for token in str(self.contract.query_policy.changed_today_keywords).split(",")
            if token.strip()
        ]
        changed_today = any(token in question.lower() for token in changed_tokens)
        uncertainty_line = f"- {uncertainty_note}" if uncertainty_note else ""
        changed_today_line = (
            "- This is a what-changed-today query: include a short delta list at the end." if changed_today else ""
        )

        query_prompt = self._render_prompt(
            "query_answer",
            {
                "editorial_brief": self.editorial_brief,
                "question": question,
                "prior_posts": [p["timestamp"][:10] + " - " + p["title"] + ": " + p["content"][:300] for p in relevant],
                "working_theories": theories,
                "layered_context": context_bundle["rendered"],
                "uncertainty_line": uncertainty_line,
                "changed_today_line": changed_today_line,
            },
        )
        response = await self.llm(
            query_prompt,
            model=self._model_for("answer_question"),
            max_tokens=650,
            expect_json=False,
            lane="interactive",
            temperature=self._temperature_for("query_answer", 0.60),
        )

        await self.redis.publish(
            f"channel:response:{trace_id}",
            json.dumps({"answer": response, "trace_id": trace_id}),
        )
        await self.observe("write", f"Answered: {question[:60]}", detail=response)
        await self.report_state("idle")

    async def search_web(self, query: str) -> list[dict]:
        if not self.tavily_key:
            await self.observe("decide", "TAVILY_API_KEY missing - web search unavailable")
            return []

        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5,
                },
            )
            response.raise_for_status()
            data = response.json()

        return data.get("results", [])

    async def fetch_content(self, url: str) -> str:
        import httpx
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        text = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
        return text[:5000]
