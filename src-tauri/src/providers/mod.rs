use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum ProviderId {
    Claude,
    Codex,
    Gemini,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderRuntimeStatus {
    provider_id: ProviderId,
    health: String,
    model: String,
    context_used_percent: Option<u8>,
    five_hour_percent: Option<u8>,
    five_hour_reset_seconds: Option<u64>,
}

struct RuntimeUsage {
    context_used_percent: Option<u8>,
    five_hour_percent: Option<u8>,
    five_hour_reset_seconds: Option<u64>,
}

pub struct SpawnConfig {
    pub command: String,
    pub args: Vec<String>,
    pub cwd: Option<String>,
}

pub fn spawn_config(provider: &ProviderId) -> SpawnConfig {
    match provider {
        ProviderId::Claude => SpawnConfig {
            command: "claude".into(),
            args: vec![],
            cwd: None,
        },
        ProviderId::Codex => SpawnConfig {
            command: "codex".into(),
            args: vec![],
            cwd: None,
        },
        ProviderId::Gemini => SpawnConfig {
            command: "gemini".into(),
            args: vec![],
            cwd: None,
        },
    }
}

pub fn run_chat(provider: &ProviderId, prompt: &str, cwd: Option<&str>) -> Result<String, String> {
    let mut command = match provider {
        ProviderId::Claude => {
            let mut cmd = Command::new("claude");
            cmd.arg("-p").arg("--output-format").arg("text").arg(prompt);
            cmd
        }
        ProviderId::Codex => {
            let output_path = output_path("codex");
            let mut cmd = Command::new("codex");
            cmd.arg("exec")
                .arg("--color")
                .arg("never")
                .arg("--skip-git-repo-check")
                .arg("-o")
                .arg(&output_path)
                .arg(prompt);
            cmd.env("MULTI_AGENT_CODEX_OUTPUT", output_path);
            cmd
        }
        ProviderId::Gemini => {
            let mut cmd = Command::new("gemini");
            cmd.arg("--prompt")
                .arg(prompt)
                .arg("--output-format")
                .arg("text")
                .arg("--skip-trust");
            cmd
        }
    };

    if let Some(cwd) = cwd {
        command.current_dir(cwd);
    }
    command.env("TERM", "xterm-256color");
    command.env("LANG", utf8_locale("LANG"));
    command.env("LC_CTYPE", utf8_locale("LC_CTYPE"));

    let codex_output_path = command.get_envs().find_map(|(key, value)| {
        if key == "MULTI_AGENT_CODEX_OUTPUT" {
            value.map(PathBuf::from)
        } else {
            None
        }
    });

    let output = command.output().map_err(|e| e.to_string())?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();

    let last_message = codex_output_path
        .as_ref()
        .and_then(|path| fs::read_to_string(path).ok())
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());

    if let Some(path) = codex_output_path {
        let _ = fs::remove_file(path);
    }

    if output.status.success() {
        if let Some(message) = last_message {
            Ok(message)
        } else if !stdout.is_empty() {
            Ok(strip_codex_noise(&stdout))
        } else {
            Ok(String::new())
        }
    } else {
        Err(if stderr.is_empty() { stdout } else { stderr })
    }
}

pub fn runtime_statuses() -> Vec<ProviderRuntimeStatus> {
    [ProviderId::Claude, ProviderId::Codex, ProviderId::Gemini]
        .into_iter()
        .map(|provider| {
            let healthy = command_exists(&provider);
            let usage = runtime_usage(&provider);
            ProviderRuntimeStatus {
                model: configured_model(&provider),
                context_used_percent: usage.context_used_percent,
                five_hour_percent: usage.five_hour_percent,
                five_hour_reset_seconds: usage.five_hour_reset_seconds,
                provider_id: provider,
                health: if healthy { "healthy" } else { "error" }.to_string(),
            }
        })
        .collect()
}

pub fn utf8_locale(name: &str) -> String {
    match std::env::var(name) {
        Ok(value)
            if value.to_ascii_uppercase().contains("UTF-8")
                || value.to_ascii_uppercase().contains("UTF8") =>
        {
            value
        }
        _ => "ko_KR.UTF-8".to_string(),
    }
}

fn output_path(prefix: &str) -> PathBuf {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();

    std::env::temp_dir().join(format!(
        "multi-agent-cli-v2-{}-{}-{}.txt",
        prefix,
        std::process::id(),
        millis
    ))
}

fn strip_codex_noise(output: &str) -> String {
    output
        .lines()
        .filter(|line| {
            let trimmed = line.trim();
            !trimmed.starts_with("WARNING:")
                && !trimmed.starts_with("Codex")
                && !trimmed.starts_with("To get started")
        })
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string()
}

fn command_exists(provider: &ProviderId) -> bool {
    let command = match provider {
        ProviderId::Claude => "claude",
        ProviderId::Codex => "codex",
        ProviderId::Gemini => "gemini",
    };

    Command::new(command)
        .arg("--version")
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}

