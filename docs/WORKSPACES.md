# Workspaces
Morgan features an embedded tiling workspace system for displaying interactive content alongside the assistant. Workspaces live inside the main application window, without opening additional windows or creating separate Morgan instances.

## Keyboard shortcuts
Workspaces are managed entirely through keyboard shortcuts, keeping the interface clean and free of unnecessary toolbars.

| Shortcut         | Action                                |
|------------------|---------------------------------------|
| `Ctrl + N`       | Open a new workspace panel.           |
| `Ctrl + N`, then `←` / `→` / `↑` / `↓` | Open a panel in that direction from the active panel. |
| `Ctrl + W`       | Close the active panel.               |
| `Ctrl + N`, then `4` | Open an embedded terminal.        |
| `Ctrl + Alt + ←` | Focus the nearest panel to the left.  |
| `Ctrl + Alt + →` | Focus the nearest panel to the right. |
| `Ctrl + Alt + ↑` | Focus the nearest panel above.        |
| `Ctrl + Alt + ↓` | Focus the nearest panel below.        |
| `Ctrl + +`      | Enlarge the complete interface.       |
| `Ctrl + -`      | Reduce the complete interface.        |
| `Ctrl + 0`      | Restore 100% interface zoom.          |

The active panel is highlighted, and closing it automatically selects another available panel.

After `Ctrl + N`, press an arrow or a workspace number within 700 ms. You can
keep Ctrl held while pressing the second key. The chord opens only one panel;
without a second key, a new workspace opens automatically when that interval ends.

Interface zoom changes in 10% steps, from 50% to 200%, and is remembered between
sessions. `Ctrl + =` also enlarges the interface on keyboards where `+` requires
Shift. Zoom scales the workspace headers and their contents together, including
the editor, terminal, diagrams, buttons and custom-drawn controls. New workspaces
inherit the current zoom. Existing editor contents and terminal sessions stay open.
When the scaled panels need more space than the screen provides, scrollbars keep
the rest of the interface reachable.

## Web links

Web searches and website requests from the assistant, web links in the Nova
diary, YouTube selections and the repository link open in the operating system's
default browser.

## Nova

Nova is Morgan's reminders, events and agenda workspace. Open it from the command
palette (`Ctrl + K`, then "Nova") or with `Ctrl + Alt + N`. `Ctrl + L`, or "Open diary" in the palette, opens it straight on the
Diary, and `Ctrl + J`, or "Open journal", straight on the Journal, reusing a Nova panel that is already open. It lives inside a
workspace panel and uses Morgan's theme, fonts and animations.

A new workspace shows a single Nova star in place of the row of buttons. Press it to
slide out the workspace buttons (Morgan, Editor, Settings and Terminal) and
press it again to fold them. `Ctrl + click` on the star opens Nova in that panel instead.

Its sidebar is part of the panel and has four buttons: Home, Notifications, Me and Search.
It folds to an icon strip with a slide when you click the Nova star, and in narrow
panels it folds by itself. Nova opens on Home.

Home, Notifications and Me each open a grid of square tiles, one per section, with the
section's icon and its name below. The grid has up to three columns and reflows as the
panel is resized, to two and then one column with scrolling when it gets narrow. Click a
tile to open its section, and the small "‹ Home" line above the section's title, or the
active sidebar button, returns to the grid. Search opens directly.

- **Home** holds Agenda, Events, Calendar and Week.
- **Notifications** holds Reminders.
- **Me** holds Diary, Journal and Memories.

The sections:

- **Agenda** lists overdue reminders, then each of the next 14 days that has
  something on it.
- **Reminders** keeps pending and completed reminders. Tick the circle to complete one.
- **Events** lists upcoming and past events, with a time or all day.
- **Diary** is Morgan's memory one day at a time, with that day's agenda, what Morgan
  remembers and the conversations held (see [MEMORY.md](MEMORY.md)). Its icon is a scroll.
- **Journal** is the user's own record, one day at a time and separate from the Diary:
  write an entry in the box (`Ctrl + Enter` adds it), or tell the assistant about the
  day and it writes the entry down in the first person with light cleanup. Entries show who
  wrote them, and can be edited or deleted. `Ctrl + J`, or "Open journal" in the command
  palette, opens it.
- **Week** reviews one week at a time: reminders done, pending and missed, events, journal
  entries, conversations and new memories, a row for each day that has activity, and a short
  summary written by the model from those facts, including the journal entries. Click a day
  to open it in the Diary.
- **Search** looks for a word in reminders, events, the conversations of each diary day and
  journal entries. Clicking a diary day opens it in the Diary, and clicking a journal entry
  opens the Journal on that day.
- **Calendar** shows a week, month or year. Click a day in the month or year to drill
  into its week, click a month name in the year to open that month, and double-click a
  slot in the week to create an event there.

