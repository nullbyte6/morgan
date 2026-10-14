use ratatui::Frame;
use ratatui::layout::{Alignment, Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Gauge, List, ListItem, ListState, Paragraph};
use unicode_width::UnicodeWidthChar;

use crate::app::{App, Conn, Mode, Role};

const ACCENT: Color = Color::Rgb(186, 134, 252);
const USER: Color = Color::Rgb(100, 210, 255);
const OK: Color = Color::Rgb(120, 220, 140);
const WARN: Color = Color::Rgb(255, 200, 90);
const BAD: Color = Color::Rgb(255, 110, 110);
const DIM: Color = Color::DarkGray;
const SPINNER: [&str; 10] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

fn panel(title: &str) -> Block<'_> {
    Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(DIM))
        .title(Span::styled(format!(" {title} "), Style::default().fg(ACCENT).bold()))
}

fn human(bytes: u64) -> String {
    let gb = bytes as f64 / 1e9;
    if gb >= 1.0 { format!("{gb:.1} GB") } else { format!("{:.0} MB", bytes as f64 / 1e6) }
}

pub fn draw(frame: &mut Frame, app: &mut App) {
    let area = frame.area();
    let rows = Layout::vertical([Constraint::Length(3), Constraint::Min(5), Constraint::Length(1)]).split(area);
    draw_header(frame, app, rows[0]);
    if rows[1].width >= 80 {
        let cols = Layout::horizontal([Constraint::Length(32), Constraint::Min(30)]).split(rows[1]);
        draw_sidebar(frame, app, cols[0]);
        draw_main(frame, app, cols[1]);
    } else {
        draw_main(frame, app, rows[1]);
    }
    draw_footer(frame, app, rows[2]);
    match app.mode {
        Mode::Chat => {}
        Mode::Models => draw_models(frame, app, area),
        Mode::Pull => draw_pull(frame, app, area),
    }
}

fn status_span(app: &App) -> Span<'static> {
    match &app.conn {
        Conn::Checking => Span::styled(format!("{} connecting", SPINNER[app.tick / 2 % SPINNER.len()]), Style::default().fg(WARN)),
        Conn::Online if app.streaming => Span::styled(format!("{} working", SPINNER[app.tick / 2 % SPINNER.len()]), Style::default().fg(ACCENT)),
        Conn::Online => Span::styled("● ready", Style::default().fg(OK)),
        Conn::Offline(_) => Span::styled("○ offline", Style::default().fg(BAD)),
    }
}

fn draw_header(frame: &mut Frame, app: &App, area: Rect) {
    let block = Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(ACCENT));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let cols = Layout::horizontal([Constraint::Min(10), Constraint::Min(10)]).split(inner);
    let left = Line::from(vec![
        Span::styled(" ◆ MORGAN", Style::default().fg(ACCENT).bold()),
        Span::styled("  agent console", Style::default().fg(DIM)),
    ]);
    let model = app.model.clone().unwrap_or_else(|| "no model".into());
    let right = Line::from(vec![
        Span::styled(model, Style::default().fg(USER)),
        Span::raw("  "),
        status_span(app),
        Span::raw(" "),
    ]);
    frame.render_widget(Paragraph::new(left), cols[0]);
    frame.render_widget(Paragraph::new(right).alignment(Alignment::Right), cols[1]);
}

