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

-- 과거 advisor skill이 사용했던 provider_runs 테이블은 제거됐다.
-- 기존 사용자 DB에 남아 있는 row는 그대로 두되 새 사용자는 만들지 않는다.

-- FTS5 인덱스: 한국어 부분문자열 매칭(예: '더스트' → '더스트가/더스트의')을
-- 위해 trigram tokenizer 사용. unicode61 기반 기존 인덱스가 남아 있으면
-- session-start.sh에서 DROP + REBUILD 마이그레이션을 수행한다 (D16, AC10).
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
  text_clean,
  content='events',
  content_rowid='rowid',
  tokenize='trigram'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts USING fts5(
  text,
  content='memory_chunks',
  content_rowid='rowid',
  tokenize='trigram'
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
