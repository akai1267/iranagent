from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

REQUIRED_TEMPLATE_IDS = [
    "post_judgment",
    "write_post",
    "rewrite_post",
    "post_verifier",
    "theory_update_check",
    "theory_rewrite",
    "theory_verifier",
    "query_answer",
    "stream_assessment",
    "question_priority",
]


DEFAULT_TEMPLATES: dict[str, str] = {
    "post_judgment": "Context: {{context}}\n\nLayered context:\n{{layered_context}}\n\nReturn JSON: {\"worth_posting\": bool, \"reason\": \"one sentence\", \"supersedes_id\": \"post id or null\"}",
    "write_post": "{{voice_prompt}}\n\nContext: {{context}}\n\nLayered context:\n{{layered_context}}\n\nEvidence ledger:\n{{evidence_ledger}}\n\nReturn JSON: {\"title\": \"str\", \"content\": \"str\", \"tags\": [\"str\"]}",
    "rewrite_post": "{{voice_prompt}}\n\nIssues:\n{{issues}}\n\nDraft:\n{{draft}}\n\nEvidence ledger:\n{{evidence_ledger}}\n\nReturn JSON: {\"title\": \"str\", \"content\": \"str\", \"tags\": [\"str\"]}",
    "post_verifier": "Title: {{title}}\n\nPost:\n{{post_content}}\n\nEvidence ledger:\n{{evidence_ledger}}\n\nReturn JSON: {\"passes\": true, \"issues\": [], \"needs_rewrite\": false, \"quality_flags\": []}",
    "theory_update_check": "Post:\n{{post_content}}\n\nCurrent theories:\n{{current_theories}}\n\nReturn JSON: {\"update_warranted\": bool, \"what_changes\": \"str or null\"}",
    "theory_rewrite": "{{voice_prompt}}\n\nCurrent theories:\n{{current_theories}}\n\nStructural:\n{{structural_context}}\n\nCurrent picture:\n{{current_picture}}\n\nEvidence:\n{{evidence_snippets}}\n\nWhat changes: {{update_reason}}\n\nReturn updated text only.",
    "theory_verifier": "Updated theories:\n{{updated_theories}}\n\nEvidence:\n{{evidence_snippets}}\n\nReturn JSON: {\"passes\": true, \"issues\": []}",
    "query_answer": "{{voice_prompt}}\n\nQuestion: {{question}}\n\nLayered context:\n{{layered_context}}\n\nAnswer directly.",
    "stream_assessment": "Recent stream:\n{{recent_stream}}\n\nLayered context:\n{{layered_context}}\n\nReturn JSON: {\"changes_picture\": bool, \"change_type\": \"delta|contradiction|confirmation|none\", \"what\": \"description or null\", \"new_question\": \"question or null\"}",
    "question_priority": "Questions:\n{{questions}}\n\nRecent stream:\n{{recent_stream}}\n\nCurrent picture:\n{{current_picture}}\n\nReturn JSON: {\"ranked\": [{\"id\": \"str\", \"score\": 0.0}]}",
}


@dataclass
class PackPolicy:
    compile_tick_sec: int = 60
    max_pack_age_sec: int = 5400
    retention_count: int = 120
    max_stream_deltas: int = 10
    max_prior_posts: int = 6


@dataclass
class WeightPolicy:
    structural_context: float = 0.35
    current_picture: float = 0.45
    latest_stream_deltas: float = 0.15
    relevant_prior_posts: float = 0.05


@dataclass
class PublishPolicy:
    require_authoritative_fresh: bool = True
    authoritative_anchor_max_age_hours: float = 12.0
    allow_stale_status_note: bool = True
    stale_status_cooldown_sec: int = 86400
    min_evidence_refs: int = 2
    block_low_confidence_stream_only: bool = True


@dataclass
class TheoryPolicy:
    update_requires_authoritative_fresh: bool = True
    min_evidence_refs: int = 2
    bootstrap_reset_once: bool = True


@dataclass
class QueryPolicy:
    changed_today_keywords: str = "changed today,today,latest change"
    require_layer_order: bool = True


@dataclass
class StylePolicy:
    banned_phrases: list[str] = field(default_factory=lambda: [
        "another round of sanctions",
        "proxy route gives",
        "iran is not striking directly right now",
        "multiple competing assessments",
        "it remains to be seen",
    ])
    require_paragraphs_only: bool = True
    require_evidence_tags: bool = True


@dataclass
class ObservabilityPolicy:
    unchanged_throttle_sec: int = 900
    blocked_throttle_sec: int = 300