fn draw_sidebar(frame: &mut Frame, app: &App, area: Rect) {
    let rows = Layout::vertical([Constraint::Length(8), Constraint::Length(8), Constraint::Min(4)]).split(area);

    let host = app.client.base().trim_start_matches("http://").to_string();
    let tps = app.tps.map(|t| format!("{t:.1} tok/s")).unwrap_or_else(|| "–".into());
    let turns = app.messages.iter().filter(|m| m.role == Role::User).count();
    let label = |s: &'static str| Span::styled(format!("{s:<8}"), Style::default().fg(DIM));
    let agent = vec![
        Line::from(vec![label("state"), status_span(app)]),
        Line::from(vec![label("host"), Span::raw(host)]),
        Line::from(vec![label("turns"), Span::raw(turns.to_string())]),
        Line::from(vec![label("speed"), Span::raw(tps)]),
        Line::from(vec![label("think"), Span::raw(if app.show_thinking { "shown" } else { "hidden" })]),
    ];
    frame.render_widget(Paragraph::new(agent).block(panel("Agent")), rows[0]);

    let items: Vec<ListItem> = if app.models.is_empty() {
        vec![ListItem::new(Span::styled("none installed", Style::default().fg(DIM)))]
    } else {
        app.models
            .iter()
            .map(|m| {
                let active = app.model.as_deref() == Some(m.name.as_str());
                let mark = if active { "▸ " } else { "  " };
                let style = if active { Style::default().fg(USER).bold() } else { Style::default() };
                ListItem::new(Line::from(vec![
                    Span::styled(format!("{mark}{}", m.name), style),
                    Span::styled(format!(" {}", human(m.size)), Style::default().fg(DIM)),
                ]))
            })
            .collect()
    };
    frame.render_widget(List::new(items).block(panel("Models")), rows[1]);

    let height = rows[2].height.saturating_sub(2) as usize;
    let width = rows[2].width.saturating_sub(2) as usize;
    let start = app.activity.len().saturating_sub(height);
    let lines: Vec<Line> = app.activity[start..]
        .iter()
        .map(|(secs, text)| {
            let stamp = format!("{:02}:{:02} ", secs / 60 % 100, secs % 60);
            let room = width.saturating_sub(stamp.len());
            let body: String = text.chars().take(room).collect();
            Line::from(vec![Span::styled(stamp, Style::default().fg(DIM)), Span::raw(body)])
        })
        .collect();
    frame.render_widget(Paragraph::new(lines).block(panel("Activity")), rows[2]);
}

fn wrap_plain(text: &str, width: usize) -> Vec<String> {
    let mut out = Vec::new();
    for raw in text.split('\n') {
        if raw.is_empty() {
            out.push(String::new());
            continue;
        }
        for piece in textwrap::wrap(raw, width.max(1)) {
            out.push(piece.into_owned());
        }
    }
    out
}

fn transcript_lines(app: &App, width: usize) -> Vec<Line<'static>> {
    let mut lines: Vec<Line<'static>> = Vec::new();
    if app.messages.is_empty() {
        lines.push(Line::from(Span::styled("Ask Morgan anything.", Style::default().fg(ACCENT).bold())));
        lines.push(Line::from(Span::styled("Type below and press Enter. Ctrl+O switches model, Ctrl+P pulls a new one.", Style::default().fg(DIM))));
        return lines;
    }
    let last = app.messages.len() - 1;
    for (i, msg) in app.messages.iter().enumerate() {
        let live = app.streaming && i == last;
        let (name, color) = match msg.role {
            Role::User => ("you", USER),
            Role::Assistant => ("morgan", ACCENT),
            Role::System => ("system", WARN),
        };
        let mut head = vec![Span::styled(format!("▌{name}"), Style::default().fg(color).bold())];
        if live {
            head.push(Span::styled(format!(" {}", SPINNER[app.tick / 2 % SPINNER.len()]), Style::default().fg(color)));
        }
        lines.push(Line::from(head));
        if msg.role == Role::Assistant && !msg.thinking.is_empty() {
            if app.show_thinking {
                for l in wrap_plain(msg.thinking.trim(), width.saturating_sub(2)) {
                    lines.push(Line::from(Span::styled(format!("│ {l}"), Style::default().fg(DIM).add_modifier(Modifier::ITALIC))));
                }
            } else if msg.content.is_empty() {
                lines.push(Line::from(Span::styled(
                    format!("│ thinking… ({} chars, Ctrl+T to show)", msg.thinking.chars().count()),
                    Style::default().fg(DIM).add_modifier(Modifier::ITALIC),
                )));
            }
        }
        let mut in_code = false;
        for raw in msg.content.split('\n') {
            if raw.trim_start().starts_with("```") {
                in_code = !in_code;
                lines.push(Line::from(Span::styled(raw.to_string(), Style::default().fg(DIM))));
                continue;
            }
            let style = match (msg.role, in_code) {
                (_, true) => Style::default().fg(OK),
                (Role::System, _) => Style::default().fg(WARN),
                _ => Style::default(),
            };
            for l in wrap_plain(raw, width) {
                lines.push(Line::from(Span::styled(l, style)));
            }
        }
        lines.push(Line::default());
    }
    lines
}

