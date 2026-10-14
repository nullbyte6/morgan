use std::time::Duration;

use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tokio::sync::mpsc::UnboundedSender;

use crate::app::AppEvent;

#[derive(Clone, Debug, Deserialize)]
pub struct ModelInfo {
    pub name: String,
    #[serde(default)]
    pub size: u64,
}

#[derive(Deserialize)]
struct Tags {
    models: Vec<ModelInfo>,
}

#[derive(Clone, Serialize)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Clone)]
pub struct Client {
    http: reqwest::Client,
    base: String,
}

fn normalize_host(raw: &str) -> String {
    let mut host = raw.trim().trim_end_matches('/').to_string();
    if host.is_empty() {
        return "http://127.0.0.1:11434".into();
    }
    if !host.contains("://") {
        host = format!("http://{host}");
    }
    let (scheme, rest) = host.split_once("://").unwrap_or(("http", ""));
    let rest = rest.replace("0.0.0.0", "127.0.0.1");
    let rest = if rest.contains(':') { rest } else { format!("{rest}:11434") };
    format!("{scheme}://{rest}")
}

async fn error_text(resp: reqwest::Response) -> String {
    let status = resp.status();
    let body = resp.text().await.unwrap_or_default();
    serde_json::from_str::<Value>(&body)
        .ok()
        .and_then(|v| v["error"].as_str().map(str::to_string))
        .unwrap_or_else(|| format!("HTTP {status}"))
}

async fn each_line(
    resp: reqwest::Response,
    mut on_line: impl FnMut(Value) -> Result<(), String>,
) -> Result<(), String> {
    let mut stream = resp.bytes_stream();
    let mut buffer: Vec<u8> = Vec::new();
    while let Some(chunk) = stream.next().await {
        buffer.extend_from_slice(&chunk.map_err(|e| e.to_string())?);
        while let Some(pos) = buffer.iter().position(|&b| b == b'\n') {
            let line: Vec<u8> = buffer.drain(..=pos).collect();
            if let Ok(value) = serde_json::from_slice::<Value>(&line) {
                on_line(value)?;
            }
        }
    }
    if let Ok(value) = serde_json::from_slice::<Value>(&buffer) {
        on_line(value)?;
    }
    Ok(())
}

impl Client {
    pub fn from_env() -> Self {
        let raw = std::env::var("OLLAMA_HOST").unwrap_or_default();
        let http = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(3))
            .build()
            .expect("http client");
        Self { http, base: normalize_host(&raw) }
    }

    pub fn base(&self) -> &str {
        &self.base
    }

    pub async fn tags(&self) -> Result<Vec<ModelInfo>, String> {
        let resp = self
            .http
            .get(format!("{}/api/tags", self.base))
            .timeout(Duration::from_secs(5))
            .send()
            .await
            .map_err(|_| format!("cannot reach Ollama at {}", self.base))?;
        if !resp.status().is_success() {
            return Err(error_text(resp).await);
        }
        let tags: Tags = resp.json().await.map_err(|e| e.to_string())?;
        Ok(tags.models)
    }

    pub async fn chat(
        &self,
        model: &str,
        messages: Vec<ChatMessage>,
        tx: &UnboundedSender<AppEvent>,
    ) -> Result<(), String> {
        let resp = self
            .http
            .post(format!("{}/api/chat", self.base))
            .json(&json!({ "model": model, "messages": messages, "stream": true }))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !resp.status().is_success() {
            return Err(error_text(resp).await);
        }
        each_line(resp, |v| {
            if let Some(err) = v["error"].as_str() {
                return Err(err.to_string());
            }
            if let Some(text) = v["message"]["thinking"].as_str().filter(|t| !t.is_empty()) {
                let _ = tx.send(AppEvent::Thinking(text.to_string()));
            }
            if let Some(text) = v["message"]["content"].as_str().filter(|t| !t.is_empty()) {
                let _ = tx.send(AppEvent::Token(text.to_string()));
            }
            if v["done"].as_bool() == Some(true) {
                let _ = tx.send(AppEvent::ChatDone {
                    tokens: v["eval_count"].as_u64().unwrap_or(0),
                    nanos: v["eval_duration"].as_u64().unwrap_or(0),
                });
            }
            Ok(())
        })
        .await
    }

    pub async fn pull(&self, model: &str, tx: &UnboundedSender<AppEvent>) -> Result<(), String> {
        let resp = self
            .http
            .post(format!("{}/api/pull", self.base))
            .json(&json!({ "model": model, "stream": true }))
            .send()
            .await
            .map_err(|e| e.to_string())?;
        if !resp.status().is_success() {
            return Err(error_text(resp).await);
        }
        each_line(resp, |v| {
            if let Some(err) = v["error"].as_str() {
                return Err(err.to_string());
            }
            let _ = tx.send(AppEvent::PullProgress {
                status: v["status"].as_str().unwrap_or("").to_string(),
                completed: v["completed"].as_u64().unwrap_or(0),
                total: v["total"].as_u64().unwrap_or(0),
            });
            Ok(())
        })
        .await
    }
}
