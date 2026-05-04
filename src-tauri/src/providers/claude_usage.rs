use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use super::util::curl::{curl_config, form_encode, run_curl_config};
use super::util::iso8601::parse_iso_timestamp_millis;
use super::util::json::{
    find_percent_by_keys, find_seconds_by_keys, json_number, json_percent, parse_percent,
};
use super::util::jsonl::collect_jsonl_files;
use super::RuntimeUsage;

pub fn read_claude_usage() -> RuntimeUsage {
    let from_env =
        read_percent_env(["CLAUDE_5H_CONTEXT_PERCENT", "CLAUDE_5H_USAGE_PERCENT"]).map(|percent| {
            RuntimeUsage {
                context_used_percent: read_claude_context_used_percent(),
                five_hour_percent: Some(percent),
                five_hour_reset_seconds: read_seconds_env(["CLAUDE_5H_RESET_SECONDS"]),
            }
        });

    from_env
        .or_else(read_claude_oauth_usage)
        .or_else(read_claude_auth_status_usage)
        .or_else(read_claude_log_usage)
        .unwrap_or_else(|| RuntimeUsage {
            context_used_percent: read_claude_context_used_percent(),
            five_hour_percent: None,
            five_hour_reset_seconds: None,
        })
}

fn read_percent_env<const N: usize>(names: [&str; N]) -> Option<u8> {
    names.into_iter().find_map(|name| {
        let value = std::env::var(name).ok()?;
        parse_percent(&value)
    })
}

fn read_seconds_env<const N: usize>(names: [&str; N]) -> Option<u64> {
    names
        .into_iter()
        .find_map(|name| std::env::var(name).ok()?.trim().parse::<u64>().ok())
}

struct ClaudeOAuthCredentials {
    access_token: String,
    expires_at: Option<u64>,
    refresh_token: Option<String>,
}

fn read_claude_oauth_usage() -> Option<RuntimeUsage> {
    let mut credentials = read_claude_oauth_credentials()?;
    if claude_oauth_credentials_expired(&credentials) {
        let refresh_token = credentials.refresh_token.as_deref()?;
        credentials.access_token = refresh_claude_access_token(refresh_token)?;
    }

    let response = fetch_claude_oauth_usage(&credentials.access_token)?;
    let five_hour = response.get("five_hour")?;
    let percent = five_hour.get("utilization").and_then(json_percent)?;
    let reset_seconds = five_hour
        .get("resets_at")
        .and_then(|value| value.as_str())
        .and_then(parse_iso_timestamp_millis)
        .and_then(|reset_at| reset_at.duration_since(SystemTime::now()).ok())
        .map(|duration| duration.as_secs());

    Some(RuntimeUsage {
        context_used_percent: read_claude_context_used_percent(),
        five_hour_percent: Some(percent),
        five_hour_reset_seconds: reset_seconds,
    })
}

fn read_claude_oauth_credentials() -> Option<ClaudeOAuthCredentials> {
    read_claude_keychain_credentials().or_else(read_claude_file_credentials)
}

fn read_claude_keychain_credentials() -> Option<ClaudeOAuthCredentials> {
    if cfg!(not(target_os = "macos")) {
        return None;
    }

    let service_name = claude_keychain_service_name();
    let user = std::env::var("USER").ok().filter(|value| !value.is_empty());
    let mut candidates = Vec::new();
    if let Some(user) = user {
        candidates.push(Some(user));
    }
    candidates.push(None);

    candidates.into_iter().find_map(|account| {
        let mut command = Command::new("/usr/bin/security");
        command
            .arg("find-generic-password")
            .arg("-s")
            .arg(&service_name);
        if let Some(account) = account {
            command.arg("-a").arg(account);
        }
        let output = command.arg("-w").output().ok()?;
        if !output.status.success() {
            return None;
        }

        let raw = String::from_utf8_lossy(&output.stdout);
        claude_oauth_credentials_from_json(raw.trim())
    })
}

fn claude_keychain_service_name() -> String {
    if let Ok(config_dir) = std::env::var("CLAUDE_CONFIG_DIR") {
        if !config_dir.is_empty() {
            if let Some(hash) = sha256_prefix_with_shasum(&config_dir) {
                return format!("Claude Code-credentials-{hash}");
            }
        }
    }

    "Claude Code-credentials".to_string()
}

