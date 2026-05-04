pub fn parse_percent(value: &str) -> Option<u8> {
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

pub fn json_percent(value: &serde_json::Value) -> Option<u8> {
    if let Some(percent) = value.as_f64() {
        return Some(percent.round().clamp(0.0, 100.0) as u8);
    }

    value.as_str().and_then(parse_percent)
}

pub fn find_percent_by_keys(json: &serde_json::Value, keys: &[&str]) -> Option<u8> {
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

pub fn find_seconds_by_keys(json: &serde_json::Value, keys: &[&str]) -> Option<u64> {
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

pub fn json_number(json: &serde_json::Value, key: &str) -> u64 {
    json.get(key)
        .and_then(|value| value.as_u64())
        .unwrap_or_default()
}