fn input_layout(text: &str, cursor: usize, width: usize) -> (Vec<String>, usize, usize) {
    let width = width.max(1);
    let mut rows = vec![String::new()];
    let mut col = 0usize;
    let mut cursor_pos = (0usize, 0usize);
    for (idx, ch) in text.char_indices() {
        let w = ch.width().unwrap_or(0);
        if col + w > width {
            rows.push(String::new());
            col = 0;
        }
        if idx == cursor {
            cursor_pos = (rows.len() - 1, col);
        }
        rows.last_mut().unwrap().push(ch);
        col += w;
    }
    if cursor >= text.len() {
        if col >= width {
            rows.push(String::new());
            col = 0;
        }
        cursor_pos = (rows.len() - 1, col);
    }
    (rows, cursor_pos.0, cursor_pos.1)
}

fn draw_main(frame: &mut Frame, app: &mut App, area: Rect) {
    let inner_width = area.width.saturating_sub(2) as usize;
    let (rows, cur_row, cur_col) = input_layout(&app.input, app.cursor, inner_width);
    let input_rows = rows.len().clamp(1, 5) as u16;
    let split = Layout::vertical([Constraint::Min(3), Constraint::Length(input_rows + 2)]).split(area);

    let block = panel("Conversation");
    let inner = block.inner(split[0]);
    let lines = transcript_lines(app, inner.width.saturating_sub(1) as usize);
    let total = lines.len();
    let visible = inner.height as usize;
    let max_scroll = total.saturating_sub(visible);
    app.scroll = app.scroll.min(max_scroll);
    let offset = (max_scroll - app.scroll) as u16;
    frame.render_widget(Paragraph::new(lines).block(block).scroll((offset, 0)), split[0]);

    let title = if app.streaming { "Message · generating, Ctrl+C to stop".to_string() } else { "Message".to_string() };
    let border = if app.mode == Mode::Chat { ACCENT } else { DIM };
    let input_block = panel(&title).border_style(Style::default().fg(border));
    let input_inner = input_block.inner(split[1]);
    let skip = (cur_row + 1).saturating_sub(input_rows as usize);
    let shown: Vec<Line> = if app.input.is_empty() {
        vec![Line::from(Span::styled("Message Morgan…", Style::default().fg(DIM)))]
    } else {
        rows.iter().skip(skip).take(input_rows as usize).map(|r| Line::from(r.clone())).collect()
    };
    frame.render_widget(Paragraph::new(shown).block(input_block), split[1]);
    if app.mode == Mode::Chat {
        frame.set_cursor_position((input_inner.x + cur_col as u16, input_inner.y + (cur_row - skip) as u16));
    }
}

fn draw_footer(frame: &mut Frame, app: &App, area: Rect) {
    let keys: &[(&str, &str)] = match app.mode {
        Mode::Chat => &[("Enter", "send"), ("Ctrl+O", "models"), ("Ctrl+P", "pull"), ("Ctrl+T", "thinking"), ("Ctrl+L", "clear"), ("PgUp/PgDn", "scroll"), ("Ctrl+C", "stop/quit")],
        Mode::Models => &[("↑/↓", "select"), ("Enter", "use"), ("p", "pull"), ("Esc", "close")],
        Mode::Pull if app.pulling.is_some() => &[("Esc", "cancel download")],
        Mode::Pull if app.pull.searching => &[("Enter", "apply"), ("Ctrl+U", "clear"), ("Esc", "stop searching")],
        Mode::Pull if app.pull.variants.is_some() => &[("↑/↓", "select"), ("Enter", "pull"), ("Esc", "back")],
        Mode::Pull => &[("/", "search"), ("↑/↓", "select"), ("Enter", "choose"), ("Esc", "clear/close")],
    };
    let mut spans = Vec::new();
    for (key, label) in keys {
        spans.push(Span::styled(format!(" {key} "), Style::default().fg(Color::Black).bg(DIM)));
        spans.push(Span::styled(format!(" {label} "), Style::default().fg(DIM)));
    }
    frame.render_widget(Paragraph::new(Line::from(spans)), area);
}

