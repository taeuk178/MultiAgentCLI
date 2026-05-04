use std::fs;
use std::path::PathBuf;

pub fn read_codex_model() -> Result<String, std::io::Error> {
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

pub fn read_claude_model() -> Result<String, std::io::Error> {
    let home = std::env::var("HOME").unwrap_or_default();
    read_json_model(
        [
            PathBuf::from(&home).join(".claude/settings.local.json"),
            PathBuf::from(&home).join(".claude/settings.json"),
        ],
        ["model", "defaultModel", "modelName"],
    )
}

pub fn read_gemini_model() -> Result<String, std::io::Error> {
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