fn configured_model(provider: &ProviderId) -> String {
    let model = match provider {
        ProviderId::Claude => std::env::var("ANTHROPIC_MODEL")
            .or_else(|_| std::env::var("CLAUDE_MODEL"))
            .or_else(|_| std::env::var("CLAUDE_CODE_MODEL"))
            .or_else(|_| read_claude_model())
            .unwrap_or_else(|_| "opus 4.7".to_string()),
        ProviderId::Codex => std::env::var("OPENAI_MODEL")
            .or_else(|_| std::env::var("CODEX_MODEL"))
            .or_else(|_| read_codex_model())
            .unwrap_or_else(|_| "default".to_string()),
        ProviderId::Gemini => std::env::var("GEMINI_MODEL")
            .or_else(|_| read_gemini_model())
            .unwrap_or_else(|_| "default".to_string()),
    };

    normalize_model_name(provider, &model)
}

fn runtime_usage(provider: &ProviderId) -> RuntimeUsage {
    match provider {
        ProviderId::Claude => read_claude_usage(),
        ProviderId::Codex => read_codex_usage(),
        ProviderId::Gemini => RuntimeUsage {
            context_used_percent: None,
            five_hour_percent: None,
            five_hour_reset_seconds: None,
        },
    }
}

fn read_claude_usage() -> RuntimeUsage {
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

fn parse_percent(value: &str) -> Option<u8> {
    let numeric = value
        .trim()
        .trim_end_matches('%')
        .parse::<f64>()
        .ok()?
        .round();
    if !numeric.is_finite() {
        return None;
    }

    Some(numeric.clamp(0.0, 100.0) as u8)
}

fn json_percent(value: &serde_json::Value) -> Option<u8> {
    if let Some(percent) = value.as_f64() {
        return Some(percent.round().clamp(0.0, 100.0) as u8);
    }

    value.as_str().and_then(parse_percent)
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

fn curl_config(url: &str, headers: &[String], body: Option<&str>) -> String {
    let mut config = format!(
        "silent\nshow-error\nfail\nmax-time = 5\nurl = \"{}\"\n",
        curl_quote(url)
    );
    for header in headers {
        config.push_str(&format!("header = \"{}\"\n", curl_quote(header)));
    }
    if let Some(body) = body {
        config.push_str("request = \"POST\"\n");
        config.push_str(&format!("data = \"{}\"\n", curl_quote(body)));
    }
    config
}

fn run_curl_config(config: &str) -> Option<String> {
    let mut child = Command::new("curl")
        .arg("-K")
        .arg("-")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    child.stdin.as_mut()?.write_all(config.as_bytes()).ok()?;
    let output = child.wait_with_output().ok()?;
    if !output.status.success() {
        return None;
    }

    let raw = String::from_utf8_lossy(&output.stdout).trim().to_string();
    (!raw.is_empty()).then_some(raw)
}

fn curl_quote(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

fn form_encode(value: &str) -> String {
    value
        .bytes()
        .flat_map(|byte| match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                vec![byte as char]
            }
            _ => format!("%{byte:02X}").chars().collect(),
        })
        .collect()
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

fn find_percent_by_keys(json: &serde_json::Value, keys: &[&str]) -> Option<u8> {
    match json {
        serde_json::Value::Object(map) => {
            for (key, value) in map {
                if keys.iter().any(|candidate| key == candidate) {
                    if let Some(percent) = json_percent(value) {
                        return Some(percent);
                    }
                }
            }

            map.values()
                .find_map(|value| find_percent_by_keys(value, keys))
        }
        serde_json::Value::Array(values) => values
            .iter()
            .find_map(|value| find_percent_by_keys(value, keys)),
        _ => None,
    }
}

fn find_seconds_by_keys(json: &serde_json::Value, keys: &[&str]) -> Option<u64> {
    match json {
        serde_json::Value::Object(map) => {
            for (key, value) in map {
                if keys.iter().any(|candidate| key == candidate) {
                    if let Some(seconds) = value.as_u64() {
                        return Some(seconds);
                    }
                    if let Some(seconds) = value.as_str().and_then(|value| value.parse().ok()) {
                        return Some(seconds);
                    }
                }
            }

            map.values()
                .find_map(|value| find_seconds_by_keys(value, keys))
        }
        serde_json::Value::Array(values) => values
            .iter()
            .find_map(|value| find_seconds_by_keys(value, keys)),
        _ => None,
    }
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

fn collect_jsonl_files(dir: &PathBuf, files: &mut Vec<PathBuf>, cutoff: SystemTime, depth: usize) {
    if depth > 8 {
        return;
    }

    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };

    for entry in entries.flatten() {
        let path = entry.path();
        let file_name = path
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("");
        if file_name == ".omc" {
            continue;
        }

        if path.is_dir() {
            collect_jsonl_files(&path, files, cutoff, depth + 1);
            continue;
        }

        if path.extension().and_then(|ext| ext.to_str()) != Some("jsonl") {
            continue;
        }

        let Ok(metadata) = entry.metadata() else {
            continue;
        };
        if metadata
            .modified()
            .ok()
            .is_some_and(|modified| modified < cutoff)
        {
            continue;
        }
        if metadata.len() <= 20 * 1024 * 1024 {
            files.push(path);
        }
    }
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

fn read_codex_usage() -> RuntimeUsage {
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

fn json_number(json: &serde_json::Value, key: &str) -> u64 {
    json.get(key)
        .and_then(|value| value.as_u64())
        .unwrap_or_default()
}

fn parse_iso_timestamp_millis(value: &str) -> Option<SystemTime> {
    let (date, time) = value.split_once('T')?;
    let mut date_parts = date.split('-');
    let year = date_parts.next()?.parse::<i32>().ok()?;
    let month = date_parts.next()?.parse::<u32>().ok()?;
    let day = date_parts.next()?.parse::<u32>().ok()?;

    let time = time.trim_end_matches('Z');
    let time = time.split_once(['+', '-']).map_or(time, |(time, _)| time);
    let mut time_parts = time.split(':');
    let hour = time_parts.next()?.parse::<u32>().ok()?;
    let minute = time_parts.next()?.parse::<u32>().ok()?;
    let second_part = time_parts.next()?;
    let second = second_part
        .split_once('.')
        .map_or(second_part, |(seconds, _)| seconds)
        .parse::<u32>()
        .ok()?;

    let days = days_from_civil(year, month, day)?;
    let seconds = days * 86_400 + hour as i64 * 3_600 + minute as i64 * 60 + second as i64;
    if seconds < 0 {
        return None;
    }

    UNIX_EPOCH.checked_add(Duration::from_secs(seconds as u64))
}

fn days_from_civil(year: i32, month: u32, day: u32) -> Option<i64> {
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return None;
    }

    let year = year - i32::from(month <= 2);
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let yoe = year - era * 400;
    let month = month as i32;
    let day = day as i32;
    let doy = (153 * (month + if month > 2 { -3 } else { 9 }) + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;

    Some((era * 146_097 + doe - 719_468) as i64)
}

fn read_codex_model() -> Result<String, std::io::Error> {
    let home = std::env::var("HOME").unwrap_or_default();
    let config = fs::read_to_string(PathBuf::from(home).join(".codex/config.toml"))?;

    config
        .lines()
        .find_map(|line| {
            let trimmed = line.trim();
            let (key, value) = trimmed.split_once('=')?;
            if key.trim() != "model" {
                return None;
            }
            Some(
                value
                    .trim()
                    .trim_matches('"')
                    .trim_matches('\'')
                    .to_string(),
            )
        })
        .filter(|value| !value.is_empty())
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::NotFound, "codex model not found"))
}

fn read_claude_model() -> Result<String, std::io::Error> {
    let home = std::env::var("HOME").unwrap_or_default();
    read_json_model(
        [
            PathBuf::from(&home).join(".claude/settings.local.json"),
            PathBuf::from(&home).join(".claude/settings.json"),
        ],
        ["model", "defaultModel", "modelName"],
    )
}

fn read_gemini_model() -> Result<String, std::io::Error> {
    let home = std::env::var("HOME").unwrap_or_default();
    read_json_model(
        [PathBuf::from(home).join(".gemini/settings.json")],
        ["model", "defaultModel", "modelName"],
    )
}

fn read_json_model<const P: usize, const K: usize>(
    paths: [PathBuf; P],
    keys: [&str; K],
) -> Result<String, std::io::Error> {
    for path in paths {
        let Ok(raw) = fs::read_to_string(path) else {
            continue;
        };
        let Ok(json) = serde_json::from_str::<serde_json::Value>(&raw) else {
            continue;
        };

        for key in keys {
            let Some(value) = json.get(key).and_then(|value| value.as_str()) else {
                continue;
            };
            let trimmed = value.trim();
            if !trimmed.is_empty() {
                return Ok(trimmed.to_string());
            }
        }
    }

    Err(std::io::Error::new(
        std::io::ErrorKind::NotFound,
        "provider model not found",
    ))
}

fn normalize_model_name(provider: &ProviderId, model: &str) -> String {
    let trimmed = model.trim();
    if trimmed.is_empty() {
        return "default".to_string();
    }

    match provider {
        ProviderId::Claude => normalize_claude_model(trimmed),
        ProviderId::Codex => normalize_codex_model(trimmed),
        ProviderId::Gemini => trimmed.to_string(),
    }
}

fn normalize_claude_model(model: &str) -> String {
    let lower = model.to_ascii_lowercase();
    if lower == "opus" {
        return "opus 4.7".to_string();
    }
    if lower == "sonnet" {
        return "sonnet".to_string();
    }

    let Some(rest) = lower.strip_prefix("claude-") else {
        return model.to_string();
    };
    let mut parts = rest.split('-');
    let Some(family) = parts.next() else {
        return model.to_string();
    };
    let Some(major) = parts.next() else {
        return family.to_string();
    };
    let Some(minor) = parts.next() else {
        return format!("{family} {major}");
    };

    format!("{family} {major}.{minor}")
}

fn normalize_codex_model(model: &str) -> String {
    let lower = model.to_ascii_lowercase();
    if let Some(rest) = lower.strip_prefix("gpt-") {
        return format!("gpt {}", rest.replace('-', " "));
    }

    model.to_string()
}
