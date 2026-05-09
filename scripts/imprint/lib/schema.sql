-- Imprint plugin SQLite schema.
-- Applied idempotently on every session start.

PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
  id          TEXT PRIMARY KEY,
  root_path   TEXT NOT NULL UNIQUE,
  name        TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id          TEXT PRIMARY KEY,
  project_id  TEXT NOT NULL REFERENCES projects(id),
  source      TEXT NOT NULL,
  title       TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id              TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL REFERENCES projects(id),
  conversation_id TEXT REFERENCES conversations(id),
  source          TEXT NOT NULL,
  kind            TEXT NOT NULL,
  text_clean      TEXT NOT NULL,
  metadata_json   TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_project_created
  ON events (project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memory_chunks (
  id              TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL REFERENCES projects(id),
  source_event_id TEXT REFERENCES events(id),
  chunk_type      TEXT NOT NULL,
  text            TEXT NOT NULL,
  metadata_json   TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL,
  pinned          INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_project_pinned_created
  ON memory_chunks (project_id, pinned DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chunks_type
  ON memory_chunks (project_id, chunk_type);

CREATE TABLE IF NOT EXISTS provider_runs (
  id                TEXT PRIMARY KEY,
  conversation_id   TEXT REFERENCES conversations(id),
  project_id        TEXT NOT NULL REFERENCES projects(id),
  provider          TEXT NOT NULL,
  phase             TEXT NOT NULL,
  prompt_event_id   TEXT REFERENCES events(id),
  output_event_id   TEXT REFERENCES events(id),
  status            TEXT NOT NULL,
  started_at        TEXT NOT NULL,
  finished_at       TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
  text_clean,
  content='events',
  content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts USING fts5(
  text,
  content='memory_chunks',
  content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
  INSERT INTO events_fts(rowid, text_clean) VALUES (new.rowid, new.text_clean);
END;

CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
  INSERT INTO events_fts(events_fts, rowid, text_clean) VALUES ('delete', old.rowid, old.text_clean);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON memory_chunks BEGIN
  INSERT INTO memory_chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON memory_chunks BEGIN
  INSERT INTO memory_chunks_fts(memory_chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON memory_chunks BEGIN
  INSERT INTO memory_chunks_fts(memory_chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
  INSERT INTO memory_chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;
