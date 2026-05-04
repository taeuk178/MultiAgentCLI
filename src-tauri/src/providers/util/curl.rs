use std::io::Write;
use std::process::{Command, Stdio};

pub fn curl_config(url: &str, headers: &[String], body: Option<&str>) -> String {
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

pub fn run_curl_config(config: &str) -> Option<String> {
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

pub fn form_encode(value: &str) -> String {
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

fn curl_quote(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}
