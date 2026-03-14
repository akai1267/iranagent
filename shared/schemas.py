from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    from_agent: str
    to_agent: str
    type: str
    payload: dict[str, Any]
    significance: str = "low"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Signal(BaseModel):
    headline: str
    source: str
    source_type: str
    reliability: float
    url: str
    snippet: str
    significance: str
    why_significant: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Post(BaseModel):
    id: str
    timestamp: datetime
    title: str
    content: str
    tags: list[str]
    supersedes: Optional[str] = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    freshness_meta: dict[str, Any] = Field(default_factory=dict)
    quality_flags: list[str] = Field(default_factory=list)


class ObservabilityEvent(BaseModel):
    seq: int | None = None
    agent: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str
    preview: Optional[str] = None
    has_detail: bool = False
    detail: Optional[str] = None
    event_type: str  # search|read|decide|write|interrupt|working|done
    significance: Optional[str] = None


class ContextDocumentRef(BaseModel):
    id: str
    provider: str
    doc_kind: str
    title: str
    url: str
    published_at: Optional[str] = None


class ContextSnapshotResponse(BaseModel):
    generated_at: str
    content: str
    meta: dict[str, Any]
    sources: list[ContextDocumentRef]


class ContextStatusResponse(BaseModel):
    last_successful_refresh_at: Optional[str] = None
    structural_age_seconds: Optional[int] = None
    current_picture_age_seconds: Optional[int] = None
    primary_anchor_cycle: Optional[str] = None
    primary_anchor_published_at: Optional[str] = None
    authoritative_fresh: bool = False
    stale_mode_active: bool = True
    briefing_pack_cycle_id: Optional[str] = None
    briefing_pack_generated_at: Optional[str] = None
    briefing_pack_age_seconds: Optional[int] = None
    briefing_pack_contract_hash: Optional[str] = None
    provider_status: dict[str, str]


class BriefingPackFreshness(BaseModel):
    authoritative_fresh: bool
    stale_mode_active: bool
    anchor_max_age_hours: float
    primary_anchor: dict[str, Any]
    secondary_anchor: dict[str, Any] | None = None
    provider_status: dict[str, str]


class BriefingPackSectionBundle(BaseModel):
    structural_context: str
    current_picture: str
    latest_stream_deltas: list[dict[str, Any]]
    relevant_prior_posts: list[dict[str, Any]]
    working_theories: str


class BriefingPackEvidenceRef(BaseModel):
    id: str
    kind: str
    authority: str
    summary: str
    source_ref: str
    timestamp: str
    url: str


class BriefingPackResponse(BaseModel):
    pack_version: int
    cycle_id: str
    generated_at: str
    generated_by: str
    contract_hash: str
    freshness: BriefingPackFreshness
    weights: dict[str, float]
    sections: BriefingPackSectionBundle
    evidence_ledger: list[BriefingPackEvidenceRef]
    input_refs: dict[str, Any]
    quality_flags: list[str]
    change_flags: list[str]