The **+** button, or clicking any entry, opens an overlay to create, edit or delete a
reminder or an event. Reminders take a date and an `HH:mm` time; events take a start
and an end, or last all day. Dates are picked from a month picker.

Reminders live in `~/.morgan/nova/reminders.sqlite3`, events in
`~/.morgan/nova/events.sqlite3` and journal entries in `~/.morgan/nova/journal.sqlite3`,
three independent SQLite databases that use only Python's standard library. Times are stored as local wall-clock times. While Morgan runs, a due
reminder is announced as a Windows notification within about 30 seconds; reminders
that were already more than a day overdue when Morgan started are not announced, but stay
marked as overdue.

## Song

When a song starts playing, a Now playing panel opens by itself to the right of the
active panel. It is shown once per song: if you close it, it stays closed until a
different song starts or the player is closed and opened again.
Turn off "Open the song panel" in Settings to stop it from opening by itself; the song
detection keeps running but no panel is opened.

Only songs count, not videos or podcasts. Morgan reads the Windows media session of
Spotify, or of a browser playing YouTube Music or an auto-generated "Topic" track, and
ignores entries that carry no album, such as ordinary YouTube videos, plus Spotify ads.
When Spotify is authorized (see the Spotify settings in `~/.morgan/json/config.json`), Morgan
also asks the Spotify Web API once per song to confirm that it is a track rather than a
podcast episode, to take its exact album art, and it follows songs that play on another
Spotify device, such as a phone. Morgan never opens the browser to authorize Spotify for
this; it only uses an authorization that already exists, which any Spotify action
requested from the assistant creates.

The panel shows the album cover, the song, artist and album, the time elapsed and the
duration, and a progress bar. Click or drag the bar to seek. The previous, play or
pause and next buttons control the player that is playing the song, with Spotify's
Web API for songs on another device.

- The copy button, left of the playback controls, copies the name of the song to the
  clipboard and shows a tick for a moment.
- The scroll button asks the main model for a summary of at most 500 words, in the
  interface language, with the song's lyrics, themes and fun facts such as interviews
  with the singer or band and the history of the album. It opens in a Summary panel below
  the song panel, without greeting or introducing itself. It reads web search results and
  one page about the song, and never quotes the lyrics beyond a few words. Summaries are
  kept for the songs of the open panel.

Song detection runs in the background while Morgan is open, once per second on this
computer, and queries the Spotify Web API only when it is authorized.

## How tiling works
Morgan uses a binary tiling layout built with Qt splitters. Each new panel divides an existing workspace into two regions, alternating between horizontal and vertical splits.
Panels automatically share the available space. You can drag the separators between them to resize individual regions without affecting their content.
Opening and closing panels triggers smooth size transitions. When a panel closes, its neighboring panel expands into the available space, and the layout reorganizes without leaving an empty region.

## Moving panels
Drag a panel by its title bar and drop it onto another panel to exchange their positions.
The entire panel follows the pointer at its original size during the drag, anchored
to the point where its title bar was grabbed. The destination highlight remains
visible to indicate where it can be dropped.
Moving a panel preserves its embedded content and internal state, including any zoom or selection managed by that content. Only its position in the tiling layout changes.

## Independent content

Each panel acts as an independent container for interactive content, such as flowcharts and other visual tools.
Panels can be focused, resized, moved, and closed individually. Their content remains embedded in Morgan's main window, allowing multiple visualizations to coexist without interrupting the conversation.

### Terminal

The Terminal button sits immediately to the right of Settings in a new workspace.
It opens an independent, persistent shell inside the panel: PowerShell 7 (`pwsh.exe`) on Windows,
starting in `%USERPROFILE%`, or the user's shell in their home directory on Unix.
On Windows, the Terminal shell setting in Settings switches new terminals to Git Bash
(`bash --login -i`) when Git for Windows is installed. The same setting is the shell
`execute_command` uses when none is named; the model can still ask for `bash` or `pwsh`
per command.
Directory changes and environment variables persist within that terminal only.
Commands run with the same permissions as Morgan.

Type directly in the terminal; Enter submits input, Up/Down recall shell history,
and Tab is passed to the shell for completion. ANSI colors and cursor updates are
rendered in the panel, which resizes the console when its workspace changes size.
Use Ctrl+Shift+C/V or the context menu to copy/paste. Ctrl+C interrupts the running
command (or copies a selection); the Ctrl+C button always sends an interrupt.
Scroll up to browse the last 1,000 lines. After `exit`, Restart opens a fresh shell
in the home directory. Closing the panel ends its shell and running child processes;
hiding Morgan in mascot mode keeps the terminal running.

Install the terminal dependencies from `requirements.txt`: `pyte` and `pywinpty`
on Windows, or `pyte` and `ptyprocess` on Unix. The terminal supports ordinary shell
and interactive command input; advanced terminal protocols such as mouse reporting
and application-specific alternate-screen behavior are not implemented.