@dataclass
class ResearcherContract:
    version: int = 1
    pack: PackPolicy = field(default_factory=PackPolicy)
    weights: WeightPolicy = field(default_factory=WeightPolicy)
    publish_policy: PublishPolicy = field(default_factory=PublishPolicy)
    theory_policy: TheoryPolicy = field(default_factory=TheoryPolicy)
    query_policy: QueryPolicy = field(default_factory=QueryPolicy)
    style_policy: StylePolicy = field(default_factory=StylePolicy)
    observability: ObservabilityPolicy = field(default_factory=ObservabilityPolicy)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def _bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    @staticmethod
    def _int(value: Any, default: int, minimum: int = 0) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, parsed)

    @staticmethod
    def _float(value: Any, default: float, minimum: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, parsed)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ResearcherContract":
        payload = data or {}
        pack = payload.get("pack", {}) if isinstance(payload.get("pack", {}), dict) else {}
        weights = payload.get("weights", {}) if isinstance(payload.get("weights", {}), dict) else {}
        publish_policy = payload.get("publish_policy", {}) if isinstance(payload.get("publish_policy", {}), dict) else {}
        theory_policy = payload.get("theory_policy", {}) if isinstance(payload.get("theory_policy", {}), dict) else {}
        query_policy = payload.get("query_policy", {}) if isinstance(payload.get("query_policy", {}), dict) else {}
        style_policy = payload.get("style_policy", {}) if isinstance(payload.get("style_policy", {}), dict) else {}
        observability = payload.get("observability", {}) if isinstance(payload.get("observability", {}), dict) else {}

        banned = style_policy.get("banned_phrases", [])
        if not isinstance(banned, list):
            banned = []

        return cls(
            version=cls._int(payload.get("version"), 1, minimum=1),
            pack=PackPolicy(
                compile_tick_sec=cls._int(pack.get("compile_tick_sec"), 60, minimum=10),
                max_pack_age_sec=cls._int(pack.get("max_pack_age_sec"), 5400, minimum=300),
                retention_count=cls._int(pack.get("retention_count"), 120, minimum=10),
                max_stream_deltas=cls._int(pack.get("max_stream_deltas"), 10, minimum=1),
                max_prior_posts=cls._int(pack.get("max_prior_posts"), 6, minimum=1),
            ),
            weights=WeightPolicy(
                structural_context=cls._float(weights.get("structural_context"), 0.35, minimum=0.0),
                current_picture=cls._float(weights.get("current_picture"), 0.45, minimum=0.0),
                latest_stream_deltas=cls._float(weights.get("latest_stream_deltas"), 0.15, minimum=0.0),
                relevant_prior_posts=cls._float(weights.get("relevant_prior_posts"), 0.05, minimum=0.0),
            ),
            publish_policy=PublishPolicy(
                require_authoritative_fresh=cls._bool(publish_policy.get("require_authoritative_fresh"), True),
                authoritative_anchor_max_age_hours=cls._float(
                    publish_policy.get("authoritative_anchor_max_age_hours"), 12.0, minimum=1.0
                ),
                allow_stale_status_note=cls._bool(publish_policy.get("allow_stale_status_note"), True),
                stale_status_cooldown_sec=cls._int(
                    publish_policy.get("stale_status_cooldown_sec"), 86400, minimum=3600
                ),
                min_evidence_refs=cls._int(publish_policy.get("min_evidence_refs"), 2, minimum=1),
                block_low_confidence_stream_only=cls._bool(
                    publish_policy.get("block_low_confidence_stream_only"), True
                ),
            ),
            theory_policy=TheoryPolicy(
                update_requires_authoritative_fresh=cls._bool(
                    theory_policy.get("update_requires_authoritative_fresh"), True
                ),
                min_evidence_refs=cls._int(theory_policy.get("min_evidence_refs"), 2, minimum=1),
                bootstrap_reset_once=cls._bool(theory_policy.get("bootstrap_reset_once"), True),
            ),
            query_policy=QueryPolicy(
                changed_today_keywords=str(query_policy.get("changed_today_keywords", "changed today,today,latest change")),
                require_layer_order=cls._bool(query_policy.get("require_layer_order"), True),
            ),
            style_policy=StylePolicy(
                banned_phrases=[str(item) for item in banned if str(item).strip()],
                require_paragraphs_only=cls._bool(style_policy.get("require_paragraphs_only"), True),
                require_evidence_tags=cls._bool(style_policy.get("require_evidence_tags"), True),
            ),
            observability=ObservabilityPolicy(
                unchanged_throttle_sec=cls._int(observability.get("unchanged_throttle_sec"), 900, minimum=30),
                blocked_throttle_sec=cls._int(observability.get("blocked_throttle_sec"), 300, minimum=30),
            ),
        )


def contract_hash(contract: ResearcherContract) -> str:
    payload = json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_contract(path: str | Path) -> tuple[ResearcherContract, bool]:
    contract_path = Path(path)
    fallback = False
    try:
        raw = yaml.safe_load(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else None
        if raw is not None and not isinstance(raw, dict):
            raw = None
            fallback = True
    except Exception:
        raw = None
        fallback = True
    contract = ResearcherContract.from_dict(raw)
    return contract, fallback


def load_templates(path: str | Path) -> tuple[dict[str, str], bool]:
    tpl_path = Path(path)
    fallback = False
    loaded: dict[str, str] = {}
    if tpl_path.exists():
        try:
            data = yaml.safe_load(tpl_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                loaded = {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
            else:
                fallback = True
        except Exception:
            fallback = True

    templates = dict(DEFAULT_TEMPLATES)
    templates.update(loaded)
    for key in REQUIRED_TEMPLATE_IDS:
        if key not in templates or not str(templates[key]).strip():
            templates[key] = DEFAULT_TEMPLATES[key]
            fallback = True
    return templates, fallback


def render_template(template: str, values: dict[str, Any]) -> str:
    rendered = str(template)
    for key, value in values.items():
        token = "{{" + str(key) + "}}"
        rendered = rendered.replace(token, str(value))
    return rendered
