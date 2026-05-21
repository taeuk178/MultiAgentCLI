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

-- 외부 문서 원문 (Notion, Slack, PRD, 회의록 등). events 와 분리.
CREATE TABLE IF NOT EXISTS documents (
  id                TEXT PRIMARY KEY,
  project_id        TEXT NOT NULL REFERENCES projects(id),
  source_type       TEXT NOT NULL,            -- notion | slack | prd | meeting | jira | file
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

CREATE INDEX IF NOT EXISTS idx_documents_project_source
  ON documents (project_id, source_type, source_updated_at DESC);

-- 외부 문서에서 파생된 contextualized chunk. 기존 memory_chunks 와 입력원이 달라 분리.
CREATE TABLE IF NOT EXISTS chunks_v2 (
  id                    TEXT PRIMARY KEY,
  project_id            TEXT NOT NULL REFERENCES projects(id),
  document_id           TEXT NOT NULL REFERENCES documents(id),
  chunk_index           INTEGER NOT NULL,
  section_path          TEXT,                 -- 예: "결제 > 테스트모드 > 버튼동작"
  chunk_text            TEXT NOT NULL,        -- 원문 청크
  context_prefix        TEXT,                 -- LLM 생성 1~2 문장 문맥
  retrieval_text        TEXT NOT NULL,        -- context_prefix + '\n' + chunk_text — 임베딩·FTS 모두 이 컬럼 기준
  embedding             BLOB,                 -- 1024 dim float32 (4096 bytes). 검색 시 sqlite-vec extension 가용하면 vec0 에 join.
  raw_chunk_type        TEXT,                 -- decision/fix/todo/error/command/test_result/summary/code_context/note/spec/message/thread
  normalized_chunk_type TEXT,                 -- requirement/decision/discussion/code_note
  source_created_at     TEXT,
  source_updated_at     TEXT,
  valid_from            TEXT,
  valid_to              TEXT,
  is_current            INTEGER NOT NULL DEFAULT 1,
  supersedes_chunk_id   TEXT REFERENCES chunks_v2(id),
  created_at            TEXT NOT NULL,
  metadata_json         TEXT NOT NULL DEFAULT '{}',
  UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_v2_project_doc
  ON chunks_v2 (project_id, document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_current
  ON chunks_v2 (project_id, is_current);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_valid_time
  ON chunks_v2 (project_id, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_section
  ON chunks_v2 (project_id, section_path);
CREATE INDEX IF NOT EXISTS idx_chunks_v2_normalized_type
  ON chunks_v2 (project_id, normalized_chunk_type);

-- retrieval_text 의 BM25 검색용. trigram tokenizer — 한국어 부분 매칭.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_v2_fts USING fts5(
  retrieval_text,
  content='chunks_v2',
  content_rowid='rowid',
  tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS chunks_v2_ai AFTER INSERT ON chunks_v2 BEGIN
  INSERT INTO chunks_v2_fts(rowid, retrieval_text)
  VALUES (new.rowid, new.retrieval_text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_v2_ad AFTER DELETE ON chunks_v2 BEGIN
  INSERT INTO chunks_v2_fts(chunks_v2_fts, rowid, retrieval_text)
  VALUES ('delete', old.rowid, old.retrieval_text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_v2_au AFTER UPDATE ON chunks_v2 BEGIN
  INSERT INTO chunks_v2_fts(chunks_v2_fts, rowid, retrieval_text)
  VALUES ('delete', old.rowid, old.retrieval_text);
  INSERT INTO chunks_v2_fts(rowid, retrieval_text)
  VALUES (new.rowid, new.retrieval_text);
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

-- chunk ↔ entity 다대다 mention link.
CREATE TABLE IF NOT EXISTS chunk_entities (
  chunk_id    TEXT NOT NULL REFERENCES chunks_v2(id),
  entity_id   TEXT NOT NULL REFERENCES entities(id),
  mention     TEXT NOT NULL,                  -- 청크 내 등장한 표현
  confidence  REAL NOT NULL,
  PRIMARY KEY (chunk_id, entity_id, mention)
);

CREATE INDEX IF NOT EXISTS idx_chunk_entities_entity
  ON chunk_entities (entity_id);

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
CREATE TABLE IF NOT EXISTS summaries (
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

CREATE INDEX IF NOT EXISTS idx_summaries_project_level
  ON summaries (project_id, level, is_current);
CREATE INDEX IF NOT EXISTS idx_summaries_target
  ON summaries (target_key);

-- summaries retrieval_text BM25 검색용. trigram tokenizer.
CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts USING fts5(
  retrieval_text,
  content='summaries',
  content_rowid='rowid',
  tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN
  INSERT INTO summaries_fts(rowid, retrieval_text)
  VALUES (new.rowid, new.retrieval_text);
END;

CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries BEGIN
  INSERT INTO summaries_fts(summaries_fts, rowid, retrieval_text)
  VALUES ('delete', old.rowid, old.retrieval_text);
END;

CREATE TRIGGER IF NOT EXISTS summaries_au AFTER UPDATE ON summaries BEGIN
  INSERT INTO summaries_fts(summaries_fts, rowid, retrieval_text)
  VALUES ('delete', old.rowid, old.retrieval_text);
  INSERT INTO summaries_fts(rowid, retrieval_text)
  VALUES (new.rowid, new.retrieval_text);
END;

-- summary 가 어떤 하위 summary / chunk 를 대표하는지 연결. drill-down 근거 추적용.
CREATE TABLE IF NOT EXISTS summary_links (
  parent_summary_id TEXT NOT NULL REFERENCES summaries(id),
  child_kind        TEXT NOT NULL,             -- summary | chunk
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
  chunk_a_id          TEXT NOT NULL REFERENCES chunks_v2(id),
  chunk_b_id          TEXT NOT NULL REFERENCES chunks_v2(id),
  contradiction_score REAL NOT NULL,
  detector            TEXT NOT NULL,           -- nli | llm | rule
  status              TEXT NOT NULL,           -- candidate | neutral | confirmed | dismissed
  reason              TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  UNIQUE (chunk_a_id, chunk_b_id, detector)
);

CREATE INDEX IF NOT EXISTS idx_contradictions_project_status
  ON contradictions (project_id, status);
CREATE INDEX IF NOT EXISTS idx_contradictions_entity
  ON contradictions (entity_id, status);
CREATE INDEX IF NOT EXISTS idx_contradictions_scope
  ON contradictions (project_id, scope_key, status);
