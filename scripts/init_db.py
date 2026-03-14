import os
import sqlite3
from pathlib import Path


def _resolve_db_path(path: str | None = None) -> str:
    if path:
        return path

    preferred = Path("/memory/posts.db")
    if preferred.parent.exists():
        return str(preferred)

    local = Path("memory/posts.db")
    local.parent.mkdir(parents=True, exist_ok=True)
    return str(local)


def init(path: str | None = None) -> str:
    db_path = _resolve_db_path(path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            supersedes TEXT,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            claim_map_json TEXT NOT NULL DEFAULT '[]',
            freshness_meta TEXT NOT NULL DEFAULT '{}',
            quality_flags TEXT NOT NULL DEFAULT '[]'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
            title,
            content,
            content='posts',
            content_rowid='rowid'
        );

        CREATE TRIGGER IF NOT EXISTS posts_ai
        AFTER INSERT ON posts BEGIN
            INSERT INTO posts_fts(rowid, title, content)
            VALUES (new.rowid, new.title, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS posts_ad
        AFTER DELETE ON posts BEGIN
            INSERT INTO posts_fts(posts_fts, rowid, title, content)
            VALUES ('delete', old.rowid, old.title, old.content);
        END;

        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            added_at TEXT NOT NULL,
            priority_score REAL DEFAULT 0.5,
            last_scored TEXT,
            answered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS observatory_events (
            seq INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            agent TEXT NOT NULL,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            preview TEXT,
            detail TEXT,
            significance TEXT,
            has_detail INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_observatory_events_timestamp
        ON observatory_events(timestamp);

        CREATE TABLE IF NOT EXISTS agent_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS context_documents (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            doc_kind TEXT NOT NULL,
            cycle TEXT,
            coverage_date TEXT,
            title TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            body TEXT NOT NULL,
            meta_json TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_context_documents_url_hash
        ON context_documents(canonical_url, content_hash);

        CREATE INDEX IF NOT EXISTS idx_context_documents_lookup
        ON context_documents(provider, doc_kind, published_at DESC, fetched_at DESC);

        CREATE TABLE IF NOT EXISTS context_snapshots (
            id TEXT PRIMARY KEY,
            snapshot_type TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            source_doc_ids TEXT NOT NULL,
            meta_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_context_snapshots_type_time
        ON context_snapshots(snapshot_type, generated_at DESC);
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()}
    if "evidence_refs" not in columns:
        conn.execute("ALTER TABLE posts ADD COLUMN evidence_refs TEXT NOT NULL DEFAULT '[]'")
    if "claim_map_json" not in columns:
        conn.execute("ALTER TABLE posts ADD COLUMN claim_map_json TEXT NOT NULL DEFAULT '[]'")
    if "freshness_meta" not in columns:
        conn.execute("ALTER TABLE posts ADD COLUMN freshness_meta TEXT NOT NULL DEFAULT '{}'")
    if "quality_flags" not in columns:
        conn.execute("ALTER TABLE posts ADD COLUMN quality_flags TEXT NOT NULL DEFAULT '[]'")
    conn.execute("UPDATE posts SET evidence_refs='[]' WHERE evidence_refs IS NULL")
    conn.execute("UPDATE posts SET claim_map_json='[]' WHERE claim_map_json IS NULL")
    conn.execute("UPDATE posts SET freshness_meta='{}' WHERE freshness_meta IS NULL")
    conn.execute("UPDATE posts SET quality_flags='[]' WHERE quality_flags IS NULL")
    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    location = init()
    print(f"DB initialized at {location}")