fn sha256_prefix_with_shasum(value: &str) -> Option<String> {
    let mut child = Command::new("shasum")
        .arg("-a")
        .arg("256")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    child.stdin.as_mut()?.write_all(value.as_bytes()).ok()?;
    let output = child.wait_with_output().ok()?;
    if !output.status.success() {
        return None;
    }

    let digest = String::from_utf8_lossy(&output.stdout);
    digest
        .split_whitespace()
        .next()
        .filter(|value| value.len() >= 8)
        .map(|value| value[..8].to_string())
}

fn read_claude_file_credentials() -> Option<ClaudeOAuthCredentials> {
    let raw = fs::read_to_string(claude_config_dir().join(".credentials.json")).ok()?;
    claude_oauth_credentials_from_json(&raw)
}

fn claude_config_dir() -> PathBuf {
    std::env::var("CLAUDE_CONFIG_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".claude")
        })
}

fn claude_oauth_credentials_from_json(raw: &str) -> Option<ClaudeOAuthCredentials> {
    let json = serde_json::from_str::<serde_json::Value>(raw).ok()?;
    let credentials = json.get("claudeAiOauth").unwrap_or(&json);
    let access_token = credentials
        .get("accessToken")
        .and_then(|value| value.as_str())
        .filter(|value| !value.is_empty())?
        .to_string();

    Some(ClaudeOAuthCredentials {
        access_token,
        expires_at: credentials
            .get("expiresAt")
            .and_then(|value| value.as_u64()),
        refresh_token: credentials
            .get("refreshToken")
            .and_then(|value| value.as_str())
            .filter(|value| !value.is_empty())
            .map(ToString::to_string),
    })
}

fn claude_oauth_credentials_expired(credentials: &ClaudeOAuthCredentials) -> bool {
    let Some(expires_at) = credentials.expires_at else {
        return false;
    };

    expires_at <= current_unix_millis()
}

fn current_unix_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}

fn refresh_claude_access_token(refresh_token: &str) -> Option<String> {
    let client_id = std::env::var("CLAUDE_CODE_OAUTH_CLIENT_ID")
        .unwrap_or_else(|_| "9d1c250a-e61b-44d9-88ed-5944d1962f5e".to_string());
    let body = format!(
        "grant_type=refresh_token&refresh_token={}&client_id={}",
        form_encode(refresh_token),
        form_encode(&client_id)
    );
    let config = curl_config(
        "https://platform.claude.com/v1/oauth/token",
        &[
            "Content-Type: application/x-www-form-urlencoded".to_string(),
            format!("Content-Length: {}", body.len()),
        ],
        Some(&body),
    );
    let json = run_curl_config(&config)?;

    serde_json::from_str::<serde_json::Value>(&json)
        .ok()?
        .get("access_token")
        .and_then(|value| value.as_str())
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
}

fn fetch_claude_oauth_usage(access_token: &str) -> Option<serde_json::Value> {
    let config = curl_config(
        "https://api.anthropic.com/api/oauth/usage",
        &[
            format!("Authorization: Bearer {access_token}"),
            "anthropic-beta: oauth-2025-04-20".to_string(),
            "Content-Type: application/json".to_string(),
        ],
        None,
    );
    let raw = run_curl_config(&config)?;
    serde_json::from_str(&raw).ok()
}

fn read_claude_auth_status_usage() -> Option<RuntimeUsage> {
    let output = Command::new("claude")
        .arg("auth")
        .arg("status")
        .output()
        .ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let json = serde_json::from_str::<serde_json::Value>(&stdout).ok()?;

    let percent = find_percent_by_keys(
        &json,
        &[
            "fiveHourContextPercent",
            "fiveHourUsagePercent",
            "fiveHourLimitPercent",
            "fiveHourPercent",
            "usagePercent",
            "percentUsed",
        ],
    )?;

    Some(RuntimeUsage {
        context_used_percent: read_claude_context_used_percent(),
        five_hour_percent: Some(percent),
        five_hour_reset_seconds: find_seconds_by_keys(
            &json,
            &[
                "fiveHourResetSeconds",
                "fiveHourResetsInSeconds",
                "secondsUntilReset",
                "resetSeconds",
            ],
        ),
    })
}

