import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from agents.researcher.context_sources import ContextDocumentCandidate


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _safe_json_loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return default


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class ContextMemoryStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def insert_document(self, candidate: ContextDocumentCandidate) -> tuple[bool, str]:
        content_hash = _content_hash(candidate.body)
        meta = dict(candidate.meta or {})
        meta.setdefault("content_hash", content_hash)

        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM context_documents WHERE canonical_url=? AND content_hash=? LIMIT 1",
                (candidate.canonical_url, content_hash),
            ).fetchone()
            if existing:
                return False, str(existing[0])

            doc_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO context_documents (
                    id, provider, doc_kind, cycle, coverage_date, title,
                    canonical_url, published_at, fetched_at, content_hash, body, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    candidate.provider,
                    candidate.doc_kind,
                    candidate.cycle,
                    candidate.coverage_date,
                    candidate.title,
                    candidate.canonical_url,
                    candidate.published_at,
                    candidate.fetched_at,
                    content_hash,
                    candidate.body,
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
            conn.commit()
            return True, doc_id
        finally:
            conn.close()

    def latest_document(
        self,
        provider: str,
        doc_kind: str,
        cycle: str | None = None,
    ) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            if cycle is None:
                row = conn.execute(
                    """
                    SELECT *
                    FROM context_documents
                    WHERE provider=? AND doc_kind=?
                    ORDER BY COALESCE(published_at, fetched_at) DESC
                    LIMIT 1
                    """,
                    (provider, doc_kind),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT *
                    FROM context_documents
                    WHERE provider=? AND doc_kind=? AND cycle=?
                    ORDER BY COALESCE(published_at, fetched_at) DESC
                    LIMIT 1
                    """,
                    (provider, doc_kind, cycle),
                ).fetchone()
            return self._row_to_doc(row)
        finally:
            conn.close()

    def latest_documents(
        self,
        provider: str | None = None,
        doc_kind: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        conn = self._connect()
        try:
            clauses = []
            params: list[Any] = []
            if provider:
                clauses.append("provider=?")
                params.append(provider)
            if doc_kind:
                clauses.append("doc_kind=?")
                params.append(doc_kind)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

            rows = conn.execute(
                f"""
                SELECT *
                FROM context_documents
                {where}
                ORDER BY COALESCE(published_at, fetched_at) DESC
                LIMIT ?
                """,
                (*params, safe_limit),
            ).fetchall()
            return [self._row_to_doc(row) for row in rows]
        finally:
            conn.close()

    def get_documents_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        keys = [item for item in ids if item]
        if not keys:
            return []

        placeholders = ",".join("?" for _ in keys)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT *
                FROM context_documents
                WHERE id IN ({placeholders})
                """,
                tuple(keys),
            ).fetchall()
            by_id = {str(row["id"]): self._row_to_doc(row) for row in rows}
            return [by_id[item] for item in keys if item in by_id]
        finally:
            conn.close()

    def get_latest_snapshot(self, snapshot_type: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM context_snapshots
                WHERE snapshot_type=?
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (snapshot_type,),
            ).fetchone()
            return self._row_to_snapshot(row)
        finally:
            conn.close()

    def save_snapshot(
        self,
        snapshot_type: str,
        content: str,
        source_doc_ids: list[str],
        meta: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        content_hash = _content_hash(content)
        meta = dict(meta or {})

        latest = self.get_latest_snapshot(snapshot_type)
        if latest and latest.get("content_hash") == content_hash:
            return False, str(latest.get("id"))

        snap_id = str(uuid4())
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO context_snapshots (
                    id, snapshot_type, generated_at, content, content_hash, source_doc_ids, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap_id,
                    snapshot_type,
                    _utc_now_iso(),
                    content,
                    content_hash,
                    json.dumps(source_doc_ids, ensure_ascii=False),
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
            conn.commit()
            return True, snap_id
        finally:
            conn.close()

    def select_current_picture_sources(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
        updates = self.latest_documents(provider="critical_threats", doc_kind="iran_update", limit=30)
        if not updates:
            return None, None, None

        sorted_updates = sorted(updates, key=self._doc_sort_key, reverse=True)
        primary = sorted_updates[0]

        primary_cycle = str(primary.get("cycle") or "")
        primary_dt = _parse_dt(primary.get("published_at") or primary.get("fetched_at"))
        primary_day = self._doc_day(primary)

        secondary = None
        if primary_cycle == "evening":
            for doc in sorted_updates:
                if str(doc.get("cycle") or "") != "morning":
                    continue
                if self._doc_day(doc) == primary_day:
                    secondary = doc
                    break
        elif primary_cycle == "morning" and primary_dt is not None:
            floor = primary_dt - timedelta(hours=36)
            for doc in sorted_updates:
                if str(doc.get("cycle") or "") != "evening":
                    continue
                doc_dt = _parse_dt(doc.get("published_at") or doc.get("fetched_at"))
                if doc_dt is None:
                    continue
                if floor <= doc_dt < primary_dt:
                    secondary = doc
                    break

        briefing = self.latest_document(provider="iran_monitor", doc_kind="daily_briefing")
        if briefing is not None:
            briefing_dt = _parse_dt(briefing.get("published_at") or briefing.get("fetched_at"))
            if briefing_dt is None or (datetime.now(timezone.utc) - briefing_dt) > timedelta(hours=24):
                briefing = None

        return primary, secondary, briefing

    def document_age_seconds(self, provider: str, doc_kind: str) -> int | None:
        doc = self.latest_document(provider=provider, doc_kind=doc_kind)
        if not doc:
            return None
        dt = _parse_dt(doc.get("published_at") or doc.get("fetched_at"))
        if dt is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))

    @staticmethod
    def _doc_day(doc: dict[str, Any]) -> str | None:
        coverage = doc.get("coverage_date")
        if coverage:
            return str(coverage)
        dt = _parse_dt(doc.get("published_at") or doc.get("fetched_at"))
        return dt.date().isoformat() if dt else None

    @staticmethod
    def _doc_sort_key(doc: dict[str, Any]) -> tuple[datetime, int, datetime]:
        published = _parse_dt(doc.get("published_at") or doc.get("fetched_at"))
        published = published or datetime(1970, 1, 1, tzinfo=timezone.utc)

        coverage_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
        coverage = doc.get("coverage_date")
        if coverage:
            try:
                coverage_dt = datetime.fromisoformat(str(coverage)).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        domain_rank = 1 if "criticalthreats.org" in str(doc.get("canonical_url") or "") else 0
        return published, domain_rank, coverage_dt

    @staticmethod
    def _row_to_doc(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        meta = _safe_json_loads(row["meta_json"], {})
        return {
            "id": str(row["id"]),
            "provider": row["provider"],
            "doc_kind": row["doc_kind"],
            "cycle": row["cycle"],
            "coverage_date": row["coverage_date"],
            "title": row["title"],
            "canonical_url": row["canonical_url"],
            "published_at": row["published_at"],
            "fetched_at": row["fetched_at"],
            "content_hash": row["content_hash"],
            "body": row["body"],
            "meta": meta,
        }

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        meta = _safe_json_loads(row["meta_json"], {})
        source_doc_ids = _safe_json_loads(row["source_doc_ids"], [])
        return {
            "id": str(row["id"]),
            "snapshot_type": row["snapshot_type"],
            "generated_at": row["generated_at"],
            "content": row["content"],
            "content_hash": row["content_hash"],
            "source_doc_ids": source_doc_ids,
            "meta": meta,
        }


def render_analysis_context(
    structural_context: str,
    current_picture: str,
    stream_deltas: list[dict[str, Any]],
    prior_posts: list[dict[str, Any]],
) -> str:
    delta_lines = []
    for item in stream_deltas:
        delta_lines.append(
            f"- [{item.get('timestamp', '')}] [{str(item.get('significance', '')).upper()}] "
            f"[{item.get('platform', '')}/{item.get('outlet', '')}] "
            f"{item.get('headline', '')} | {item.get('why', '')} | {item.get('url', '')}"
        )

    post_lines = [
        f"- {p.get('timestamp', '')[:10]} | {p.get('title', '')}: {str(p.get('content', ''))[:260]}"
        for p in prior_posts
    ]

    return (
        "Structural Context:\n"
        f"{(structural_context or '(missing structural context)').strip()}\n\n"
        "Current Picture:\n"
        f"{(current_picture or '(missing current picture)').strip()}\n\n"
        "Latest High-Signal Deltas:\n"
        f"{chr(10).join(delta_lines) if delta_lines else '(none)'}\n\n"
        "Relevant Prior Posts:\n"
        f"{chr(10).join(post_lines) if post_lines else '(none)'}"
    )
