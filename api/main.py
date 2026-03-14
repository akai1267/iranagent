import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from scripts.init_db import init as init_db
from shared.schemas import CurrentPictureLatestResponse


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


def _safe_json_loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return default


def _to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _load_latest_snapshot(snapshot_type: str) -> dict | None:
    conn = sqlite3.connect(_db_path())
    try:
        row = conn.execute(
            """
            SELECT generated_at, content, meta_json
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
        "generated_at": row[0],
        "content": row[1],
        "meta": _safe_json_loads(row[2], {}),
    }


def _load_agent_state(keys: list[str]) -> dict[str, str]:
    if not keys:
        return {}
    conn = sqlite3.connect(_db_path())
    try:
        placeholders = ",".join("?" for _ in keys)
        rows = conn.execute(
            f"SELECT key, value FROM agent_state WHERE key IN ({placeholders})",
            tuple(keys),
        ).fetchall()
    finally:
        conn.close()
    return {str(k): str(v) for k, v in rows}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(_db_path())
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
    agents_to_check = [item.strip() for item in raw.split(",") if item.strip()] or ["researcher"]
    agents = {}
    for agent in agents_to_check:
        heartbeat = await redis.get(f"heartbeat:{agent}")
        agents[agent] = "ok" if heartbeat else "down"
    await redis.aclose()
    return {"status": "ok", "agents": agents}


@app.get("/context/current-picture")
async def deprecated_context_current_picture():
    raise HTTPException(status_code=410, detail="Deprecated endpoint. Use /current-picture/latest")


@app.get("/current-picture/latest", response_model=CurrentPictureLatestResponse)
async def current_picture_latest():
    snapshot = _load_latest_snapshot("ui_current_picture")
    if not snapshot:
        raise HTTPException(status_code=404, detail="Current picture is warming up.")

    now = datetime.now(timezone.utc)
    generated_at_raw = str(snapshot.get("generated_at") or "")
    generated_at_dt = _to_dt(generated_at_raw)
    age_seconds = int((now - generated_at_dt).total_seconds()) if generated_at_dt else None
    stale_after = max(300, int(os.environ.get("UI_CURRENT_PICTURE_INTERVAL_SEC", "10800") or "10800"))

    meta = snapshot.get("meta", {}) if isinstance(snapshot.get("meta"), dict) else {}
    state = _load_agent_state(
        [
            "researcher:ui_current_picture:last_attempt_at",
            "researcher:ui_current_picture:last_error",
        ]
    )

    return CurrentPictureLatestResponse(
        generated_at=generated_at_raw,
        content=str(snapshot.get("content") or ""),
        source_generated_at=meta.get("source_generated_at"),
        source_url=meta.get("source_url"),
        model=meta.get("model"),
        age_seconds=age_seconds,
        stale=bool(age_seconds is not None and age_seconds > stale_after),
        last_attempt_at=state.get("researcher:ui_current_picture:last_attempt_at"),
        last_error=state.get("researcher:ui_current_picture:last_error") or None,
    )


if FRONTEND_DIST.exists():
    index_file = FRONTEND_DIST / "index.html"

    @app.get("/")
    async def root():
        return FileResponse(index_file)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)
