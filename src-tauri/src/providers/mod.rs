use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ProviderId {
    Claude,
    Codex,
    Gemini,
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