fn centered(area: Rect, width: u16, height: u16) -> Rect {
    let w = width.min(area.width);
    let h = height.min(area.height);
    Rect::new(area.x + (area.width - w) / 2, area.y + (area.height - h) / 2, w, h)
}

fn draw_models(frame: &mut Frame, app: &App, area: Rect) {
    let rect = centered(area, 60, (app.models.len() as u16 + 4).min(20));
    frame.render_widget(Clear, rect);
    let items: Vec<ListItem> = app
        .models
        .iter()
        .map(|m| {
            ListItem::new(Line::from(vec![
                Span::raw(m.name.clone()),
                Span::styled(format!("  {}", human(m.size)), Style::default().fg(DIM)),
            ]))
        })
        .collect();
    let list = List::new(items)
        .block(panel("Select model").border_style(Style::default().fg(ACCENT)))
        .highlight_style(Style::default().fg(Color::Black).bg(ACCENT))
        .highlight_symbol("▸ ");
    let mut state = ListState::default().with_selected(Some(app.picker));
    frame.render_stateful_widget(list, rect, &mut state);
}

fn clip(text: &str, width: usize) -> String {
    if text.chars().count() <= width {
        return text.to_string();
    }
    let mut out: String = text.chars().take(width.saturating_sub(1)).collect();
    out.push('…');
    out
}

