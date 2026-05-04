use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;

pub fn collect_jsonl_files(
    dir: &PathBuf,
    files: &mut Vec<PathBuf>,
    cutoff: SystemTime,
    depth: usize,
) {
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
