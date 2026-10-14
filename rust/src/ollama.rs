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

#[derive(Clone, Debug)]
pub struct LibModel {
    pub name: String,
    pub description: String,
    pub sizes: Vec<String>,
    pub tags: Vec<String>,
    pub downloads: String,
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

fn encode(text: &str) -> String {
    let mut out = String::new();
    for b in text.bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{b:02X}"));
        }
    }
    out
}

fn decode(text: &str) -> String {
    text.replace("&#39;", "'")
        .replace("&quot;", "\"")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
}

fn compact(downloads: &str) -> String {
    let digits: String = downloads.chars().filter(char::is_ascii_digit).collect();
    let Ok(n) = digits.parse::<f64>() else { return String::new() };
    if n >= 1e9 {
        format!("{:.1}B", n / 1e9)
    } else if n >= 1e6 {
        format!("{:.1}M", n / 1e6)
    } else if n >= 1e3 {
        format!("{:.0}K", n / 1e3)
    } else {
        format!("{n:.0}")
    }
}

fn parse_library(html: &str) -> Vec<LibModel> {
    const OPEN: &str = "<a href=\"/library/";
    let mut out = Vec::new();
    let mut rest = html;
    while let Some(i) = rest.find(OPEN) {
        rest = &rest[i + OPEN.len()..];
        let Some(q) = rest.find('"') else { break };
        let name = rest[..q].to_string();
        let end = rest.find("</a>").unwrap_or(rest.len());
        let block = &rest[..end];
        rest = &rest[end..];
        if name.is_empty() || name.contains(':') {
            continue;
        }
        let description = block
            .find("<p ")
            .and_then(|p| {
                let body = &block[p..];
                let start = body.find('>')? + 1;
                let stop = body.find("</p>")?;
                Some(decode(body[start..stop].trim()))
            })
            .unwrap_or_default();
        let mut sizes = Vec::new();
        let mut tags = Vec::new();
        let mut cursor = block;
        while let Some(s) = cursor.find("<span ") {
            cursor = &cursor[s + 6..];
            let Some(close) = cursor.find('>') else { break };
            let attrs = &cursor[..close];
            let text_end = cursor[close + 1..].find('<').map(|t| close + 1 + t).unwrap_or(cursor.len());
            let text = cursor[close + 1..text_end].trim().to_string();
            if text.is_empty() {
                continue;
            }
            if attrs.contains("ddf4ff") {
                sizes.push(text);
            } else if attrs.contains("indigo-50") {
                tags.push(text);
            }
        }
        let downloads = block
            .find(" downloads\"")
            .and_then(|end| {
                let head = &block[..end];
                let start = head.rfind("title=\"")? + 7;
                Some(compact(&head[start..]))
            })
            .unwrap_or_default();
        if !out.iter().any(|m: &LibModel| m.name == name) {
            out.push(LibModel { name, description, sizes, tags, downloads });
        }
    }
    out
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

    pub async fn library(&self, query: &str, page: usize) -> Result<Vec<LibModel>, String> {
        let mut params = Vec::new();
        if !query.trim().is_empty() {
            params.push(format!("q={}", encode(query.trim())));
        }
        if page > 1 {
            params.push(format!("p={page}"));
        }
        params.push("c=local".to_string());
        let url = format!("https://ollama.com/search?{}", params.join("&"));
        let resp = self
            .http
            .get(url)
            .header("User-Agent", "morgan-tui")
            .timeout(Duration::from_secs(10))
            .send()
            .await
            .map_err(|_| "cannot reach ollama.com".to_string())?;
        if !resp.status().is_success() {
            return Err(format!("ollama.com returned HTTP {}", resp.status()));
        }
        let html = resp.text().await.map_err(|e| e.to_string())?;
        Ok(parse_library(&html))
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
