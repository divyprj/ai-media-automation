"""Database DDL schemas and initialization utilities."""

import sqlite3

SCHEMA_DDL = """
-- Monitored content feeds configuration
CREATE TABLE IF NOT EXISTS feeds (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_polled_at TEXT,
    poll_interval_sec INTEGER NOT NULL DEFAULT 900
);

-- Ingested raw discovery items from feeds
CREATE TABLE IF NOT EXISTS discovered_items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content_hash TEXT UNIQUE NOT NULL,
    raw_metadata TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    is_verified INTEGER NOT NULL DEFAULT 0,
    verification_score REAL NOT NULL DEFAULT 0.0,
    verification_notes TEXT
);

-- Platform-adapted generated posts and media
CREATE TABLE IF NOT EXISTS generated_posts (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES discovered_items(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    text TEXT NOT NULL,
    character_count INTEGER NOT NULL,
    has_em_dash INTEGER NOT NULL DEFAULT 0,
    visual_path TEXT,
    attribution_url TEXT NOT NULL,
    is_sensitive INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Publication queue state machine
CREATE TABLE IF NOT EXISTS publish_queue (
    job_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES discovered_items(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    scheduled_for TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

-- Immutable audit logs for safety and operation tracking
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    details TEXT NOT NULL
);

-- Indexes for performance and uniqueness queries
CREATE INDEX IF NOT EXISTS idx_discovered_items_hash ON discovered_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_discovered_items_discovered_at ON discovered_items(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_queue_status_sched ON publish_queue(status, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_publish_queue_item ON publish_queue(item_id);
CREATE INDEX IF NOT EXISTS idx_generated_posts_item ON generated_posts(item_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize database tables and indexes using the schema DDL.

    Args:
        conn: Open SQLite connection.
    """
    conn.executescript(SCHEMA_DDL)
    conn.commit()
