mod providers;
mod pty_manager;

use providers::{spawn_config, ProviderId};
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
) -> Result<(), String> {
    let config = spawn_config(&provider_id);
    state.create(app, tab_id, config, cols, rows)
}

#[tauri::command]
fn pty_write(
    state: State<'_, PtyManager>,
    tab_id: String,
    data: String,
) -> Result<(), String> {
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
fn pty_close(
    state: State<'_, PtyManager>,
    tab_id: String,
) -> Result<(), String> {
    state.close(&tab_id)
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
