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
