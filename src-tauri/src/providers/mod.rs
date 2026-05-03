use std::fs;
use std::path::PathBuf;
use std::process::Command;
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
    context_label: String,
    context_percent: Option<u8>,
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
            ProviderRuntimeStatus {
                model: configured_model(&provider),
                context_label: context_label(&provider).to_string(),
                context_percent: context_percent(&provider),
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

fn context_label(provider: &ProviderId) -> &'static str {
    match provider {
        ProviderId::Claude => "5h context",
        ProviderId::Codex | ProviderId::Gemini => "ctx",
    }
}

fn context_percent(provider: &ProviderId) -> Option<u8> {
    match provider {
        ProviderId::Claude => read_claude_five_hour_percent(),
        ProviderId::Codex | ProviderId::Gemini => None,
    }
}

fn read_claude_five_hour_percent() -> Option<u8> {
    read_percent_env(["CLAUDE_5H_CONTEXT_PERCENT", "CLAUDE_5H_USAGE_PERCENT"])
        .or_else(read_claude_auth_status_percent)
        .or_else(read_claude_five_hour_log_percent)
}

fn read_percent_env<const N: usize>(names: [&str; N]) -> Option<u8> {
    names.into_iter().find_map(|name| {
        let value = std::env::var(name).ok()?;
        parse_percent(&value)
    })
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

fn read_claude_auth_status_percent() -> Option<u8> {
    let output = Command::new("claude")
        .arg("auth")
        .arg("status")
        .output()
        .ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let json = serde_json::from_str::<serde_json::Value>(&stdout).ok()?;

    find_percent_by_keys(
        &json,
        &[
            "fiveHourContextPercent",
            "fiveHourUsagePercent",
            "fiveHourLimitPercent",
            "fiveHourPercent",
            "usagePercent",
            "percentUsed",
        ],
    )
}

fn find_percent_by_keys(json: &serde_json::Value, keys: &[&str]) -> Option<u8> {
    match json {
        serde_json::Value::Object(map) => {
            for (key, value) in map {
                if keys.iter().any(|candidate| key == candidate) {
                    if let Some(percent) = value.as_f64().map(|value| value.round() as i64) {
                        return Some(percent.clamp(0, 100) as u8);
                    }
                    if let Some(percent) = value.as_str().and_then(parse_percent) {
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

fn read_claude_five_hour_log_percent() -> Option<u8> {
    let limit = std::env::var("CLAUDE_5H_TOKEN_LIMIT")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(125_000_000);

    let now = SystemTime::now();
    let cutoff = now.checked_sub(Duration::from_secs(5 * 60 * 60))?;
    let home = std::env::var("HOME").ok()?;
    let projects_dir = PathBuf::from(home).join(".claude/projects");
    let tokens = claude_usage_tokens_since(&projects_dir, cutoff);
    if tokens == 0 {
        return None;
    }

    let percent = ((tokens as f64 / limit as f64) * 100.0).round();
    Some(percent.clamp(0.0, 100.0) as u8)
}

fn claude_usage_tokens_since(root: &PathBuf, cutoff: SystemTime) -> u64 {
    let mut files = Vec::new();
    collect_jsonl_files(root, &mut files, cutoff, 0);

    files
        .iter()
        .filter_map(|path| fs::read_to_string(path).ok())
        .flat_map(|raw| {
            raw.lines()
                .filter_map(|line| claude_usage_tokens_from_line(line, cutoff))
                .collect::<Vec<_>>()
        })
        .sum()
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

fn claude_usage_tokens_from_line(line: &str, cutoff: SystemTime) -> Option<u64> {
    let json = serde_json::from_str::<serde_json::Value>(line).ok()?;
    let timestamp = json
        .get("timestamp")
        .and_then(|value| value.as_str())
        .and_then(parse_iso_timestamp_millis)?;
    if timestamp < cutoff {
        return None;
    }

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

    Some(
        json_number(usage, "input_tokens")
            + json_number(usage, "output_tokens")
            + json_number(usage, "cache_creation_input_tokens")
            + json_number(usage, "cache_read_input_tokens"),
    )
    .filter(|tokens| *tokens > 0)
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
