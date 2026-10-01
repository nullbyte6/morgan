# Workspaces
Arlo features an embedded tiling workspace system for displaying interactive content alongside the assistant. Workspaces live inside the main application window, without opening additional windows or creating separate Arlo instances.

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

## Browser sessions

All browser panels share a persistent Arlo profile in `~/.arlo/browser`.
Cookies (including session cookies), local storage and site login state survive
closing panels and restarting Arlo. Sign in once inside Arlo to use the same
session in its other browser panels. Websites can still expire or revoke logins.
This profile does not import Chrome/Edge sessions or saved passwords, and it does
not provide a password manager. Logging out on a website also logs out the other
Arlo panels using that account.

### Extensions

The browser's **… Extensions** button opens its extension manager in a workspace panel.
Opening it again focuses the existing panel. Buttons stack in narrow panels, and
short panels scroll vertically to keep every control accessible. Install a
Manifest V3 extension from a folder containing `manifest.json`, a ZIP, or a CRX
file. CRX files are unpacked into Arlo's profile before installation. Installed extensions are enabled, copied into Arlo's profile,
and restored at startup with their last enabled/disabled state. Select an
extension to enable, disable or remove it; **Open panel** opens its action popup
in another workspace panel when one is available. All browser panels share the same extensions.

Extensions require Qt WebEngine 6.10 or newer. Compatibility depends on the
extension APIs supported by Qt WebEngine; not every Chrome extension will work.
Direct Chrome Web Store installation, Chrome Sync and Manifest V2 are not
supported by this manager. Bitwarden's current Manifest V3 CRX can be imported
with **Install ZIP**; its vault state then uses Arlo's persistent browser profile.

Web searches and website requests from the assistant open in the embedded Browser
workspace. Arlo reuses an existing browser panel or creates one, and restores the
main window if it is hidden. Search results remain available to the assistant for
reading and citation. Web links in conversation logs, YouTube selections and the
repository link also use this browser. If the embedded browser is unavailable,
Arlo reports an error instead of launching the system browser.

## Nova

Nova is Arlo's reminders, events and agenda workspace. Open it from the command
palette (`Ctrl + K`, then "Nova") or with `Ctrl + Alt + N`. It lives inside a
workspace panel and uses Arlo's theme, fonts and animations.

A new workspace shows a single Nova star in place of the row of buttons. Press it to
slide out the workspace buttons (Arlo, Logs, Browser, Editor, Settings and Terminal) and
press it again to fold them. `Ctrl + click` on the star opens Nova in that panel instead.

Its sidebar is part of the panel: it holds Agenda, Reminders, Events, Calendar and Diary,
and folds to an icon strip with a slide when you click the Nova star. In narrow
panels it folds by itself.

- **Agenda** lists overdue reminders, then each of the next 14 days that has
  something on it.
- **Reminders** keeps pending and completed reminders. Tick the circle to complete one.
- **Events** lists upcoming and past events, with a time or all day.
- **Diary** is Arlo's memory one day at a time, with that day's agenda, what Arlo
  remembers and the conversations held (see [MEMORY.md](MEMORY.md)).
- **Calendar** shows a week, month or year. Click a day in the month or year to drill
  into its week, click a month name in the year to open that month, and double-click a
  slot in the week to create an event there.

The **+** button, or clicking any entry, opens an overlay to create, edit or delete a
reminder or an event. Reminders take a date and an `HH:mm` time; events take a start
and an end, or last all day. Dates are picked from a month picker.

Reminders live in `~/.arlo/nova/reminders.sqlite3` and events in
`~/.arlo/nova/events.sqlite3`, two independent SQLite databases that use only Python's
standard library. Times are stored as local wall-clock times. While Arlo runs, a due
reminder is announced as a Windows notification within about 30 seconds; reminders
that were already more than a day overdue when Arlo started are not announced, but stay
marked as overdue.

## How tiling works
Arlo uses a binary tiling layout built with Qt splitters. Each new panel divides an existing workspace into two regions, alternating between horizontal and vertical splits.
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
Panels can be focused, resized, moved, and closed individually. Their content remains embedded in Arlo's main window, allowing multiple visualizations to coexist without interrupting the conversation.

### Terminal

The Terminal button sits immediately to the right of Settings in a new workspace.
It opens an independent, persistent shell inside the panel: PowerShell 7 (`pwsh.exe`) on Windows,
starting in `%USERPROFILE%`, or the user's shell in their home directory on Unix.
Directory changes and environment variables persist within that terminal only.
Commands run with the same permissions as Arlo.

Type directly in the terminal; Enter submits input, Up/Down recall shell history,
and Tab is passed to the shell for completion. ANSI colors and cursor updates are
rendered in the panel, which resizes the console when its workspace changes size.
Use Ctrl+Shift+C/V or the context menu to copy/paste. Ctrl+C interrupts the running
command (or copies a selection); the Ctrl+C button always sends an interrupt.
Scroll up to browse the last 1,000 lines. After `exit`, Restart opens a fresh shell
in the home directory. Closing the panel ends its shell and running child processes;
hiding Arlo in mascot mode keeps the terminal running.

Install the terminal dependencies from `requirements.txt`: `pyte` and `pywinpty`
on Windows, or `pyte` and `ptyprocess` on Unix. The terminal supports ordinary shell
and interactive command input; advanced terminal protocols such as mouse reporting
and application-specific alternate-screen behavior are not implemented.
