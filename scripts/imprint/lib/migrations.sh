#!/bin/bash
# Imprint DB 마이그레이션 헬퍼.
# session-start.sh에서 호출되며, 실패해도 사용자 세션을 차단하지 않는다.

# FTS5 인덱스가 unicode61(또는 다른 비-trigram) 토크나이저로 빌드되어 있으면
# DROP + REBUILD하여 trigram으로 재구축한다 (D16, AC10).
fts_migrate_to_trigram() {
  local table="$1"; local content_table="$2"; local content_col="$3"
  local sql
  sql=$(sqlite3 "$IMPRINT_DB" \
    "SELECT sql FROM sqlite_master WHERE name='$table' AND type='table';" \
    2>>"$IMPRINT_LOG" || true)

  if [[ -z "$sql" ]]; then
    return 0
  fi
  if printf '%s' "$sql" | grep -qi "tokenize *= *['\"]trigram"; then
    return 0
  fi

  log_info "fts migration: rebuilding $table with trigram tokenizer"
  if ! sqlite3 "$IMPRINT_DB" >/dev/null 2>>"$IMPRINT_LOG" <<SQL
DROP TABLE IF EXISTS $table;
CREATE VIRTUAL TABLE $table USING fts5(
  $content_col,
  content='$content_table',
  content_rowid='rowid',
  tokenize='trigram'
);
INSERT INTO $table($table) VALUES('rebuild');
SQL
  then
    log_error "fts migration failed for $table"
    return 0
  fi
}

run_migrations() {
  if ! command -v sqlite3 >/dev/null 2>&1; then
    return 0
  fi
  fts_migrate_to_trigram events_fts events text_clean
  fts_migrate_to_trigram memory_chunks_fts memory_chunks text
}
