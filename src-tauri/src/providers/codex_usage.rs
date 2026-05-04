use std::fs;
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use super::util::iso8601::parse_iso_timestamp_millis;
use super::util::json::{json_number, json_percent};
use super::util::jsonl::collect_jsonl_files;
use super::RuntimeUsage;

pub fn read_codex_usage() -> RuntimeUsage {
    let now = SystemTime::now();
    let status = read_latest_codex_token_status();
    let five_hour_reset_seconds = status
        .as_ref()
        .and_then(|status| status.five_hour_resets_at)
        .and_then(|reset_at| reset_at.duration_since(now).ok())
        .map(|duration| duration.as_secs());

    RuntimeUsage {
        context_used_percent: status
            .as_ref()
            .and_then(|status| status.context_used_percent),
        five_hour_percent: status.and_then(|status| status.five_hour_remaining_percent),
        five_hour_reset_seconds,
    }
}

fn read_latest_codex_token_status() -> Option<CodexTokenStatus> {
    let now = SystemTime::now();
    let cutoff = now.checked_sub(Duration::from_secs(5 * 60 * 60))?;
    let home = std::env::var("HOME").ok()?;
    let sessions_dir = PathBuf::from(home).join(".codex/sessions");
    let mut files = Vec::new();
    collect_jsonl_files(&sessions_dir, &mut files, cutoff, 0);

    files
        .iter()
        .filter_map(|path| fs::read_to_string(path).ok())
        .flat_map(|raw| {
            raw.lines()
                .filter_map(codex_token_count_from_line)
                .collect::<Vec<_>>()
        })
        .max_by_key(|status| status.timestamp)
}

struct CodexTokenStatus {
    timestamp: SystemTime,
    context_used_percent: Option<u8>,
    five_hour_remaining_percent: Option<u8>,
    five_hour_resets_at: Option<SystemTime>,
}

fn codex_token_count_from_line(line: &str) -> Option<CodexTokenStatus> {
    let json = serde_json::from_str::<serde_json::Value>(line).ok()?;
    let timestamp = json
        .get("timestamp")
        .and_then(|value| value.as_str())
        .and_then(parse_iso_timestamp_millis)?;
    let payload = json.get("payload")?;
    if payload.get("type").and_then(|value| value.as_str()) != Some("token_count") {
        return None;
    }

    let context_used_percent = payload.get("info").and_then(|info| {
        let context_window = json_number(info, "model_context_window");
        let usage = info.get("last_token_usage")?;
        let tokens = json_number(usage, "total_tokens")
            .max(json_number(usage, "input_tokens") + json_number(usage, "output_tokens"));
        if context_window == 0 || tokens == 0 {
            return None;
        }

        let percent = (tokens as f64 / context_window as f64) * 100.0;
        Some(percent.round().clamp(0.0, 100.0) as u8)
    });

    let primary = payload
        .get("rate_limits")
        .and_then(|rate_limits| rate_limits.get("primary"));
    let used_percent = primary
        .and_then(|primary| primary.get("used_percent"))
        .and_then(json_percent);
    let five_hour_remaining_percent = used_percent.map(|used| 100_u8.saturating_sub(used));
    let five_hour_resets_at = primary
        .and_then(|primary| primary.get("resets_at"))
        .and_then(|value| value.as_u64())
        .and_then(|seconds| UNIX_EPOCH.checked_add(Duration::from_secs(seconds)));

    Some(CodexTokenStatus {
        timestamp,
        context_used_percent,
        five_hour_remaining_percent,
        five_hour_resets_at,
    })
}
