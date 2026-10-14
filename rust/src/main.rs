mod app;
mod ollama;
mod ui;

use std::io;
use std::time::Duration;

use ratatui::crossterm::event::{self, Event};
use tokio::sync::mpsc;

use app::{App, AppEvent};

fn spawn_input(tx: mpsc::UnboundedSender<AppEvent>) {
    std::thread::spawn(move || {
        loop {
            let sent = if event::poll(Duration::from_millis(100)).unwrap_or(false) {
                match event::read() {
                    Ok(Event::Key(key)) => tx.send(AppEvent::Key(key)),
                    Ok(Event::Resize(..)) => tx.send(AppEvent::Resize),
                    _ => Ok(()),
                }
            } else {
                tx.send(AppEvent::Tick)
            };
            if sent.is_err() {
                break;
            }
        }
    });
}

#[tokio::main]
async fn main() -> io::Result<()> {
    let (tx, mut rx) = mpsc::unbounded_channel();
    let mut app = App::new(tx.clone());
    app.refresh_models();
    spawn_input(tx);

    let mut terminal = ratatui::init();
    let result = run(&mut terminal, &mut app, &mut rx).await;
    ratatui::restore();
    result
}

async fn run(
    terminal: &mut ratatui::DefaultTerminal,
    app: &mut App,
    rx: &mut mpsc::UnboundedReceiver<AppEvent>,
) -> io::Result<()> {
    while !app.should_quit {
        terminal.draw(|frame| ui::draw(frame, app))?;
        let Some(event) = rx.recv().await else { break };
        app.handle(event);
        while let Ok(event) = rx.try_recv() {
            app.handle(event);
        }
    }
    Ok(())
}
