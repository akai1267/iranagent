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


class ObservabilityEvent(BaseModel):
    seq: int | None = None
    agent: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str
    preview: Optional[str] = None
    has_detail: bool = False
    detail: Optional[str] = None
    event_type: str
    significance: Optional[str] = None


class CurrentPictureLatestResponse(BaseModel):
    generated_at: str
    content: str
    source_generated_at: Optional[str] = None
    source_url: Optional[str] = None
    model: Optional[str] = None
    model_chain: list[str] = Field(default_factory=list)
    pipeline_version: Optional[str] = None
    quality_flags: list[str] = Field(default_factory=list)
    age_seconds: Optional[int] = None
    stale: bool = False
    last_attempt_at: Optional[str] = None
    last_error: Optional[str] = None
