mod providers;
mod pty_manager;

use providers::{run_chat, runtime_statuses, spawn_config, ProviderId, ProviderRuntimeStatus};
use pty_manager::PtyManager;
use tauri::State;

#[tauri::command]
fn pty_create(
    app: tauri::AppHandle,
    state: State<'_, PtyManager>,
    tab_id: String,
    provider_id: ProviderId,
    cols: u16,
    rows: u16,
    cwd: Option<String>,
) -> Result<(), String> {
    let mut config = spawn_config(&provider_id);
    config.cwd = cwd;
    state.create(app, tab_id, config, cols, rows)
}

#[tauri::command]
fn pty_write(state: State<'_, PtyManager>, tab_id: String, data: String) -> Result<(), String> {
    state.write(&tab_id, data.as_bytes())
}

#[tauri::command]
fn pty_resize(
    state: State<'_, PtyManager>,
    tab_id: String,
    cols: u16,
    rows: u16,
) -> Result<(), String> {
    state.resize(&tab_id, cols, rows)
}

#[tauri::command]
fn pty_close(state: State<'_, PtyManager>, tab_id: String) -> Result<(), String> {
    state.close(&tab_id)
}

#[tauri::command]
async fn provider_chat(
    provider_id: ProviderId,
    prompt: String,
    cwd: Option<String>,
) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || run_chat(&provider_id, &prompt, cwd.as_deref()))
        .await
        .map_err(|e| format!("provider task failed: {}", e))?
}

#[tauri::command]
async fn provider_statuses() -> Result<Vec<ProviderRuntimeStatus>, String> {
    tauri::async_runtime::spawn_blocking(runtime_statuses)
        .await
        .map_err(|e| format!("provider status task failed: {}", e))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(PtyManager::new())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            pty_create,
            pty_write,
            pty_resize,
            pty_close,
            provider_chat,
            provider_statuses,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