fn read_claude_log_usage() -> Option<RuntimeUsage> {
    let limit = std::env::var("CLAUDE_5H_TOKEN_LIMIT")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(125_000_000);

    let now = SystemTime::now();
    let cutoff = now.checked_sub(Duration::from_secs(5 * 60 * 60))?;
    let home = std::env::var("HOME").ok()?;
    let projects_dir = PathBuf::from(home).join(".claude/projects");
    let (tokens, oldest_usage) = claude_usage_tokens_since(&projects_dir, cutoff);
    if tokens == 0 {
        return None;
    }

    let percent = ((tokens as f64 / limit as f64) * 100.0).round();
    let reset_seconds = oldest_usage
        .and_then(|timestamp| timestamp.checked_add(Duration::from_secs(5 * 60 * 60)))
        .and_then(|reset_at| reset_at.duration_since(now).ok())
        .map(|duration| duration.as_secs());

    Some(RuntimeUsage {
        context_used_percent: read_claude_context_used_percent(),
        five_hour_percent: Some(percent.clamp(0.0, 100.0) as u8),
        five_hour_reset_seconds: reset_seconds,
    })
}

fn read_claude_context_used_percent() -> Option<u8> {
    let home = std::env::var("HOME").ok()?;
    let projects_dir = PathBuf::from(home).join(".claude/projects");
    let latest = latest_claude_usage(&projects_dir)?;
    let tokens = latest.input_tokens
        + latest.output_tokens
        + latest.cache_creation_input_tokens
        + latest.cache_read_input_tokens;
    if tokens == 0 {
        return None;
    }

    let percent = (tokens as f64 / 1_000_000.0) * 100.0;
    Some(percent.round().clamp(0.0, 100.0) as u8)
}

struct ClaudeUsageLine {
    timestamp: SystemTime,
    input_tokens: u64,
    output_tokens: u64,
    cache_creation_input_tokens: u64,
    cache_read_input_tokens: u64,
}

fn latest_claude_usage(root: &PathBuf) -> Option<ClaudeUsageLine> {
    let now = SystemTime::now();
    let cutoff = now.checked_sub(Duration::from_secs(5 * 60 * 60))?;
    let mut files = Vec::new();
    collect_jsonl_files(root, &mut files, cutoff, 0);

    files
        .iter()
        .filter_map(|path| fs::read_to_string(path).ok())
        .flat_map(|raw| {
            raw.lines()
                .filter_map(claude_usage_line_from_line)
                .collect::<Vec<_>>()
        })
        .max_by_key(|usage| usage.timestamp)
}

fn claude_usage_tokens_since(root: &PathBuf, cutoff: SystemTime) -> (u64, Option<SystemTime>) {
    let mut files = Vec::new();
    collect_jsonl_files(root, &mut files, cutoff, 0);

    let mut tokens = 0;
    let mut oldest_usage = None;
    for path in files {
        let Ok(raw) = fs::read_to_string(path) else {
            continue;
        };
        for line in raw.lines() {
            let Some((line_tokens, timestamp)) = claude_usage_from_line(line, cutoff) else {
                continue;
            };
            tokens += line_tokens;
            if oldest_usage.is_none_or(|oldest| timestamp < oldest) {
                oldest_usage = Some(timestamp);
            }
        }
    }

    (tokens, oldest_usage)
}

fn claude_usage_from_line(line: &str, cutoff: SystemTime) -> Option<(u64, SystemTime)> {
    let usage = claude_usage_line_from_line(line)?;
    if usage.timestamp < cutoff {
        return None;
    }

    let tokens = usage.input_tokens
        + usage.output_tokens
        + usage.cache_creation_input_tokens
        + usage.cache_read_input_tokens;

    (tokens > 0).then_some((tokens, usage.timestamp))
}

fn claude_usage_line_from_line(line: &str) -> Option<ClaudeUsageLine> {
    let json = serde_json::from_str::<serde_json::Value>(line).ok()?;
    let timestamp = json
        .get("timestamp")
        .and_then(|value| value.as_str())
        .and_then(parse_iso_timestamp_millis)?;

    let usage = json
        .get("message")
        .and_then(|message| message.get("usage"))
        .or_else(|| json.get("usage"))
        .or_else(|| {
            json.get("data")
                .and_then(|data| data.get("message"))
                .and_then(|message| message.get("usage"))
        })
        .or_else(|| json.get("data").and_then(|data| data.get("usage")))?;

    Some(ClaudeUsageLine {
        timestamp,
        input_tokens: json_number(usage, "input_tokens"),
        output_tokens: json_number(usage, "output_tokens"),
        cache_creation_input_tokens: json_number(usage, "cache_creation_input_tokens"),
        cache_read_input_tokens: json_number(usage, "cache_read_input_tokens"),
    })
}
