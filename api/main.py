import asyncio
import datetime
import json
import os
import sqlite3
import time
from datetime import timezone
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import redis.asyncio as aioredis
import yaml
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.researcher.briefing_pack import pack_age_seconds
from scripts.init_db import init as init_db
from shared.schemas import (
    BriefingPackResponse,
    ContextDocumentRef,
    ContextSnapshotResponse,
    ContextStatusResponse,
    CurrentPictureLatestResponse,
)


def _memory_path(filename: str) -> Path:
    if Path("/memory").exists():
        return Path("/memory") / filename
    return Path("memory") / filename


def _db_path() -> str:
    path = _memory_path("posts.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379")


def _resources_path() -> Path:
    mounted = Path("/config/resources.yaml")
    if mounted.exists():
        return mounted
    return Path("config/resources.yaml")


def _resources_config() -> dict:
    path = _resources_path()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _to_int(value) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_dt(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _safe_json_loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return default


def _briefing_pack_root() -> Path:
    env_value = os.environ.get("BRIEFING_PACK_ROOT", "").strip()
    if env_value:
        return Path(env_value)
    if Path("/memory").exists():
        return Path("/memory/briefing_packs")
    return Path("memory/briefing_packs")


def _briefing_pack_latest_path() -> Path:
    return _briefing_pack_root() / "latest.json"


def _briefing_pack_latest_markdown_path() -> Path:
    return _briefing_pack_root() / "latest.md"


def _load_briefing_pack_latest() -> dict | None:
    path = _briefing_pack_latest_path()
    if not path.exists():
        return None
    return _safe_json_loads(path.read_text(encoding="utf-8"), None)


def _load_briefing_pack_cycle(cycle_id: str) -> dict | None:
    safe_cycle = str(cycle_id or "").strip()
    if not safe_cycle:
        return None
    path = _briefing_pack_root() / "cycles" / safe_cycle / "pack.json"
    if not path.exists():
        return None
    return _safe_json_loads(path.read_text(encoding="utf-8"), None)


def _load_latest_snapshot(snapshot_type: str) -> dict | None:
    conn = sqlite3.connect(_db_path())
    row = conn.execute(
        """
        SELECT id, snapshot_type, generated_at, content, content_hash, source_doc_ids, meta_json
        FROM context_snapshots
        WHERE snapshot_type = ?
        ORDER BY generated_at DESC
        LIMIT 1
        """,
        (snapshot_type,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "snapshot_type": row[1],
        "generated_at": row[2],
        "content": row[3],
        "content_hash": row[4],
        "source_doc_ids": _safe_json_loads(row[5], []),
        "meta": _safe_json_loads(row[6], {}),
    }


def _load_documents_by_ids(ids: list[str]) -> list[ContextDocumentRef]:
    keys = [item for item in ids if item]
    if not keys:
        return []
    placeholders = ",".join("?" for _ in keys)
    conn = sqlite3.connect(_db_path())
    rows = conn.execute(
        f"""
        SELECT id, provider, doc_kind, title, canonical_url, published_at
        FROM context_documents
        WHERE id IN ({placeholders})
        """,
        tuple(keys),
    ).fetchall()
    conn.close()
    by_id = {
        str(row[0]): ContextDocumentRef(
            id=str(row[0]),
            provider=str(row[1]),
            doc_kind=str(row[2]),
            title=str(row[3]),
            url=str(row[4]),
            published_at=row[5],
        )
        for row in rows
    }
    return [by_id[item] for item in keys if item in by_id]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(_db_path())
    _memory_path("working_theories.md").touch(exist_ok=True)
    _memory_path("stream.md").touch(exist_ok=True)
    proposals = _memory_path("source_proposals.json")
    if not proposals.exists():
        proposals.write_text("[]", encoding="utf-8")
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/health")
async def health():
    redis = await aioredis.from_url(_redis_url())
    raw = os.environ.get("ACTIVE_AGENTS", "researcher")
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    agents_to_check = requested or ["researcher"]
    agents = {}
    for agent in agents_to_check:
        heartbeat = await redis.get(f"heartbeat:{agent}")
        agents[agent] = "ok" if heartbeat else "down"
    await redis.aclose()
    return {"status": "ok", "agents": agents}


@app.get("/budget/status")
async def budget_status(window_minutes: int = 60):
    safe_window = max(5, min(window_minutes, 240))
    resources = _resources_config()
    groq_cfg = resources.get("groq", {}) if isinstance(resources, dict) else {}
    models_cfg = groq_cfg.get("models", {}) if isinstance(groq_cfg, dict) else {}
    threshold = float(groq_cfg.get("rate_limit_threshold", 1.0))
    skip_prefix = os.environ.get("BUDGET_SKIP_KEY_PREFIX", "budget_skip")
    reasons = ("budget_exhausted", "oversized_request", "groq_rate_limit")
    lanes = ("background", "interactive")

    aliases = list(models_cfg.keys())
    now = int(time.time())
    current_bucket = now // 60
    previous_bucket = current_bucket - 1

    redis = await aioredis.from_url(_redis_url())
    try:
        usage_keys: list[str] = []
        for alias in aliases:
            usage_keys.extend(
                [
                    f"global_rl:{alias}:{current_bucket}:req",
                    f"global_rl:{alias}:{current_bucket}:tok",
                    f"global_rl:{alias}:{previous_bucket}:req",
                    f"global_rl:{alias}:{previous_bucket}:tok",
                ]
            )

        usage_values = await redis.mget(usage_keys) if usage_keys else []
        usage_by_alias: dict[str, dict[str, int]] = {}
        idx = 0
        for alias in aliases:
            usage_by_alias[alias] = {
                "req_current": _to_int(usage_values[idx]),
                "tok_current": _to_int(usage_values[idx + 1]),
                "req_previous": _to_int(usage_values[idx + 2]),
                "tok_previous": _to_int(usage_values[idx + 3]),
            }
            idx += 4

        skip_keys: list[str] = []
        skip_map: list[tuple[str, str, str]] = []
        for alias in aliases:
            for reason in reasons:
                for lane in lanes:
                    for bucket in range(current_bucket - safe_window + 1, current_bucket + 1):
                        skip_keys.append(f"{skip_prefix}:{alias}:{reason}:{lane}:{bucket}")
                        skip_map.append((alias, reason, lane))

        skip_values = await redis.mget(skip_keys) if skip_keys else []
        skip_by_alias: dict[str, dict[str, dict[str, int]]] = {
            alias: {reason: {lane: 0 for lane in lanes} for reason in reasons} for alias in aliases
        }
        for raw, (alias, reason, lane) in zip(skip_values, skip_map):
            skip_by_alias[alias][reason][lane] += _to_int(raw)
    finally:
        await redis.aclose()

    models: dict[str, dict] = {}
    skip_totals = {reason: 0 for reason in reasons}

    for alias in aliases:
        cfg = models_cfg.get(alias, {}) if isinstance(models_cfg, dict) else {}
        rpm_limit = max(1, int(cfg.get("rpm_limit", 30)))
        tpm_limit = max(1, int(cfg.get("tpm_limit", 6000)))
        effective_rpm = max(1, int(rpm_limit * threshold))
        effective_tpm = max(1, int(tpm_limit * threshold))
        usage = usage_by_alias.get(alias, {"req_current": 0, "tok_current": 0, "req_previous": 0, "tok_previous": 0})
        skips = skip_by_alias.get(alias, {reason: {lane: 0 for lane in lanes} for reason in reasons})

        reason_totals = {
            reason: int(skips.get(reason, {}).get("background", 0) + skips.get(reason, {}).get("interactive", 0))
            for reason in reasons
        }
        for reason, value in reason_totals.items():
            skip_totals[reason] += value

        models[alias] = {
            "limits": {
                "rpm": rpm_limit,
                "tpm": tpm_limit,
                "threshold": threshold,
                "effective_rpm": effective_rpm,
                "effective_tpm": effective_tpm,
            },
            "usage": {
                "current_bucket": {
                    "requests": usage["req_current"],
                    "tokens": usage["tok_current"],
                },
                "previous_bucket": {
                    "requests": usage["req_previous"],
                    "tokens": usage["tok_previous"],
                },
                # Two-bucket approximation to surface trends around minute boundaries.
                "rolling_approx_60s": {
                    "requests": usage["req_current"] + usage["req_previous"],
                    "tokens": usage["tok_current"] + usage["tok_previous"],
                },
            },
            "utilization": {
                "rpm_current": round(usage["req_current"] / max(1, effective_rpm), 3),
                "tpm_current": round(usage["tok_current"] / max(1, effective_tpm), 3),
            },
            "skips_last_window": {
                "window_minutes": safe_window,
                "reasons": reason_totals,
                "background_total": int(
                    sum(skips.get(reason, {}).get("background", 0) for reason in reasons)
                ),
                "interactive_total": int(
                    sum(skips.get(reason, {}).get("interactive", 0) for reason in reasons)
                ),
                "total": int(sum(reason_totals.values())),
            },
        }

    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "window_seconds": 60,
        "skip_window_minutes": safe_window,
        "models": models,
        "skip_totals_last_window": {
            "reasons": skip_totals,
            "total": int(sum(skip_totals.values())),
        },
    }


@app.websocket("/ws/observatory")
async def observatory(ws: WebSocket):
    await ws.accept()
    redis = await aioredis.from_url(_redis_url())
    pubsub = redis.pubsub()
    await pubsub.subscribe("channel:observatory")

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            await ws.send_text(data)
    except Exception:
        pass
    finally:
        await pubsub.unsubscribe("channel:observatory")
        await redis.aclose()


@app.get("/observatory/recent")
async def recent_observatory_events(limit: int = 200, after_seq: int | None = None):
    safe_limit = max(1, min(limit, 1000))
    conn = sqlite3.connect(_db_path())

    if after_seq is not None and after_seq > 0:
        rows = conn.execute(
            """
            SELECT seq, timestamp, agent, event_type, summary, preview, significance, has_detail
            FROM observatory_events
            WHERE seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (after_seq, safe_limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT seq, timestamp, agent, event_type, summary, preview, significance, has_detail
            FROM observatory_events
            ORDER BY seq DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        rows = list(reversed(rows))
    conn.close()

    return [
        {
            "seq": row[0],
            "timestamp": row[1],
            "agent": row[2],
            "event_type": row[3],
            "summary": row[4],
            "preview": row[5],
            "significance": row[6],
            "has_detail": bool(row[7]),
        }
        for row in rows
    ]


@app.get("/observatory/event/{seq}")
async def observatory_event_detail(seq: int):
    conn = sqlite3.connect(_db_path())
    row = conn.execute(
        """
        SELECT seq, timestamp, agent, event_type, summary, preview, detail, significance, has_detail
        FROM observatory_events
        WHERE seq = ?
        """,
        (seq,),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Event not found")

    return {
        "seq": row[0],
        "timestamp": row[1],
        "agent": row[2],
        "event_type": row[3],
        "summary": row[4],
        "preview": row[5],
        "detail": row[6],
        "significance": row[7],
        "has_detail": bool(row[8]),
    }


@app.get("/context/current-picture", response_model=ContextSnapshotResponse)
async def context_current_picture():
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /current-picture/latest")


@app.get("/current-picture/latest", response_model=CurrentPictureLatestResponse)
async def current_picture_latest():
    snapshot = _load_latest_snapshot("ui_current_picture")
    if not snapshot:
        raise HTTPException(status_code=404, detail="Current picture is warming up.")

    generated_at = str(snapshot.get("generated_at") or "")
    generated_dt = _to_dt(generated_at)
    now = datetime.datetime.now(timezone.utc)
    age_seconds = max(0, int((now - generated_dt).total_seconds())) if generated_dt else None
    stale_after = max(300, int(os.environ.get("UI_CURRENT_PICTURE_INTERVAL_SEC", "10800") or "10800"))
    stale = age_seconds is None or age_seconds > stale_after

    meta = snapshot.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}

    conn = sqlite3.connect(_db_path())
    state_rows = conn.execute(
        """
        SELECT key, value
        FROM agent_state
        WHERE key IN (
            'researcher:ui_current_picture:last_attempt_at',
            'researcher:ui_current_picture:last_error'
        )
        """
    ).fetchall()
    conn.close()
    state = {row[0]: row[1] for row in state_rows}
    last_error = state.get("researcher:ui_current_picture:last_error")
    if last_error is not None and not str(last_error).strip():
        last_error = None

    return CurrentPictureLatestResponse(
        generated_at=generated_at,
        content=str(snapshot.get("content", "")),
        source_generated_at=(
            str(meta.get("source_generated_at")).strip() if meta.get("source_generated_at") is not None else None
        ),
        source_url=str(meta.get("source_url") or "") or None,
        model=str(meta.get("model") or "") or None,
        age_seconds=age_seconds,
        stale=stale,
        last_attempt_at=state.get("researcher:ui_current_picture:last_attempt_at"),
        last_error=last_error,
    )


@app.get("/context/structural", response_model=ContextSnapshotResponse)
async def context_structural():
    snapshot = _load_latest_snapshot("structural_context")
    if not snapshot:
        raise HTTPException(status_code=404, detail="Structural context snapshot not found")
    sources = _load_documents_by_ids(list(snapshot.get("source_doc_ids", [])))
    return ContextSnapshotResponse(
        generated_at=str(snapshot.get("generated_at")),
        content=str(snapshot.get("content", "")),
        meta=dict(snapshot.get("meta", {})),
        sources=sources,
    )


@app.get("/context/documents")
async def context_documents(
    provider: str | None = None,
    doc_kind: str | None = None,
    limit: int = 20,
    include_body: bool = False,
):
    safe_limit = max(1, min(limit, 200))
    clauses = []
    params: list[str | int] = []
    if provider:
        clauses.append("provider = ?")
        params.append(provider)
    if doc_kind:
        clauses.append("doc_kind = ?")
        params.append(doc_kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = sqlite3.connect(_db_path())
    rows = conn.execute(
        f"""
        SELECT id, provider, doc_kind, cycle, coverage_date, title, canonical_url,
               published_at, fetched_at, content_hash, body, meta_json
        FROM context_documents
        {where}
        ORDER BY COALESCE(published_at, fetched_at) DESC
        LIMIT ?
        """,
        (*params, safe_limit),
    ).fetchall()
    conn.close()
    return [
        {
            "id": str(row[0]),
            "provider": row[1],
            "doc_kind": row[2],
            "cycle": row[3],
            "coverage_date": row[4],
            "title": row[5],
            "url": row[6],
            "published_at": row[7],
            "fetched_at": row[8],
            "content_hash": row[9],
            "meta": _safe_json_loads(row[11], {}),
            "body": row[10] if include_body else None,
        }
        for row in rows
    ]


@app.get("/briefing-pack/latest", response_model=BriefingPackResponse)
async def briefing_pack_latest():
    payload = _load_briefing_pack_latest()
    if not payload:
        raise HTTPException(status_code=404, detail="Briefing pack not found")
    return BriefingPackResponse(**payload)


@app.get("/briefing-pack/latest/markdown", response_class=PlainTextResponse)
async def briefing_pack_latest_markdown():
    path = _briefing_pack_latest_markdown_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Briefing pack markdown not found")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/briefing-pack/{cycle_id}", response_model=BriefingPackResponse)
async def briefing_pack_cycle(cycle_id: str):
    payload = _load_briefing_pack_cycle(cycle_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Briefing pack cycle not found")
    return BriefingPackResponse(**payload)


@app.get("/context/status", response_model=ContextStatusResponse)
async def context_status():
    max_staleness = max(300, int(os.environ.get("CONTEXT_MAX_STALENESS_SEC", "21600")))
    structural_refresh = max(3600, int(os.environ.get("CONTEXT_STRUCTURAL_REFRESH_SEC", "86400")))
    anchor_freshness_hours = float(os.environ.get("AUTHORITATIVE_ANCHOR_MAX_AGE_HOURS", "12") or "12")
    anchor_freshness_sec = max(3600, int(anchor_freshness_hours * 3600))
    stale_note_cooldown_sec = max(60, int(os.environ.get("STALE_STATUS_NOTE_COOLDOWN_SEC", "86400")))
    now = datetime.datetime.now(timezone.utc)

    conn = sqlite3.connect(_db_path())
    state_rows = conn.execute(
        """
        SELECT key, value
        FROM agent_state
        WHERE key IN (
            'researcher:context:last_successful_refresh_at',
            'researcher:context:last_current_picture_generated_at',
            'researcher:brief_pack:last_stale_status_at'
        )
        """
    ).fetchall()
    state = {row[0]: row[1] for row in state_rows}

    def latest_doc(provider: str, doc_kind: str):
        return conn.execute(
            """
            SELECT id, provider, doc_kind, cycle, title, canonical_url, published_at, fetched_at
            FROM context_documents
            WHERE provider = ? AND doc_kind = ?
            ORDER BY COALESCE(published_at, fetched_at) DESC
            LIMIT 1
            """,
            (provider, doc_kind),
        ).fetchone()

    structural_doc = latest_doc("iran_monitor", "structural_overview")
    briefing_doc = latest_doc("iran_monitor", "daily_briefing")
    anchor_doc = latest_doc("critical_threats", "iran_update")

    current_snapshot = conn.execute(
        """
        SELECT generated_at, meta_json
        FROM context_snapshots
        WHERE snapshot_type = 'current_picture'
        ORDER BY generated_at DESC
        LIMIT 1
        """
    ).fetchone()
    structural_snapshot = conn.execute(
        """
        SELECT generated_at
        FROM context_snapshots
        WHERE snapshot_type = 'structural_context'
        ORDER BY generated_at DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()

    def age_seconds(raw: str | None) -> int | None:
        dt = _to_dt(raw)
        if dt is None:
            return None
        return max(0, int((now - dt).total_seconds()))

    structural_age = age_seconds(structural_snapshot[0] if structural_snapshot else None)
    current_age = age_seconds(current_snapshot[0] if current_snapshot else None)

    primary_cycle = None
    primary_published = None
    if current_snapshot:
        meta = _safe_json_loads(current_snapshot[1], {})
        primary_cycle = meta.get("primary_anchor_cycle")
        primary_published = meta.get("primary_anchor_published_at")
    if primary_cycle is None and anchor_doc:
        primary_cycle = anchor_doc[3]
        primary_published = anchor_doc[6] or anchor_doc[7]

    anchor_age = age_seconds(primary_published)

    def provider_status(age: int | None, stale_after: int) -> str:
        if age is None:
            return "error"
        if age > stale_after:
            return "stale"
        return "ok"

    last_refresh = state.get("researcher:context:last_successful_refresh_at")
    provider_map = {
        "critical_threats": provider_status(
            age_seconds((anchor_doc[6] if anchor_doc else None) or (anchor_doc[7] if anchor_doc else None)),
            max_staleness,
        ),
        "iran_monitor_structural": provider_status(
            age_seconds((structural_doc[6] if structural_doc else None) or (structural_doc[7] if structural_doc else None)),
            structural_refresh,
        ),
        "iran_monitor_briefing": provider_status(
            age_seconds((briefing_doc[6] if briefing_doc else None) or (briefing_doc[7] if briefing_doc else None)),
            max_staleness,
        ),
    }
    authoritative_fresh = (
        anchor_age is not None
        and anchor_age <= anchor_freshness_sec
        and provider_map.get("critical_threats") == "ok"
    )
    stale_note_available = False
    if not authoritative_fresh:
        last_stale_raw = state.get("researcher:brief_pack:last_stale_status_at")
        last_stale = _to_dt(last_stale_raw)
        if last_stale is None:
            stale_note_available = True
        else:
            stale_note_available = max(0, int((now - last_stale).total_seconds())) >= stale_note_cooldown_sec
    publish_mode = "normal" if authoritative_fresh else ("stale_note_only" if stale_note_available else "blocked")

    latest_pack = _load_briefing_pack_latest()
    briefing_pack_cycle_id = None
    briefing_pack_generated_at = None
    briefing_pack_age = None
    briefing_pack_contract_hash = None
    if isinstance(latest_pack, dict):
        briefing_pack_cycle_id = str(latest_pack.get("cycle_id") or "") or None
        briefing_pack_generated_at = str(latest_pack.get("generated_at") or "") or None
        briefing_pack_contract_hash = str(latest_pack.get("contract_hash") or "") or None
        briefing_pack_age = pack_age_seconds(latest_pack)
    status = ContextStatusResponse(
        last_successful_refresh_at=last_refresh,
        structural_age_seconds=structural_age,
        current_picture_age_seconds=current_age,
        primary_anchor_cycle=primary_cycle,
        primary_anchor_published_at=primary_published,
        authoritative_fresh=authoritative_fresh,
        stale_mode_active=not authoritative_fresh,
        publish_mode=publish_mode,
        stale_note_available=stale_note_available,
        briefing_pack_cycle_id=briefing_pack_cycle_id,
        briefing_pack_generated_at=briefing_pack_generated_at,
        briefing_pack_age_seconds=briefing_pack_age,
        briefing_pack_contract_hash=briefing_pack_contract_hash,
        provider_status=provider_map,
    )
    return status


@app.get("/posts")
async def get_posts(limit: int = 50, tag: str | None = None):
    conn = sqlite3.connect(_db_path())
    if tag:
        rows = conn.execute(
            """
            SELECT id, timestamp, title, content, tags, supersedes,
                   COALESCE(evidence_refs, '[]') AS evidence_refs,
                   COALESCE(claim_map_json, '[]') AS claim_map_json,
                   COALESCE(freshness_meta, '{}') AS freshness_meta,
                   COALESCE(quality_flags, '[]') AS quality_flags
            FROM posts
            WHERE tags LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (f"%{tag}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, timestamp, title, content, tags, supersedes,
                   COALESCE(evidence_refs, '[]') AS evidence_refs,
                   COALESCE(claim_map_json, '[]') AS claim_map_json,
                   COALESCE(freshness_meta, '{}') AS freshness_meta,
                   COALESCE(quality_flags, '[]') AS quality_flags
            FROM posts
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "timestamp": row[1],
            "title": row[2],
            "content": row[3],
            "tags": row[4] or "",
            "supersedes": row[5],
            "evidence_refs": _safe_json_loads(row[6], []),
            "claim_map": _safe_json_loads(row[7], []),
            "freshness_meta": _safe_json_loads(row[8], {}),
            "quality_flags": _safe_json_loads(row[9], []),
        }
        for row in rows
    ]


@app.get("/posts/{post_id}/evidence")
async def get_post_evidence(post_id: str):
    conn = sqlite3.connect(_db_path())
    row = conn.execute(
        """
        SELECT id, timestamp, title,
               COALESCE(evidence_refs, '[]') AS evidence_refs,
               COALESCE(claim_map_json, '[]') AS claim_map_json,
               COALESCE(freshness_meta, '{}') AS freshness_meta,
               COALESCE(quality_flags, '[]') AS quality_flags
        FROM posts
        WHERE id = ?
        LIMIT 1
        """,
        (post_id,),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Post not found")
    return {
        "id": row[0],
        "timestamp": row[1],
        "title": row[2],
        "evidence_refs": _safe_json_loads(row[3], []),
        "claim_map": _safe_json_loads(row[4], []),
        "freshness_meta": _safe_json_loads(row[5], {}),
        "quality_flags": _safe_json_loads(row[6], []),
    }


@app.get("/questions")
async def get_questions():
    conn = sqlite3.connect(_db_path())
    rows = conn.execute(
        "SELECT id, question, priority_score FROM questions WHERE answered_at IS NULL ORDER BY priority_score DESC"
    ).fetchall()
    conn.close()
    return [{"id": row[0], "question": row[1], "priority": row[2]} for row in rows]


@app.get("/working-theories")
async def working_theories():
    path = _memory_path("working_theories.md")
    try:
        content = path.read_text(encoding="utf-8")
        updated_at = datetime.datetime.utcfromtimestamp(path.stat().st_mtime).isoformat() + "Z"
        return {"content": content, "updated_at": updated_at}
    except FileNotFoundError:
        return {"content": "", "updated_at": None}


class ChatRequest(BaseModel):
    question: str
    urgent: bool = False


@app.post("/chat")
async def chat(body: ChatRequest):
    trace_id = str(uuid4())
    redis = await aioredis.from_url(_redis_url())

    await redis.publish(
        "channel:orchestrator",
        json.dumps(
            {
                "id": trace_id,
                "trace_id": trace_id,
                "from_agent": "user",
                "to_agent": "orchestrator",
                "type": "query",
                "payload": {
                    "question": body.question,
                    "urgent": body.urgent,
                    "trace_id": trace_id,
                },
                "significance": "high" if body.urgent else "low",
            }
        ),
    )

    pubsub = redis.pubsub()
    await pubsub.subscribe(f"channel:response:{trace_id}")

    try:
        async with asyncio.timeout(30):
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                payload = json.loads(data)
                return {"answer": payload.get("answer", ""), "trace_id": trace_id}
    except asyncio.TimeoutError:
        return {
            "answer": "Still working on it - try again in a moment.",
            "trace_id": trace_id,
        }
    finally:
        await pubsub.unsubscribe(f"channel:response:{trace_id}")
        await redis.aclose()


@app.get("/source-proposals")
async def get_source_proposals():
    path = _memory_path("source_proposals.json")
    if not path.exists():
        return []
    proposals = json.loads(path.read_text(encoding="utf-8"))
    return [proposal for proposal in proposals if proposal.get("status") == "pending"]


@app.post("/source-proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str):
    redis = await aioredis.from_url(_redis_url())
    await redis.publish(
        "channel:source_monitor",
        json.dumps(
            {
                "id": str(uuid4()),
                "trace_id": str(uuid4()),
                "from_agent": "user",
                "to_agent": "source_monitor",
                "type": "approve_source",
                "payload": {"id": proposal_id},
                "significance": "low",
            }
        ),
    )
    await redis.aclose()
    return {"status": "approved", "id": proposal_id}


@app.post("/source-proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str):
    redis = await aioredis.from_url(_redis_url())
    await redis.publish(
        "channel:source_monitor",
        json.dumps(
            {
                "id": str(uuid4()),
                "trace_id": str(uuid4()),
                "from_agent": "user",
                "to_agent": "source_monitor",
                "type": "reject_source",
                "payload": {"id": proposal_id},
                "significance": "low",
            }
        ),
    )
    await redis.aclose()
    return {"status": "rejected", "id": proposal_id}


if FRONTEND_DIST.exists():
    @app.get("/", include_in_schema=False)
    async def serve_root():
        return FileResponse(FRONTEND_DIST / "index.html")


    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith(("ws/",)):
            return {"detail": "Not found"}

        candidate = FRONTEND_DIST / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
