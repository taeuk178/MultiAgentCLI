use super::ProviderId;

pub fn normalize_model_name(provider: &ProviderId, model: &str) -> String {
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
