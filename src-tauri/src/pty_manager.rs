use std::collections::HashMap;
use std::io::{Read, Write};
use std::sync::{Arc, Mutex};

use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use serde::Serialize;
use tauri::{AppHandle, Emitter};

use crate::providers::{utf8_locale, SpawnConfig};

#[derive(Serialize, Clone)]
struct PtyOutputPayload {
    tab_id: String,
    data: String,
}

struct PtySession {
    master: Box<dyn portable_pty::MasterPty + Send>,
    writer: Box<dyn Write + Send>,
}

pub struct PtyManager {
    sessions: Arc<Mutex<HashMap<String, PtySession>>>,
}

impl PtyManager {
    pub fn new() -> Self {
        Self {
            sessions: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub fn create(
        &self,
        app: AppHandle,
        tab_id: String,
        config: SpawnConfig,
        cols: u16,
        rows: u16,
    ) -> Result<(), String> {
        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize {
                rows,
                cols,
                pixel_width: 0,
                pixel_height: 0,
            })
            .map_err(|e| e.to_string())?;

        let mut cmd = CommandBuilder::new(&config.command);
        for arg in &config.args {
            cmd.arg(arg);
        }
        cmd.env("TERM", "xterm-256color");
        cmd.env("LANG", utf8_locale("LANG"));
        cmd.env("LC_CTYPE", utf8_locale("LC_CTYPE"));
        if let Some(cwd) = &config.cwd {
            cmd.cwd(cwd);
        }

        let _child = pair
            .slave
            .spawn_command(cmd)
            .map_err(|e| format!("failed to spawn '{}': {}", config.command, e))?;
        drop(pair.slave);

        let mut reader = pair.master.try_clone_reader().map_err(|e| e.to_string())?;
        let writer = pair.master.take_writer().map_err(|e| e.to_string())?;

        let tab_id_reader = tab_id.clone();
        std::thread::spawn(move || {
            let mut buf = [0u8; 4096];
            loop {
                match reader.read(&mut buf) {
                    Ok(0) | Err(_) => break,
                    Ok(n) => {
                        let data = String::from_utf8_lossy(&buf[..n]).into_owned();
                        let _ = app.emit(
                            "pty-output",
                            PtyOutputPayload {
                                tab_id: tab_id_reader.clone(),
                                data,
                            },
                        );
                    }
                }
            }
        });

        self.sessions.lock().map_err(|e| e.to_string())?.insert(
            tab_id,
            PtySession {
                master: pair.master,
                writer,
            },
        );

        Ok(())
    }

    pub fn write(&self, tab_id: &str, data: &[u8]) -> Result<(), String> {
        let mut sessions = self.sessions.lock().map_err(|e| e.to_string())?;
        let session = sessions.get_mut(tab_id).ok_or("session not found")?;
        session.writer.write_all(data).map_err(|e| e.to_string())?;
        session.writer.flush().map_err(|e| e.to_string())
    }

    pub fn resize(&self, tab_id: &str, cols: u16, rows: u16) -> Result<(), String> {
        let sessions = self.sessions.lock().map_err(|e| e.to_string())?;
        let session = sessions.get(tab_id).ok_or("session not found")?;
        session
            .master
            .resize(PtySize {
                rows,
                cols,
                pixel_width: 0,
                pixel_height: 0,
            })
            .map_err(|e| e.to_string())
    }

    pub fn close(&self, tab_id: &str) -> Result<(), String> {
        self.sessions
            .lock()
            .map_err(|e| e.to_string())?
            .remove(tab_id);
        Ok(())
    }
}
