use std::process::Command;

use super::claude_usage::read_claude_usage;
use super::codex_usage::read_codex_usage;
use super::model_config::{read_claude_model, read_codex_model, read_gemini_model};
use super::model_name::normalize_model_name;
use super::{output_path, ProviderId, RuntimeUsage, SpawnConfig};

pub(super) trait Provider {
    fn id(&self) -> ProviderId;
    fn command_name(&self) -> &'static str;

    fn spawn_config(&self) -> SpawnConfig {
        SpawnConfig {
            command: self.command_name().into(),
            args: vec![],
            cwd: None,
        }
    }

    fn chat_command(&self, prompt: &str) -> Command;

    fn command_exists(&self) -> bool {
        Command::new(self.command_name())
            .arg("--version")
            .output()
            .map(|output| output.status.success())
            .unwrap_or(false)
    }

    fn configured_model(&self) -> String;

    fn runtime_usage(&self) -> RuntimeUsage {
        RuntimeUsage {
            context_used_percent: None,
            five_hour_percent: None,
            five_hour_reset_seconds: None,
        }
    }
}

struct ClaudeProvider;
struct CodexProvider;
struct GeminiProvider;

static CLAUDE_PROVIDER: ClaudeProvider = ClaudeProvider;
static CODEX_PROVIDER: CodexProvider = CodexProvider;
static GEMINI_PROVIDER: GeminiProvider = GeminiProvider;

impl Provider for ClaudeProvider {
    fn id(&self) -> ProviderId {
        ProviderId::Claude
    }

    fn command_name(&self) -> &'static str {
        "claude"
    }

    fn chat_command(&self, prompt: &str) -> Command {
        let mut cmd = Command::new(self.command_name());
        cmd.arg("-p").arg("--output-format").arg("text").arg(prompt);
        cmd
    }

    fn configured_model(&self) -> String {
        let model = std::env::var("ANTHROPIC_MODEL")
            .or_else(|_| std::env::var("CLAUDE_MODEL"))
            .or_else(|_| std::env::var("CLAUDE_CODE_MODEL"))
            .or_else(|_| read_claude_model())
            .unwrap_or_else(|_| "opus 4.7".to_string());

        normalize_model_name(&self.id(), &model)
    }

    fn runtime_usage(&self) -> RuntimeUsage {
        read_claude_usage()
    }
}

impl Provider for CodexProvider {
    fn id(&self) -> ProviderId {
        ProviderId::Codex
    }

    fn command_name(&self) -> &'static str {
        "codex"
    }

    fn chat_command(&self, prompt: &str) -> Command {
        let output_path = output_path("codex");
        let mut cmd = Command::new(self.command_name());
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

    fn configured_model(&self) -> String {
        let model = std::env::var("OPENAI_MODEL")
            .or_else(|_| std::env::var("CODEX_MODEL"))
            .or_else(|_| read_codex_model())
            .unwrap_or_else(|_| "default".to_string());

        normalize_model_name(&self.id(), &model)
    }

    fn runtime_usage(&self) -> RuntimeUsage {
        read_codex_usage()
    }
}

impl Provider for GeminiProvider {
    fn id(&self) -> ProviderId {
        ProviderId::Gemini
    }

    fn command_name(&self) -> &'static str {
        "gemini"
    }

    fn chat_command(&self, prompt: &str) -> Command {
        let mut cmd = Command::new(self.command_name());
        cmd.arg("--prompt")
            .arg(prompt)
            .arg("--output-format")
            .arg("text")
            .arg("--skip-trust");
        cmd
    }

    fn configured_model(&self) -> String {
        let model = std::env::var("GEMINI_MODEL")
            .or_else(|_| read_gemini_model())
            .unwrap_or_else(|_| "default".to_string());

        normalize_model_name(&self.id(), &model)
    }
}

pub(super) fn provider_for(provider: ProviderId) -> &'static dyn Provider {
    match provider {
        ProviderId::Claude => &CLAUDE_PROVIDER,
        ProviderId::Codex => &CODEX_PROVIDER,
        ProviderId::Gemini => &GEMINI_PROVIDER,
    }
}
