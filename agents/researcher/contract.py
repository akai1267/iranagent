from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

REQUIRED_TEMPLATE_IDS = [
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
]


DEFAULT_TEMPLATES: dict[str, str] = {
    "post_judgment": "Context: {{context}}\n\nLayered context:\n{{layered_context}}\n\nReturn JSON: {\"worth_posting\": bool, \"reason\": \"one sentence\", \"supersedes_id\": \"post id or null\"}",
    "post_frame": "{{editorial_brief}}\n\nContext trigger:\n{{context}}\n\nLayered context:\n{{layered_context}}\n\nEvidence ledger:\n{{evidence_ledger}}\n\nReturn JSON: {\"title\": \"str\", \"thesis\": \"str\", \"why_now\": \"str\", \"core_claims\": [{\"claim\": \"str\", \"evidence_ids\": [\"E1\"]}], \"supporting_evidence_ids\": [\"E1\"], \"revision_of_prior\": \"str or null\", \"watchpoint\": \"str\", \"confidence\": \"high|medium|low\", \"quality_risks\": [\"str\"]}",
    "post_prose": "{{editorial_brief}}\n\nFrame:\n{{frame_json}}\n\nWrite the final note only.",
    "post_prose_rewrite": "{{editorial_brief}}\n\nIssues:\n{{issues}}\n\nFrame:\n{{frame_json}}\n\nDraft:\n{{draft}}\n\nWrite the final revised note only.",
    "post_verifier_v2": "Frame:\n{{frame_json}}\n\nPublic note:\n{{post_content}}\n\nEvidence ledger:\n{{evidence_ledger}}\n\nReturn JSON: {\"passes\": true, \"issues\": [], \"needs_rewrite\": false, \"claim_map\": [{\"claim\": \"str\", \"evidence_ids\": [\"E1\"]}], \"quality_flags\": []}",
    "write_post": "{{editorial_brief}}\n\nContext: {{context}}\n\nLayered context:\n{{layered_context}}\n\nEvidence ledger:\n{{evidence_ledger}}\n\nReturn JSON: {\"title\": \"str\", \"content\": \"str\", \"tags\": [\"str\"]}",
    "rewrite_post": "{{editorial_brief}}\n\nIssues:\n{{issues}}\n\nDraft:\n{{draft}}\n\nEvidence ledger:\n{{evidence_ledger}}\n\nReturn JSON: {\"title\": \"str\", \"content\": \"str\", \"tags\": [\"str\"]}",
    "post_verifier": "Title: {{title}}\n\nPost:\n{{post_content}}\n\nEvidence ledger:\n{{evidence_ledger}}\n\nReturn JSON: {\"passes\": true, \"issues\": [], \"needs_rewrite\": false, \"quality_flags\": []}",
    "theory_update_check": "Post:\n{{post_content}}\n\nCurrent theories:\n{{current_theories}}\n\nReturn JSON: {\"update_warranted\": bool, \"what_changes\": \"str or null\"}",
    "theory_rewrite": "{{editorial_brief}}\n\nCurrent theories:\n{{current_theories}}\n\nStructural:\n{{structural_context}}\n\nCurrent picture:\n{{current_picture}}\n\nEvidence:\n{{evidence_snippets}}\n\nWhat changes: {{update_reason}}\n\nReturn updated text only.",
    "theory_verifier": "Updated theories:\n{{updated_theories}}\n\nEvidence:\n{{evidence_snippets}}\n\nReturn JSON: {\"passes\": true, \"issues\": []}",
    "query_answer": "{{editorial_brief}}\n\nQuestion: {{question}}\n\nLayered context:\n{{layered_context}}\n\nAnswer directly.",
    "stream_assessment": "Recent stream:\n{{recent_stream}}\n\nLayered context:\n{{layered_context}}\n\nReturn JSON: {\"changes_picture\": bool, \"change_type\": \"delta|contradiction|confirmation|none\", \"what\": \"description or null\", \"new_question\": \"question or null\"}",
    "question_priority": "Questions:\n{{questions}}\n\nRecent stream:\n{{recent_stream}}\n\nCurrent picture:\n{{current_picture}}\n\nReturn JSON: {\"ranked\": [{\"id\": \"str\", \"score\": 0.0}]}",
    "current_picture_frame": "{{current_picture_brief}}\n\nSource map:\n{{source_map}}\n\nStream deltas:\n{{delta_lines}}\n\nReturn JSON: {\"topline\": \"str\", \"operational_picture\": \"str\", \"political_diplomatic_picture\": \"str\", \"what_changed\": \"str\", \"what_is_continuing\": \"str\", \"watchpoints_12_24h\": \"str\", \"gaps\": \"str\", \"source_use\": \"str\"}",
    "current_picture_prose": "{{current_picture_brief}}\n\nFrame:\n{{frame_json}}\n\nWrite the final brief only.",
    "current_picture_verifier_v2": "Frame:\n{{frame_json}}\n\nBrief:\n{{snapshot_text}}\n\nSource docs summary:\n{{source_brief}}\n\nReturn JSON: {\"passes\": true, \"issues\": [], \"needs_rewrite\": false}",
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
class WritingPolicy:
    output_shape: str = "analyst_note"
    public_grounding_mode: str = "hidden_provenance"
    inference_mode: str = "disciplined_thesis"
    writer_pipeline_v2: bool = True


@dataclass
class TemperaturePolicy:
    post_frame: float = 0.25
    post_prose: float = 0.75
    post_prose_rewrite: float = 0.65
    post_verifier_v2: float = 0.10
    current_picture_frame: float = 0.25
    current_picture_prose: float = 0.65
    current_picture_verifier_v2: float = 0.10
    query_answer: float = 0.60
    theory_rewrite: float = 0.50
    theory_verifier: float = 0.10


@dataclass
class PriorContextPolicy:
    excluded_quality_flags: list[str] = field(default_factory=lambda: ["stale_status", "low_confidence_stream_only"])
    exclude_banned_phrase_posts: bool = True
    max_age_days: int = 14
    prompt_max_posts: int = 4


@dataclass
class TitlePolicy:
    max_words: int = 10
    avoid_generic_titles: bool = True
    derive_from_thesis_if_missing: bool = True


@dataclass
class CurrentPicturePolicy:
    paragraph_min: int = 4
    paragraph_max: int = 5
    allow_markdown_headings: bool = False
    analyst_specificity_required: bool = True


@dataclass
class RuntimeGatePolicy:
    hard_cut_stale_mode: bool = True
    critical_high_behavior: str = "triage_only"
    medium_stale_handling: str = "drop_count"
    stream_skip_when_gate_closed: bool = True
    stream_defer_cooldown_sec: int = 600
    skip_background_deep_dive_when_gate_closed: bool = True


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
    writing_policy: WritingPolicy = field(default_factory=WritingPolicy)
    temperature_policy: TemperaturePolicy = field(default_factory=TemperaturePolicy)
    prior_context_policy: PriorContextPolicy = field(default_factory=PriorContextPolicy)
    title_policy: TitlePolicy = field(default_factory=TitlePolicy)
    current_picture_policy: CurrentPicturePolicy = field(default_factory=CurrentPicturePolicy)
    runtime_gate_policy: RuntimeGatePolicy = field(default_factory=RuntimeGatePolicy)
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
        writing_policy = payload.get("writing_policy", {}) if isinstance(payload.get("writing_policy", {}), dict) else {}
        temperature_policy = (
            payload.get("temperature_policy", {}) if isinstance(payload.get("temperature_policy", {}), dict) else {}
        )
        prior_context_policy = (
            payload.get("prior_context_policy", {}) if isinstance(payload.get("prior_context_policy", {}), dict) else {}
        )
        title_policy = payload.get("title_policy", {}) if isinstance(payload.get("title_policy", {}), dict) else {}
        current_picture_policy = (
            payload.get("current_picture_policy", {})
            if isinstance(payload.get("current_picture_policy", {}), dict)
            else {}
        )
        runtime_gate_policy = (
            payload.get("runtime_gate_policy", {})
            if isinstance(payload.get("runtime_gate_policy", {}), dict)
            else {}
        )

        banned = style_policy.get("banned_phrases", [])
        if not isinstance(banned, list):
            banned = []
        excluded_quality_flags = prior_context_policy.get("excluded_quality_flags", [])
        if not isinstance(excluded_quality_flags, list):
            excluded_quality_flags = []

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
            writing_policy=WritingPolicy(
                output_shape=str(writing_policy.get("output_shape", "analyst_note")),
                public_grounding_mode=str(writing_policy.get("public_grounding_mode", "hidden_provenance")),
                inference_mode=str(writing_policy.get("inference_mode", "disciplined_thesis")),
                writer_pipeline_v2=cls._bool(writing_policy.get("writer_pipeline_v2"), True),
            ),
            temperature_policy=TemperaturePolicy(
                post_frame=cls._float(temperature_policy.get("post_frame"), 0.25, minimum=0.0),
                post_prose=cls._float(temperature_policy.get("post_prose"), 0.75, minimum=0.0),
                post_prose_rewrite=cls._float(temperature_policy.get("post_prose_rewrite"), 0.65, minimum=0.0),
                post_verifier_v2=cls._float(temperature_policy.get("post_verifier_v2"), 0.10, minimum=0.0),
                current_picture_frame=cls._float(temperature_policy.get("current_picture_frame"), 0.25, minimum=0.0),
                current_picture_prose=cls._float(temperature_policy.get("current_picture_prose"), 0.65, minimum=0.0),
                current_picture_verifier_v2=cls._float(
                    temperature_policy.get("current_picture_verifier_v2"), 0.10, minimum=0.0
                ),
                query_answer=cls._float(temperature_policy.get("query_answer"), 0.60, minimum=0.0),
                theory_rewrite=cls._float(temperature_policy.get("theory_rewrite"), 0.50, minimum=0.0),
                theory_verifier=cls._float(temperature_policy.get("theory_verifier"), 0.10, minimum=0.0),
            ),
            prior_context_policy=PriorContextPolicy(
                excluded_quality_flags=[str(item) for item in excluded_quality_flags if str(item).strip()],
                exclude_banned_phrase_posts=cls._bool(
                    prior_context_policy.get("exclude_banned_phrase_posts"), True
                ),
                max_age_days=cls._int(prior_context_policy.get("max_age_days"), 14, minimum=1),
                prompt_max_posts=cls._int(prior_context_policy.get("prompt_max_posts"), 4, minimum=1),
            ),
            title_policy=TitlePolicy(
                max_words=cls._int(title_policy.get("max_words"), 10, minimum=3),
                avoid_generic_titles=cls._bool(title_policy.get("avoid_generic_titles"), True),
                derive_from_thesis_if_missing=cls._bool(title_policy.get("derive_from_thesis_if_missing"), True),
            ),
            current_picture_policy=CurrentPicturePolicy(
                paragraph_min=cls._int(current_picture_policy.get("paragraph_min"), 4, minimum=1),
                paragraph_max=cls._int(current_picture_policy.get("paragraph_max"), 5, minimum=1),
                allow_markdown_headings=cls._bool(current_picture_policy.get("allow_markdown_headings"), False),
                analyst_specificity_required=cls._bool(
                    current_picture_policy.get("analyst_specificity_required"), True
                ),
            ),
            runtime_gate_policy=RuntimeGatePolicy(
                hard_cut_stale_mode=cls._bool(runtime_gate_policy.get("hard_cut_stale_mode"), True),
                critical_high_behavior=str(runtime_gate_policy.get("critical_high_behavior", "triage_only")),
                medium_stale_handling=str(runtime_gate_policy.get("medium_stale_handling", "drop_count")),
                stream_skip_when_gate_closed=cls._bool(runtime_gate_policy.get("stream_skip_when_gate_closed"), True),
                stream_defer_cooldown_sec=cls._int(
                    runtime_gate_policy.get("stream_defer_cooldown_sec"), 600, minimum=30
                ),
                skip_background_deep_dive_when_gate_closed=cls._bool(
                    runtime_gate_policy.get("skip_background_deep_dive_when_gate_closed"), True
                ),
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
