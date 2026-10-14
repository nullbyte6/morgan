use std::time::Instant;

use ratatui::crossterm::event::{KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use tokio::sync::mpsc::UnboundedSender;
use tokio::task::JoinHandle;

use crate::ollama::{ChatMessage, Client, LibModel, ModelInfo};

pub const FALLBACK_MODELS: &[(&str, &str, &[&str])] = &[
    ("qwen3.5", "Qwen 3.5 family of open multimodal models.", &["0.8b", "2b", "4b", "9b", "27b", "35b", "122b"]),
    ("qwen3.8", "Qwen 3.8 family of open models.", &["27b"]),
];

const SEARCH_DELAY_TICKS: usize = 4;
const PAGE_LOOKAHEAD: usize = 4;

const SYSTEM_PROMPT: &str = "You are Morgan, a capable local AI agent running in a terminal. Be concise and direct.";

pub enum AppEvent {
    Key(KeyEvent),
    Resize,
    Tick,
    Models(Result<Vec<ModelInfo>, String>),
    Token(String),
    Thinking(String),
    ChatDone { tokens: u64, nanos: u64 },
    ChatError(String),
    PullProgress { status: String, completed: u64, total: u64 },
    PullDone(String),
    PullError(String),
    Library { seq: u64, result: Result<Vec<LibModel>, String> },
}

#[derive(Clone, Copy, PartialEq)]
pub enum Mode {
    Chat,
    Models,
    Pull,
}

#[derive(Clone, PartialEq)]
pub enum Conn {
    Checking,
    Online,
    Offline(String),
}

#[derive(Clone, Copy, PartialEq)]
pub enum Role {
    User,
    Assistant,
    System,
}

pub struct Msg {
    pub role: Role,
    pub content: String,
    pub thinking: String,
}

pub struct PullState {
    pub name: String,
    pub status: String,
    pub completed: u64,
    pub total: u64,
}

pub struct Variants {
    pub name: String,
    pub options: Vec<String>,
    pub selected: usize,
}

#[derive(Default)]
pub struct PullUi {
    pub query: String,
    pub searching: bool,
    pub items: Vec<LibModel>,
    pub selected: usize,
    pub loading: bool,
    pub page: usize,
    pub done: bool,
    pub loaded: bool,
    pub notice: Option<String>,
    pub variants: Option<Variants>,
    pub seq: u64,
    pub dirty_at: Option<usize>,
}

impl PullUi {
    pub fn is_direct(&self) -> bool {
        let q = self.query.trim();
        q.contains(':') || q.contains('/')
    }
}

pub struct App {
    pub client: Client,
    pub tx: UnboundedSender<AppEvent>,
    pub started: Instant,
    pub mode: Mode,
    pub conn: Conn,
    pub models: Vec<ModelInfo>,
    pub model: Option<String>,
    pub messages: Vec<Msg>,
    pub input: String,
    pub cursor: usize,
    pub scroll: usize,
    pub streaming: bool,
    pub show_thinking: bool,
    pub tps: Option<f64>,
    pub activity: Vec<(u64, String)>,
    pub picker: usize,
    pub pull: PullUi,
    pub pulling: Option<PullState>,
    pub pull_error: Option<String>,
    pub tick: usize,
    pub should_quit: bool,
    pending_select: Option<String>,
    chat_task: Option<JoinHandle<()>>,
    pull_task: Option<JoinHandle<()>>,
}

impl App {
    pub fn new(tx: UnboundedSender<AppEvent>) -> Self {
        Self {
            client: Client::from_env(),
            tx,
            started: Instant::now(),
            mode: Mode::Chat,
            conn: Conn::Checking,
            models: Vec::new(),
            model: None,
            messages: Vec::new(),
            input: String::new(),
            cursor: 0,
            scroll: 0,
            streaming: false,
            show_thinking: false,
            tps: None,
            activity: Vec::new(),
            picker: 0,
            pull: PullUi::default(),
            pulling: None,
            pull_error: None,
            tick: 0,
            should_quit: false,
            pending_select: None,
            chat_task: None,
            pull_task: None,
        }
    }

    pub fn log(&mut self, text: impl Into<String>) {
        let secs = self.started.elapsed().as_secs();
        self.activity.push((secs, text.into()));
        if self.activity.len() > 200 {
            self.activity.remove(0);
        }
    }

    fn system(&mut self, text: impl Into<String>) {
        self.messages.push(Msg { role: Role::System, content: text.into(), thinking: String::new() });
    }

    pub fn refresh_models(&mut self) {
        self.conn = Conn::Checking;
        let client = self.client.clone();
        let tx = self.tx.clone();
        tokio::spawn(async move {
            let _ = tx.send(AppEvent::Models(client.tags().await));
        });
    }

    pub fn handle(&mut self, event: AppEvent) {
        match event {
            AppEvent::Key(key) => self.on_key(key),
            AppEvent::Resize => {}
            AppEvent::Tick => {
                self.tick = self.tick.wrapping_add(1);
                if self.mode == Mode::Pull {
                    if let Some(at) = self.pull.dirty_at {
                        if self.tick.wrapping_sub(at) >= SEARCH_DELAY_TICKS {
                            self.pull.dirty_at = None;
                            self.restart_library();
                        }
                    }
                }
            }
            AppEvent::Library { seq, result } => self.on_library(seq, result),
            AppEvent::Models(result) => self.on_models(result),
            AppEvent::Token(text) => {
                if self.streaming {
                    if let Some(last) = self.messages.last_mut() {
                        last.content.push_str(&text);
                    }
                }
            }
            AppEvent::Thinking(text) => {
                if self.streaming {
                    if let Some(last) = self.messages.last_mut() {
                        last.thinking.push_str(&text);
                    }
                }
            }
            AppEvent::ChatDone { tokens, nanos } => {
                self.streaming = false;
                self.chat_task = None;
                if nanos > 0 && tokens > 0 {
                    let rate = tokens as f64 / (nanos as f64 / 1e9);
                    self.tps = Some(rate);
                    self.log(format!("reply done · {tokens} tok · {rate:.1} tok/s"));
                } else {
                    self.log("reply done");
                }
            }
            AppEvent::ChatError(error) => {
                self.streaming = false;
                self.chat_task = None;
                if self.messages.last().is_some_and(|m| m.role == Role::Assistant && m.content.is_empty() && m.thinking.is_empty()) {
                    self.messages.pop();
                }
                self.log(format!("error: {error}"));
                self.system(format!("Ollama error: {error}"));
            }
            AppEvent::PullProgress { status, completed, total } => {
                if let Some(p) = self.pulling.as_mut() {
                    p.status = status;
                    if total > 0 {
                        p.completed = completed;
                        p.total = total;
                    }
                }
            }
            AppEvent::PullDone(name) => {
                self.pulling = None;
                self.pull_task = None;
                self.log(format!("pulled {name}"));
                self.pending_select = Some(name);
                self.mode = Mode::Chat;
                self.refresh_models();
            }
            AppEvent::PullError(error) => {
                self.pulling = None;
                self.pull_task = None;
                self.log(format!("pull failed: {error}"));
                self.pull_error = Some(error);
            }
        }
    }

    fn on_models(&mut self, result: Result<Vec<ModelInfo>, String>) {
        match result {
            Ok(models) => {
                self.conn = Conn::Online;
                self.models = models;
                if let Some(name) = self.pending_select.take() {
                    if self.models.iter().any(|m| m.name == name) {
                        self.model = Some(name);
                    }
                }
                let valid = self.model.as_ref().is_some_and(|c| self.models.iter().any(|m| &m.name == c));
                if !valid {
                    self.model = self.models.first().map(|m| m.name.clone());
                }
                if self.models.is_empty() {
                    self.log("no local models installed");
                    self.open_pull();
                } else {
                    let count = self.models.len();
                    let active = self.model.clone().unwrap_or_default();
                    self.log(format!("{count} model(s) available · using {active}"));
                }
            }
            Err(error) => {
                self.log(error.clone());
                self.conn = Conn::Offline(error);
            }
        }
    }

    fn on_key(&mut self, key: KeyEvent) {
        if key.kind != KeyEventKind::Press {
            return;
        }
        let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
        if ctrl && key.code == KeyCode::Char('q') {
            self.should_quit = true;
            return;
        }
        match self.mode {
            Mode::Chat => self.on_chat_key(key, ctrl),
            Mode::Models => self.on_models_key(key),
            Mode::Pull => self.on_pull_key(key),
        }
    }

    fn on_chat_key(&mut self, key: KeyEvent, ctrl: bool) {
        match (ctrl, key.code) {
            (true, KeyCode::Char('c')) => {
                if self.streaming {
                    self.cancel_chat();
                } else {
                    self.should_quit = true;
                }
            }
            (true, KeyCode::Char('o')) => self.open_models(),
            (true, KeyCode::Char('p')) => self.open_pull(),
            (true, KeyCode::Char('r')) => self.refresh_models(),
            (true, KeyCode::Char('l')) => {
                if !self.streaming {
                    self.messages.clear();
                    self.scroll = 0;
                    self.log("conversation cleared");
                }
            }
            (true, KeyCode::Char('t')) => self.show_thinking = !self.show_thinking,
            (true, KeyCode::Char('u')) => {
                self.input.drain(..self.cursor);
                self.cursor = 0;
            }
            (false, KeyCode::Enter) => self.send(),
            (false, KeyCode::Char(c)) => {
                self.input.insert(self.cursor, c);
                self.cursor += c.len_utf8();
            }
            (false, KeyCode::Backspace) => {
                if let Some(c) = self.input[..self.cursor].chars().next_back() {
                    self.cursor -= c.len_utf8();
                    self.input.remove(self.cursor);
                }
            }
            (false, KeyCode::Delete) => {
                if self.cursor < self.input.len() {
                    self.input.remove(self.cursor);
                }
            }
            (false, KeyCode::Left) => {
                if let Some(c) = self.input[..self.cursor].chars().next_back() {
                    self.cursor -= c.len_utf8();
                }
            }
            (false, KeyCode::Right) => {
                if let Some(c) = self.input[self.cursor..].chars().next() {
                    self.cursor += c.len_utf8();
                }
            }
            (false, KeyCode::Home) => self.cursor = 0,
            (false, KeyCode::End) => self.cursor = self.input.len(),
            (false, KeyCode::Up) => self.scroll = self.scroll.saturating_add(1),
            (false, KeyCode::Down) => self.scroll = self.scroll.saturating_sub(1),
            (false, KeyCode::PageUp) => self.scroll = self.scroll.saturating_add(10),
            (false, KeyCode::PageDown) => self.scroll = self.scroll.saturating_sub(10),
            _ => {}
        }
    }

    fn open_models(&mut self) {
        if self.models.is_empty() {
            self.refresh_models();
            return;
        }
        self.picker = self
            .model
            .as_ref()
            .and_then(|c| self.models.iter().position(|m| &m.name == c))
            .unwrap_or(0);
        self.mode = Mode::Models;
    }

    fn on_models_key(&mut self, key: KeyEvent) {
        match key.code {
            KeyCode::Esc => self.mode = Mode::Chat,
            KeyCode::Up | KeyCode::Char('k') => self.picker = self.picker.saturating_sub(1),
            KeyCode::Down | KeyCode::Char('j') => {
                if self.picker + 1 < self.models.len() {
                    self.picker += 1;
                }
            }
            KeyCode::Char('p') => self.open_pull(),
            KeyCode::Enter => {
                if let Some(m) = self.models.get(self.picker) {
                    let name = m.name.clone();
                    self.log(format!("switched to {name}"));
                    self.model = Some(name);
                }
                self.mode = Mode::Chat;
            }
            _ => {}
        }
    }

    fn open_pull(&mut self) {
        self.pull_error = None;
        self.mode = Mode::Pull;
        if !self.pull.loaded {
            self.pull.loaded = true;
            self.restart_library();
        }
    }

    fn restart_library(&mut self) {
        self.pull.seq += 1;
        self.pull.items.clear();
        self.pull.selected = 0;
        self.pull.page = 0;
        self.pull.done = false;
        self.pull.notice = None;
        self.pull.loading = false;
        if self.pull.is_direct() {
            self.pull.done = true;
            return;
        }
        self.fetch_library();
    }

    fn fetch_library(&mut self) {
        if self.pull.loading || self.pull.done {
            return;
        }
        self.pull.loading = true;
        let seq = self.pull.seq;
        let page = self.pull.page + 1;
        let query = self.pull.query.clone();
        let client = self.client.clone();
        let tx = self.tx.clone();
        tokio::spawn(async move {
            let _ = tx.send(AppEvent::Library { seq, result: client.library(&query, page).await });
        });
    }

    fn on_library(&mut self, seq: u64, result: Result<Vec<LibModel>, String>) {
        if seq != self.pull.seq {
            return;
        }
        self.pull.loading = false;
        match result {
            Ok(items) => {
                self.pull.page += 1;
                if items.is_empty() {
                    self.pull.done = true;
                    if self.pull.items.is_empty() {
                        self.pull.notice = Some("No models match that search".into());
                    }
                }
                for item in items {
                    if !self.pull.items.iter().any(|m| m.name == item.name) {
                        self.pull.items.push(item);
                    }
                }
            }
            Err(error) => {
                self.pull.done = true;
                self.log(format!("library: {error}"));
                if self.pull.items.is_empty() && self.pull.query.trim().is_empty() {
                    self.pull.items = FALLBACK_MODELS
                        .iter()
                        .map(|(name, desc, sizes)| LibModel {
                            name: name.to_string(),
                            description: desc.to_string(),
                            sizes: sizes.iter().map(|s| s.to_string()).collect(),
                            tags: Vec::new(),
                            downloads: String::new(),
                        })
                        .collect();
                }
                self.pull.notice = Some(format!("{error} · type name:tag and press / then Enter to pull anyway"));
            }
        }
    }

    fn move_pull_selection(&mut self, delta: isize) {
        let len = self.pull.items.len();
        if len == 0 {
            return;
        }
        let next = (self.pull.selected as isize + delta).clamp(0, len as isize - 1) as usize;
        self.pull.selected = next;
        if next + PAGE_LOOKAHEAD >= len {
            self.fetch_library();
        }
    }

    fn clear_query(&mut self) {
        self.pull.query.clear();
        self.pull.dirty_at = None;
        self.restart_library();
    }

    fn on_pull_key(&mut self, key: KeyEvent) {
        if self.pulling.is_some() {
            if key.code == KeyCode::Esc {
                if let Some(task) = self.pull_task.take() {
                    task.abort();
                }
                self.pulling = None;
                self.log("pull cancelled");
            }
            return;
        }
        if let Some(v) = self.pull.variants.as_mut() {
            match key.code {
                KeyCode::Esc => self.pull.variants = None,
                KeyCode::Up | KeyCode::Char('k') => v.selected = v.selected.saturating_sub(1),
                KeyCode::Down | KeyCode::Char('j') => {
                    if v.selected + 1 < v.options.len() {
                        v.selected += 1;
                    }
                }
                KeyCode::Enter => {
                    let tag = &v.options[v.selected];
                    let target = if tag == "latest" { v.name.clone() } else { format!("{}:{}", v.name, tag) };
                    self.pull.variants = None;
                    self.start_pull(target);
                }
                _ => {}
            }
            return;
        }
        let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
        if self.pull.searching {
            match key.code {
                KeyCode::Esc => {
                    self.pull.searching = false;
                    if !self.pull.query.is_empty() {
                        self.clear_query();
                    }
                }
                KeyCode::Enter => {
                    if self.pull.is_direct() {
                        let target = self.pull.query.trim().to_string();
                        self.start_pull(target);
                    } else {
                        self.pull.searching = false;
                        if self.pull.dirty_at.take().is_some() {
                            self.restart_library();
                        }
                    }
                }
                KeyCode::Up | KeyCode::Down => self.pull.searching = false,
                KeyCode::Char('u') if ctrl => self.clear_query(),
                KeyCode::Char(c) if !ctrl => {
                    self.pull.query.push(c);
                    self.pull.dirty_at = Some(self.tick);
                }
                KeyCode::Backspace => {
                    self.pull.query.pop();
                    self.pull.dirty_at = Some(self.tick);
                }
                _ => {}
            }
            return;
        }
        match key.code {
            KeyCode::Char('/') => self.pull.searching = true,
            KeyCode::Esc => {
                if self.pull.query.is_empty() {
                    self.mode = Mode::Chat;
                } else {
                    self.clear_query();
                }
            }
            KeyCode::Up | KeyCode::Char('k') => self.move_pull_selection(-1),
            KeyCode::Down | KeyCode::Char('j') => self.move_pull_selection(1),
            KeyCode::PageUp => self.move_pull_selection(-10),
            KeyCode::PageDown => self.move_pull_selection(10),
            KeyCode::Home => self.move_pull_selection(isize::MIN / 2),
            KeyCode::End => self.move_pull_selection(isize::MAX / 2),
            KeyCode::Enter => {
                if let Some(item) = self.pull.items.get(self.pull.selected) {
                    if item.sizes.is_empty() {
                        let name = item.name.clone();
                        self.start_pull(name);
                    } else {
                        let mut options = vec!["latest".to_string()];
                        options.extend(item.sizes.iter().cloned());
                        self.pull.variants = Some(Variants { name: item.name.clone(), options, selected: 0 });
                    }
                }
            }
            _ => {}
        }
    }

    fn start_pull(&mut self, name: String) {
        if matches!(self.conn, Conn::Offline(_)) {
            self.pull_error = Some(format!("Ollama is not reachable at {}", self.client.base()));
            return;
        }
        self.pull_error = None;
        self.log(format!("pulling {name}"));
        self.pulling = Some(PullState { name: name.clone(), status: "starting".into(), completed: 0, total: 0 });
        let client = self.client.clone();
        let tx = self.tx.clone();
        self.pull_task = Some(tokio::spawn(async move {
            match client.pull(&name, &tx).await {
                Ok(()) => {
                    let _ = tx.send(AppEvent::PullDone(name));
                }
                Err(e) => {
                    let _ = tx.send(AppEvent::PullError(e));
                }
            }
        }));
    }

    fn cancel_chat(&mut self) {
        if let Some(task) = self.chat_task.take() {
            task.abort();
        }
        self.streaming = false;
        self.log("generation stopped");
    }

    fn send(&mut self) {
        let text = self.input.trim().to_string();
        if text.is_empty() || self.streaming {
            return;
        }
        let Some(model) = self.model.clone() else {
            self.system("No model selected. Press Ctrl+P to pull one or Ctrl+R to rescan.");
            return;
        };
        if let Conn::Offline(error) = &self.conn {
            let error = error.clone();
            self.system(format!("{error}. Start it with `ollama serve`, then press Ctrl+R."));
            return;
        }
        self.messages.push(Msg { role: Role::User, content: text, thinking: String::new() });
        let mut history = vec![ChatMessage { role: "system".into(), content: SYSTEM_PROMPT.into() }];
        for m in &self.messages {
            let role = match m.role {
                Role::User => "user",
                Role::Assistant => "assistant",
                Role::System => continue,
            };
            history.push(ChatMessage { role: role.into(), content: m.content.clone() });
        }
        self.messages.push(Msg { role: Role::Assistant, content: String::new(), thinking: String::new() });
        self.input.clear();
        self.cursor = 0;
        self.scroll = 0;
        self.streaming = true;
        self.log(format!("asking {model}"));
        let client = self.client.clone();
        let tx = self.tx.clone();
        self.chat_task = Some(tokio::spawn(async move {
            if let Err(e) = client.chat(&model, history, &tx).await {
                let _ = tx.send(AppEvent::ChatError(e));
            }
        }));
    }
}
