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
  noise           INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_project_created
  ON events (project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_project_noise
  ON events (project_id, noise, created_at DESC);

CREATE TABLE IF NOT EXISTS extract_state (
  project_id      TEXT NOT NULL REFERENCES projects(id),
  session_id      TEXT NOT NULL,
  last_created_at TEXT,
  last_event_id   TEXT,
  last_rolled_at  TEXT,
  PRIMARY KEY (project_id, session_id)
);

-- 과거 advisor skill이 사용했던 provider_runs 테이블은 제거됐다.
-- 기존 사용자 DB에 남아 있는 row는 그대로 두되 새 사용자는 만들지 않는다.

-- 원본 문서 (Notion, Slack, PRD, Plan, ADR, file 등). synthetic memory 문서는 넣지 않는다.
CREATE TABLE IF NOT EXISTS source_documents (
  id                TEXT PRIMARY KEY,
  project_id        TEXT NOT NULL REFERENCES projects(id),
  source_type       TEXT NOT NULL,            -- notion | slack | prd | plan | adr | meeting | jira | file
  source_ref        TEXT NOT NULL,            -- notion page id, slack ts/channel, file path
  title             TEXT,
  author            TEXT,
  source_created_at TEXT,
  source_updated_at TEXT,
  raw_text          TEXT NOT NULL,
  checksum          TEXT NOT NULL,            -- 동일 checksum 이면 re-ingest skip.
  is_deleted        INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE (project_id, source_type, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_source_documents_project_source
  ON source_documents (project_id, source_type, source_updated_at DESC);

-- 검색 가능한 영구 단위의 단일 인덱스.
-- /remember, rollup extract, source_documents chunking 결과가 모두 여기에 들어온다.
-- working overlay는 이 테이블에 저장하지 않고 events.metadata_json에서 검색 시점에 읽는다.
CREATE TABLE IF NOT EXISTS search_entries (
  id                  TEXT PRIMARY KEY,
  project_id          TEXT NOT NULL REFERENCES projects(id),
  source_document_id  TEXT REFERENCES source_documents(id),
  source_event_id     TEXT REFERENCES events(id),
  origin              TEXT NOT NULL DEFAULT 'manual_remember', -- manual_remember | assistant_extract | external_fetch | source_status | source_document
  raw_type            TEXT,                   -- decision/fix/todo/code_context/note/plan_step/requirement/message/thread/command/error/test_result/summary
  normalized_type     TEXT,                   -- requirement/decision/discussion/code_note
  chunk_index         INTEGER,
  section_path        TEXT,
  text                TEXT NOT NULL,
  context_prefix      TEXT,
  retrieval_text      TEXT,
  embedding           BLOB,
  plan_key            TEXT,
  feature_key         TEXT,
  source_created_at   TEXT,
  source_updated_at   TEXT,
  valid_from          TEXT,
  valid_to            TEXT,
  is_current          INTEGER NOT NULL DEFAULT 1,
  supersedes_entry_id TEXT REFERENCES search_entries(id),
  pinned              INTEGER NOT NULL DEFAULT 0,
  metadata_json       TEXT NOT NULL DEFAULT '{}',
  created_at          TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_search_entries_source_doc_chunk
  ON search_entries (source_document_id, chunk_index)
  WHERE source_document_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_search_entries_project_doc
  ON search_entries (project_id, source_document_id);
CREATE INDEX IF NOT EXISTS idx_search_entries_current
  ON search_entries (project_id, is_current);
CREATE INDEX IF NOT EXISTS idx_search_entries_valid_time
  ON search_entries (project_id, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_search_entries_section
  ON search_entries (project_id, section_path);
CREATE INDEX IF NOT EXISTS idx_search_entries_normalized_type
  ON search_entries (project_id, normalized_type);
CREATE INDEX IF NOT EXISTS idx_search_entries_origin
  ON search_entries (project_id, origin);
CREATE INDEX IF NOT EXISTS idx_search_entries_pinned_created
  ON search_entries (project_id, pinned DESC, created_at DESC);

-- retrieval_text 의 BM25 검색용. trigram tokenizer — 한국어 부분 매칭.
CREATE VIRTUAL TABLE IF NOT EXISTS search_entries_fts USING fts5(
  retrieval_text,
  content='search_entries',
  content_rowid='rowid',
  tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS search_entries_ai AFTER INSERT ON search_entries BEGIN
  INSERT INTO search_entries_fts(rowid, retrieval_text)
  VALUES (new.rowid, COALESCE(NULLIF(new.retrieval_text, ''), new.text));
END;

CREATE TRIGGER IF NOT EXISTS search_entries_ad AFTER DELETE ON search_entries BEGIN
  INSERT INTO search_entries_fts(search_entries_fts, rowid, retrieval_text)
  VALUES ('delete', old.rowid, COALESCE(NULLIF(old.retrieval_text, ''), old.text));
END;

CREATE TRIGGER IF NOT EXISTS search_entries_au AFTER UPDATE ON search_entries BEGIN
  INSERT INTO search_entries_fts(search_entries_fts, rowid, retrieval_text)
  VALUES ('delete', old.rowid, COALESCE(NULLIF(old.retrieval_text, ''), old.text));
  INSERT INTO search_entries_fts(rowid, retrieval_text)
  VALUES (new.rowid, COALESCE(NULLIF(new.retrieval_text, ''), new.text));
END;

-- canonical entity. 같은 UI 요소·feature 를 여러 표현으로 가리키는 alias 들의 결착점.
CREATE TABLE IF NOT EXISTS entities (
  id              TEXT PRIMARY KEY,
  project_id      TEXT NOT NULL REFERENCES projects(id),
  entity_type     TEXT NOT NULL,              -- ui_element | screen | feature | api | state | experiment_flag
  canonical_name  TEXT NOT NULL,              -- "test_button"
  display_name    TEXT NOT NULL,              -- "Test 버튼"
  created_at      TEXT NOT NULL,
  UNIQUE (project_id, entity_type, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_entities_project_type
  ON entities (project_id, entity_type);

-- entity 별 alias 표현. status 로 review queue 흡수.
CREATE TABLE IF NOT EXISTS entity_aliases (
  id               TEXT PRIMARY KEY,
  entity_id        TEXT NOT NULL REFERENCES entities(id),
  alias            TEXT NOT NULL,              -- 원문 그대로
  normalized_alias TEXT NOT NULL,              -- 소문자 + 공백 trim + 특수문자 제거
  status           TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | rejected
  confidence       REAL NOT NULL DEFAULT 1.0,
  created_at       TEXT NOT NULL,
  UNIQUE (entity_id, normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_norm
  ON entity_aliases (normalized_alias);
CREATE INDEX IF NOT EXISTS idx_entity_aliases_status
  ON entity_aliases (status);

-- search_entry ↔ entity 다대다 mention link.
CREATE TABLE IF NOT EXISTS entry_entities (
  entry_id    TEXT NOT NULL REFERENCES search_entries(id),
  entity_id   TEXT NOT NULL REFERENCES entities(id),
  mention     TEXT NOT NULL,                  -- entry 내 등장한 표현
  confidence  REAL NOT NULL,
  PRIMARY KEY (entry_id, entity_id, mention)
);

CREATE INDEX IF NOT EXISTS idx_entry_entities_entity
  ON entry_entities (entity_id);

-- append-only ingest queue. polling worker 가 status 와 priority 로 drain.
-- priority: 낮을수록 먼저 처리 (1=높음, 5=중간, 9=낮음). J2/J1=1, J5/J6=5, J4/J3=9.
CREATE TABLE IF NOT EXISTS ingest_queue (
  id            TEXT PRIMARY KEY,
  project_id    TEXT NOT NULL REFERENCES projects(id),
  payload_json  TEXT NOT NULL,                -- {kind: chunk|alias|version|summary|contradiction, ...}
  status        TEXT NOT NULL DEFAULT 'pending',  -- pending | claimed | done | failed
  priority      INTEGER NOT NULL DEFAULT 5,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error    TEXT,
  created_at    TEXT NOT NULL,
  claimed_at    TEXT,
  completed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingest_queue_status_priority
  ON ingest_queue (status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_ingest_queue_project
  ON ingest_queue (project_id, status);

-- feature / document / project 단위 계층 요약. retrieval 라우팅이 질문 해상도에
-- 맞춰 이 테이블을 검색.
CREATE TABLE IF NOT EXISTS search_summaries (
  id                    TEXT PRIMARY KEY,
  project_id            TEXT NOT NULL REFERENCES projects(id),
  level                 TEXT NOT NULL,         -- feature | document | project
  target_key            TEXT NOT NULL,         -- feature:<key> | document:<id> | project:<id>
  title                 TEXT,
  summary_text          TEXT NOT NULL,         -- 사용자에게 보여줄 본문
  retrieval_text        TEXT NOT NULL,         -- 검색용 텍스트 (context prefix 포함)
  embedding             BLOB,                  -- 1024 dim float32
  source_chunk_count    INTEGER NOT NULL DEFAULT 0,
  source_summary_count  INTEGER NOT NULL DEFAULT 0,
  valid_from            TEXT,
  valid_to              TEXT,
  is_current            INTEGER NOT NULL DEFAULT 1,
  generator             TEXT,                  -- llm | deterministic — 누가 만들었는지 추적
  updated_at            TEXT NOT NULL,
  UNIQUE (project_id, level, target_key, is_current)
);

CREATE INDEX IF NOT EXISTS idx_search_summaries_project_level
  ON search_summaries (project_id, level, is_current);
CREATE INDEX IF NOT EXISTS idx_search_summaries_target
  ON search_summaries (target_key);

-- summaries retrieval_text BM25 검색용. trigram tokenizer.
CREATE VIRTUAL TABLE IF NOT EXISTS search_summaries_fts USING fts5(
  retrieval_text,
  content='search_summaries',
  content_rowid='rowid',
  tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS search_summaries_ai AFTER INSERT ON search_summaries BEGIN
  INSERT INTO search_summaries_fts(rowid, retrieval_text)
  VALUES (new.rowid, new.retrieval_text);
END;

CREATE TRIGGER IF NOT EXISTS search_summaries_ad AFTER DELETE ON search_summaries BEGIN
  INSERT INTO search_summaries_fts(search_summaries_fts, rowid, retrieval_text)
  VALUES ('delete', old.rowid, old.retrieval_text);
END;

CREATE TRIGGER IF NOT EXISTS search_summaries_au AFTER UPDATE ON search_summaries BEGIN
  INSERT INTO search_summaries_fts(search_summaries_fts, rowid, retrieval_text)
  VALUES ('delete', old.rowid, old.retrieval_text);
  INSERT INTO search_summaries_fts(rowid, retrieval_text)
  VALUES (new.rowid, new.retrieval_text);
END;

-- summary 가 어떤 하위 summary / entry 를 대표하는지 연결. drill-down 근거 추적용.
CREATE TABLE IF NOT EXISTS summary_links (
  parent_summary_id TEXT NOT NULL REFERENCES search_summaries(id),
  child_kind        TEXT NOT NULL,             -- summary | entry
  child_id          TEXT NOT NULL,
  rank_order        INTEGER NOT NULL DEFAULT 0,
  weight            REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (parent_summary_id, child_kind, child_id)
);

CREATE INDEX IF NOT EXISTS idx_summary_links_child
  ON summary_links (child_kind, child_id);
CREATE INDEX IF NOT EXISTS idx_summary_links_parent_rank
  ON summary_links (parent_summary_id, rank_order);

-- contradiction 결과 캐시. query 시 매번 chunk 쌍을 다시 비교하지 않기 위해 저장.
CREATE TABLE IF NOT EXISTS contradictions (
  id                  TEXT PRIMARY KEY,
  project_id          TEXT NOT NULL REFERENCES projects(id),
  entity_id           TEXT REFERENCES entities(id),
  scope_key           TEXT,                    -- feature key 또는 section_path
  entry_a_id          TEXT NOT NULL REFERENCES search_entries(id),
  entry_b_id          TEXT NOT NULL REFERENCES search_entries(id),
  contradiction_score REAL NOT NULL,
  detector            TEXT NOT NULL,           -- nli | llm | rule
  status              TEXT NOT NULL,           -- candidate | neutral | confirmed | dismissed
  reason              TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  UNIQUE (entry_a_id, entry_b_id, detector)
);

CREATE INDEX IF NOT EXISTS idx_contradictions_project_status
  ON contradictions (project_id, status);
CREATE INDEX IF NOT EXISTS idx_contradictions_entity
  ON contradictions (entity_id, status);
CREATE INDEX IF NOT EXISTS idx_contradictions_scope
  ON contradictions (project_id, scope_key, status);