fn draw_pull(frame: &mut Frame, app: &App, area: Rect) {
    let rect = centered(area, 88, area.height.saturating_sub(4).min(28));
    frame.render_widget(Clear, rect);
    let ui = &app.pull;
    let title = if app.models.is_empty() { "No models installed · pull one" } else { "Pull a model" };
    let block = panel(title).border_style(Style::default().fg(ACCENT));
    let inner = block.inner(rect);
    frame.render_widget(block, rect);

    let parts = Layout::vertical([Constraint::Length(3), Constraint::Min(3), Constraint::Length(3)]).split(inner);

    let search_border = if ui.searching { ACCENT } else { DIM };
    let search_block = Block::default()
        .borders(Borders::ALL)
        .border_type(BorderType::Rounded)
        .border_style(Style::default().fg(search_border));
    let search_inner = search_block.inner(parts[0]);
    let search_line = if ui.query.is_empty() && !ui.searching {
        Line::from(Span::styled("/ to search the Ollama library · or type name:tag to pull any model", Style::default().fg(DIM)))
    } else {
        Line::from(vec![Span::styled("/ ", Style::default().fg(ACCENT)), Span::raw(ui.query.clone())])
    };
    frame.render_widget(Paragraph::new(search_line).block(search_block), parts[0]);
    if ui.searching {
        let col = 2 + ui.query.chars().map(|c| c.width().unwrap_or(0)).sum::<usize>();
        frame.set_cursor_position((search_inner.x + (col as u16).min(search_inner.width.saturating_sub(1)), search_inner.y));
    }

    let width = parts[1].width as usize;
    if let Some(v) = &ui.variants {
        let items: Vec<ListItem> = v
            .options
            .iter()
            .map(|o| {
                let note = if o == "latest" { "  default tag" } else { "" };
                ListItem::new(Line::from(vec![
                    Span::raw(format!("{}:{}", v.name, o)),
                    Span::styled(note, Style::default().fg(DIM)),
                ]))
            })
            .collect();
        let list = List::new(items)
            .block(Block::default().title(Span::styled(format!(" {} · choose a size ", v.name), Style::default().fg(WARN))))
            .highlight_style(Style::default().fg(Color::Black).bg(ACCENT))
            .highlight_symbol("▸ ");
        let mut state = ListState::default().with_selected(Some(v.selected));
        frame.render_stateful_widget(list, parts[1], &mut state);
    } else if ui.items.is_empty() {
        let text = if ui.is_direct() {
            format!("Press Enter to pull {}", ui.query.trim())
        } else if ui.loading || ui.dirty_at.is_some() {
            format!("{} searching…", SPINNER[app.tick / 2 % SPINNER.len()])
        } else {
            ui.notice.clone().unwrap_or_default()
        };
        frame.render_widget(Paragraph::new(Span::styled(text, Style::default().fg(DIM))), parts[1]);
    } else {
        let name_w = 22usize;
        let size_w = 24usize.min(width / 4);
        let items: Vec<ListItem> = ui
            .items
            .iter()
            .map(|m| {
                let sizes = if m.sizes.is_empty() { m.tags.join(" ") } else { m.sizes.join(" ") };
                let used = 2 + name_w + 1 + size_w + 1 + 7 + 1;
                let desc = clip(&m.description, width.saturating_sub(used));
                ListItem::new(Line::from(vec![
                    Span::styled(format!("{:<name_w$}", clip(&m.name, name_w)), Style::default().fg(USER)),
                    Span::raw(" "),
                    Span::styled(format!("{:<size_w$}", clip(&sizes, size_w)), Style::default().fg(WARN)),
                    Span::raw(" "),
                    Span::styled(format!("{:>7}", m.downloads), Style::default().fg(DIM)),
                    Span::raw(" "),
                    Span::styled(desc, Style::default().fg(DIM)),
                ]))
            })
            .collect();
        let list = List::new(items)
            .highlight_style(Style::default().bg(Color::Rgb(50, 40, 70)).add_modifier(Modifier::BOLD))
            .highlight_symbol("▸ ");
        let mut state = ListState::default().with_selected(Some(ui.selected));
        frame.render_stateful_widget(list, parts[1], &mut state);
    }

    if let Some(p) = &app.pulling {
        let ratio = if p.total > 0 { (p.completed as f64 / p.total as f64).clamp(0.0, 1.0) } else { 0.0 };
        let gauge = Gauge::default()
            .block(Block::default().title(Span::styled(format!(" {} · {} ", p.name, p.status), Style::default().fg(WARN))))
            .gauge_style(Style::default().fg(ACCENT))
            .ratio(ratio)
            .label(if p.total > 0 { format!("{} / {}", human(p.completed), human(p.total)) } else { "…".into() });
        frame.render_widget(gauge, parts[2]);
        return;
    }
    let mut lines: Vec<Line> = Vec::new();
    if let Some(e) = &app.pull_error {
        lines.push(Line::from(Span::styled(format!("pull failed: {e}"), Style::default().fg(BAD))));
    } else if let Conn::Offline(e) = &app.conn {
        lines.push(Line::from(Span::styled(format!("{e}. Start `ollama serve`, then Ctrl+R."), Style::default().fg(BAD))));
    }
    if let Some(n) = &ui.notice {
        if !ui.items.is_empty() {
            lines.push(Line::from(Span::styled(n.clone(), Style::default().fg(WARN))));
        }
    }
    if lines.is_empty() && ui.variants.is_none() {
        if let Some(m) = ui.items.get(ui.selected) {
            let tags = if m.tags.is_empty() { String::new() } else { format!("[{}] ", m.tags.join(", ")) };
            lines.push(Line::from(vec![Span::styled(tags, Style::default().fg(OK)), Span::raw(m.description.clone())]));
        }
    }
    let status = if ui.loading && !ui.items.is_empty() { " loading more…" } else { "" };
    lines.push(Line::from(Span::styled(format!("{} models{}", ui.items.len(), status), Style::default().fg(DIM))));
    frame.render_widget(Paragraph::new(lines).wrap(ratatui::widgets::Wrap { trim: true }), parts[2]);
}
