#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of morgan.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Full-screen dark terminal interface: a pyfiglet name, subtitles and a composer."""
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import fragment_list_to_text
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (ConditionalContainer, Dimension, Float, FloatContainer,
                                   HSplit, Layout, VSplit, Window, WindowAlign)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import (AfterInput, ConditionalProcessor, Processor,
                                              Transformation)
from prompt_toolkit.styles import Style

from src.init.config import load_dev_file
from src.init.file_tags import FILE_TAG_LIMIT, FILE_TAG_QUERY, find_file_tags
from src.init.tui import i18n
from src.init.tui.i18n import t
from src.init.tui.markdown import render_markdown
from src.init.nova.sections import Section
from src.init.tui.nova import NovaOverlay
from src.init.tui.overlays import Command, FileOverlay, ModelOverlay, PaletteOverlay, UpdateOverlay
from src.init.tui.palette import mix
from src.init.tui.session import TuiSession
from src.init.tui.shell import shell_command_text
from src.init.tui.text import banner, bold_fragments, elide, pad, subtitle_lines, width_of
from src.init.tui.widgets import ScrollControl, clicked, exact, rounded_box, style
from src.init.updates import Release, UpdateCancelled, available_releases, download, install, relaunch_command

log = logging.getLogger("assistant.tui")
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
BARS = " ▁▂▃▄▅▆▇█"
FADE_SECONDS = 0.18
REVEAL_SECONDS = 0.26
CONTENT_WIDTH = 100
_QUOTED_PATH = re.compile(r'"([^"\r\n]+)"|\'([^\'\r\n]+)\'|(\S+)')


@dataclass
class UpdateState:
    release: Release
    phase: str = "downloading"
    received: int = 0
    total: int = 0
    message: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)


def ease_out(progress: float) -> float:
    return 1 - (1 - min(1.0, max(0.0, progress))) ** 3


class Scroll:
    """Vertical position of a text box that follows new text until scrolled up."""

    def __init__(self):
        self.offset = 0
        self.follow = True
        self.total = 0
        self.height = 10

    def fit(self, total: int, height: int) -> int:
        self.total, self.height = total, max(1, height)
        limit = max(0, total - self.height)
        self.offset = limit if self.follow else min(self.offset, limit)
        return self.offset

    def move(self, delta: int) -> None:
        limit = max(0, self.total - self.height)
        self.offset = min(limit, max(0, self.offset + delta))
        self.follow = self.offset >= limit

    def reset(self, follow: bool = True) -> None:
        self.offset = 0
        self.follow = follow


class TagHighlighter(Processor):
    """Color @file references in the composer like the desktop's composer does."""

    def __init__(self, app):
        self.app = app

    def apply_transformation(self, transformation_input):
        fragments = transformation_input.fragments
        text = fragment_list_to_text(fragments)
        tags = find_file_tags(text, self.app.session.directory)
        if not tags:
            return Transformation(fragments)
        mark = style(self.app.palette["file_tag"])
        cells = [(fragment[0], character) for fragment in fragments for character in fragment[1]]
        for start, end, _name, _path in tags:
            for position in range(start, min(end, len(cells))):
                cells[position] = (cells[position][0] + " " + mark, cells[position][1])
        merged = []
        for cell_style, character in cells:
            if merged and merged[-1][0] == cell_style:
                merged[-1] = (cell_style, merged[-1][1] + character)
            else:
                merged.append((cell_style, character))
        return Transformation(merged)


class TagPopup:
    """Files of the working directory suggested after typing @."""

    def __init__(self, app):
        self.app = app
        self.entries = []
        self.index = 0
        self.start = -1

    @property
    def visible(self):
        return bool(self.entries) and self.start >= 0

    def hide(self):
        self.entries = []
        self.start = -1

    def update(self):
        app = self.app
        buffer = app.input
        if not app.normal() or not app.session.editable():
            self.hide()
            return
        document = buffer.document
        before = document.current_line_before_cursor
        match = FILE_TAG_QUERY.search(before)
        if match is None:
            self.hide()
            return
        query = (match.group(1) if match.group(1) is not None else match.group(2)).casefold()
        try:
            entries = [(entry.name, entry.is_dir()) for entry in os.scandir(app.session.directory)]
        except OSError:
            entries = []
        matches = [entry for entry in entries if query in entry[0].casefold()]
        matches.sort(key=lambda entry: (not entry[0].casefold().startswith(query),
                                        not entry[1], entry[0].casefold()))
        if not matches:
            self.hide()
            return
        self.entries = matches[:FILE_TAG_LIMIT]
        self.index = min(self.index, len(self.entries) - 1)
        self.start = document.cursor_position - len(before) + match.start()

    def move(self, step):
        if self.entries:
            self.index = (self.index + step) % len(self.entries)

    def accept(self, position=None):
        if not self.visible:
            return
        name = self.entries[self.index if position is None else position][0]
        buffer = self.app.input
        tag = f'@"{name}"' if re.search(r'[\s"]', name) else f"@{name}"
        removal = buffer.cursor_position - self.start
        self.hide()
        buffer.delete_before_cursor(removal)
        buffer.insert_text(tag + " ")


class TuiApp:
    def __init__(self, scheduler, prefs, palette, *, voice_enabled=True):
        self.scheduler = scheduler
        self.palette = palette
        self.session = TuiSession(scheduler, prefs, voice_enabled=voice_enabled)
        self.dialog = self.session.dialog
        self.version = load_dev_file()["version"]
        i18n.refresh()
        self.overlay = None
        self.update = None
        self.update_checking = False
        self.panel = Scroll()
        self.output = Scroll()
        self.tag_popup = TagPopup(self)
        self.ticker = None
        self.fade_from = self.fade_to = palette.state("idle")
        self.fade_start = -10.0
        self.quit_armed = 0.0
        self.exiting = False
        self.history_index = None
        self.history_draft = ""
        self.input = Buffer(
            multiline=True, history=InMemoryHistory(),
            read_only=Condition(lambda: not self.normal() or not self.session.editable()),
            on_text_changed=lambda _buffer: self.on_input_changed(),
            on_cursor_position_changed=lambda _buffer: self.on_input_changed())
        self.input_window = self.build_input_window()
        self.application = Application(
            layout=Layout(self.build_root(), focused_element=self.input_window),
            key_bindings=self.build_bindings(), style=self.build_style(),
            full_screen=True, mouse_support=True, erase_when_done=False)
        self.application.ttimeoutlen = 0.05
        self.application.timeoutlen = 0.2
        self.session.changed.connect(self.on_changed)
        self.session.draft_accepted.connect(self.on_draft_accepted)
        self.session.exit_requested.connect(self.exit)
        self.session.nova_changed.connect(self.on_nova_changed)
        self.session.nova_requested.connect(lambda: self.open_nova(Section.AGENDA))

    def build_style(self):
        return Style.from_dict({"": f"bg:{self.palette['surface']} fg:{self.palette['text']}"})

    def c(self, role):
        return self.palette[role]

    def normal(self):
        return self.overlay is None and not self.dialog.visible

    def size(self):
        return self.application.output.get_size()

    def columns(self):
        return self.size().columns

    def content_width(self):
        return max(10, min(self.columns() - 2, CONTENT_WIDTH))

    def composer_width(self):
        columns = self.columns()
        return max(10, min(columns - 2, max(44, min(110, int(columns * 0.62)))))

    def reveal(self):
        ready_at = self.session.ready_at
        if ready_at is None:
            return 0.0
        return ease_out((time.monotonic() - ready_at) / REVEAL_SECONDS)

    def tint(self, color):
        return mix(color, self.c("surface"), self.reveal())

    def state_color(self):
        now = time.monotonic()
        target = self.palette.state(self.session.visual_state)
        if target != self.fade_to:
            self.fade_from = self.blend(now)
            self.fade_to = target
            self.fade_start = now
        return self.blend(now)

    def blend(self, now):
        progress = ease_out((now - self.fade_start) / FADE_SECONDS)
        return mix(self.fade_to, self.fade_from, progress)

    def panel_visible(self):
        return self.session.response_visible

    def compact(self):
        return self.panel_visible() or self.size().rows < 20

    def spinner(self):
        return SPINNER[int(time.monotonic() * 8) % len(SPINNER)]

    def place_tag_popup(self):
        self.tag_float.left = (self.columns() - self.composer_width()) // 2 + 1
        self.tag_float.bottom = self.input_rows() + 3

    def on_input_changed(self):
        self.tag_popup.update()
        self.place_tag_popup()
        self.application.invalidate()

    def browse_history(self, step):
        history = self.session.history
        if not history:
            return
        if self.history_index is None:
            if step > 0:
                return
            self.history_draft = self.input.text
            index = len(history) - 1
        else:
            index = self.history_index + step
            if index < 0:
                return
        if index >= len(history):
            self.history_index = None
            text = self.history_draft
        else:
            self.history_index = index
            text = history[index]
        self.input.text = text
        self.input.cursor_position = len(text)

    def on_draft_accepted(self):
        self.history_index = None
        self.input.reset(append_to_history=True)
        self.tag_popup.hide()
        self.panel.reset()

    def on_changed(self):
        self.place_tag_popup()
        self.application.invalidate()
        self.ensure_ticker()

    def tick_interval(self):
        session = self.session
        now = time.monotonic()
        self.state_color()
        if (now - self.fade_start < FADE_SECONDS
                or (session.ready_at is not None and now - session.ready_at < REVEAL_SECONDS)):
            return 1 / 30
        if not session.ready and not session.failed:
            return 0.125
        if session.busy and not session.stopping and session.visual_state in ("processing", "executing"):
            return 0.125
        if session.shell is not None:
            return 0.25
        if self.dialog.visible or session.timer_started is not None:
            return 1.0
        return None

    def ensure_ticker(self):
        if self.ticker is None and not self.exiting:
            interval = self.tick_interval()
            if interval is not None:
                self.ticker = self.scheduler.later(interval, self.tick)

    def tick(self):
        self.ticker = None
        self.application.invalidate()
        self.ensure_ticker()

    def banner_lines(self):
        size = self.size()
        name = i18n.assistant_name()
        if self.compact():
            return (f"{name} {self.version}",)
        return banner(name, size.columns, size.rows)

    def banner_fragments(self):
        return [(style(self.state_color(), bold=True), "\n".join(self.banner_lines()))]

    def version_fragments(self):
        if self.compact():
            return []
        return [(style(self.c("text_muted")), self.version)]

    def status_fragments(self):
        session, palette = self.session, self.palette
        now = time.monotonic()
        if session.notice and now < session.notice_until:
            return [(style(palette["warning"]), elide(session.notice, self.columns() - 4))]
        if session.status_key:
            return [(style(palette["text_muted"]), f"{self.spinner()} {t(session.status_key)}")]
        if session.busy and not session.trail_text and not session.speaking and not session.stopping \
                and session.visual_state in ("processing", "executing", "writing"):
            return [(style(palette["text_muted"]), f"{self.spinner()} {t('status.thinking')}")]
        if session.recording:
            return [(style(palette["text_muted"]), t("voice.recording"))]
        if session.stopping:
            return [(style(palette["text_muted"]), t("status.stopping"))]
        return []

    def trail_fragments(self):
        session = self.session
        if session.trail_text and session.steps_enabled:
            return [(style(self.c("text_subtle"), italic=True),
                     elide(session.trail_text, self.columns() - 4))]
        return []

    def subtitle_height(self):
        session = self.session
        if not session.subtitles_enabled or self.panel_visible() or self.size().rows < 16:
            return 0
        return 3

    def subtitle_fragments(self):
        session = self.session
        if not self.subtitle_height() or not session.subtitle_text:
            return []
        lines = subtitle_lines(session.subtitle_text, self.content_width() - 4)
        text_style = style(self.c("text"))
        return bold_fragments("\n".join(lines), text_style, style(self.c("text"), bold=True))

    def panel_lines(self, width):
        session = self.session
        text = session.reply_text
        if not text.strip():
            return []
        return render_markdown(text, width, self.palette)

    def panel_fragments(self):
        window = self.panel_window.render_info
        height = window.window_height if window is not None else 10
        lines = self.panel_lines(self.content_width() - 2)
        first = self.panel.fit(len(lines), height)
        visible = lines[first:first + self.panel.height]
        fragments = []
        for position, line in enumerate(visible):
            fragments.extend(line)
            if position < len(visible) - 1:
                fragments.append(("", "\n"))
        return fragments

    def panel_title(self):
        session = self.session
        title = session.response_title or t("tui.response")
        return [(style(self.c("accent"), bold=True), " " + elide(title, self.content_width() - 12) + " ")]

    def panel_close(self):
        return [(style(self.c("text_muted")), " ", clicked(self.close_panel)),
                (style(self.c("text_muted"), bold=True), "×", clicked(self.close_panel)),
                (style(self.c("text_muted")), " ", clicked(self.close_panel))]

    def close_panel(self):
        self.session.response_visible = False
        self.session.notify()

    def output_lines(self):
        text = self.session.command_output
        return text.split("\n") if text else []

    def output_height(self):
        return max(1, min(10, len(self.output_lines()) or 1))

    def output_fragments(self):
        lines = self.output_lines()
        height = self.output_height()
        first = self.output.fit(len(lines), height)
        width = self.content_width() - 2
        code = style(self.c("code_block_text"), self.c("code_block_background"))
        shown = [elide(line.replace("\t", "    "), width) for line in lines[first:first + height]]
        if not shown:
            shown = [t("tui.shell_running")]
        return [(code, "\n".join(shown))]

    def output_title(self):
        session = self.session
        label = f"> {elide(session.last_command, 40)}"
        hint = f"{t('tui.shell_running')} " if session.shell is not None else ""
        return [(style(self.c("warning"), bold=True), " " + label + " "),
                (style(self.c("text_subtle")), hint)]

    def close_output(self):
        if not self.session.cancel_shell():
            self.session.dismiss_output()

    def output_close(self):
        return [(style(self.c("text_muted"), bold=True), " × ", clicked(self.close_output))]

    def chip_rows(self):
        items = list(self.session.attachments.values())
        width = self.composer_width()
        rows, row, used = [], [], 0
        for item in items:
            if item.status == "pending":
                detail, tone = t("ui.attachment_checking"), "text_subtle"
            elif item.status == "error":
                detail, tone = t("ui.attachment_error"), "error"
            else:
                detail = f"{item.extension.upper().lstrip('.') or 'TEXT'} · {item.size / 1024:.1f} KB"
                tone = "text_muted"
            name = elide(item.name, 26, middle=True)
            body = f" {name} · {detail} "
            size = width_of(body) + 3
            if row and used + size > width:
                rows.append(row)
                row, used = [], 0
            chip = style(self.tint(self.c("text")), self.tint(self.c("surface_raised")))
            note = style(self.tint(self.c(tone)), self.tint(self.c("surface_raised")))
            remove = clicked(lambda item_id=item.id: self.session.remove_attachment(item_id))
            row.append([(chip, " " + name), (note, f" · {detail} "),
                        (style(self.tint(self.c("text_muted")), self.tint(self.c("surface_raised")), bold=True),
                         "× ", remove), ("", "  ")])
            used += size + 2
        if row:
            rows.append(row)
        return rows

    def chips_fragments(self):
        fragments = []
        rows = self.chip_rows()
        for position, row in enumerate(rows):
            for chip in row:
                fragments.extend(chip)
            if position < len(rows) - 1:
                fragments.append(("", "\n"))
        return fragments

    def indicator_fragments(self):
        session, palette = self.session, self.palette
        width = self.composer_width()
        muted = style(self.tint(palette["text_muted"]))
        left = [(muted, session.timer_label())]
        name = Path(session.directory).resolve()
        directory = name.name or str(name)
        left.append((style(self.tint(palette["text_secondary"])), "  ▸ " + elide(directory, 24, middle=True)))
        if session.branch:
            left.append((style(self.tint(palette["git_branch"])), "  ◆ " + elide(session.branch, 24)))
        if session.runner.session.private:
            left.append((style(self.tint(palette["private_indicator"]), bold=True),
                         "  ● " + t("status.private"), clicked(session.toggle_private)))
        mode = session.permission_mode.upper()
        right_permission = f"{t('ui.permissions')} · {mode}"
        model = session.model or "…"
        right = [(style(self.tint(palette["warning" if mode == "AUTO" else "text_muted"])),
                  right_permission, clicked(session.toggle_permission_mode)),
                 (muted, "  "),
                 (style(self.tint(palette["text_secondary"])), elide(model, 28) + " ▾",
                  clicked(self.open_models))]
        used = sum(width_of(text) for _style, text, *_ in left + right)
        if used >= width:
            return left[:2] + [("", " ")] + right[-1:]
        return left + [("", " " * (width - used))] + right

    def placeholder(self):
        session = self.session
        if not session.ready:
            return ""
        if session.busy:
            return t("ui.steering_input")
        full = t("tui.input")
        return full if width_of(full) + 8 <= self.composer_width() else t("ui.input")

    def build_input_window(self):
        control = BufferControl(
            buffer=self.input,
            input_processors=[
                TagHighlighter(self),
                ConditionalProcessor(
                    AfterInput(lambda: self.placeholder(),
                               style=style(self.c("text_subtle"))),
                    filter=Condition(lambda: not self.input.text))],
            focusable=True)
        return Window(control, height=Dimension(min=1, max=4), wrap_lines=True,
                      style=lambda: style(self.tint(self.c("text"))))

    def attach_fragments(self):
        enabled = self.session.editable()
        color = self.tint(self.c("text_muted" if enabled else "text_disabled"))
        fragment = (style(color, bold=True), " + ")
        return [fragment + (clicked(self.open_files),) if enabled else fragment]

    def meter_fragments(self):
        session = self.session
        levels = session.levels or []
        if session.recording and not levels:
            levels = [0.0] * 15
        layers = [self.c(f"audio_wave_layer_{index}") for index in (1, 2, 3, 4)]
        fragments = [(style(self.c("accent"), bold=True), " ● ")]
        for position, level in enumerate(levels):
            character = BARS[min(len(BARS) - 1, int(max(0.0, min(1.0, level)) * (len(BARS) - 1) + 0.5))]
            fragments.append((style(layers[position * 4 // max(1, len(levels))]), character * 2))
        return fragments

    def send_state(self):
        return self.session.send_state(bool(self.input.text.strip()) or bool(self.session.attachments))

    def send_fragments(self):
        kind, enabled = self.send_state()
        glyph = {"stop": "■", "send": "↑", "mic": "●"}[kind]
        color = self.tint(self.c("accent") if enabled else self.c("text_disabled"))
        action = clicked(lambda: self.session.primary_action(self.input.text)) if enabled else None
        rows = [("╭───╮", None), (f"│ {glyph} │", action), ("╰───╯", None)]
        fragments = []
        for position, (text, handler) in enumerate(rows):
            is_middle = position == 1
            fragment = (style(color, bold=is_middle), text)
            fragments.append(fragment + (handler,) if handler else fragment)
            if position < len(rows) - 1:
                fragments.append(("", "\n"))
        return fragments

    def progress_fragments(self):
        session, palette = self.session, self.palette
        view = session.presentation.view
        width = self.progress_width()
        state = view.state
        tone = {"running": "accent", "waiting": "warning", "error": "error",
                "finished": "success", "stopped": "text_muted"}[state]
        inner = width - 4
        title = elide(view.title or t("task_progress.pending_title"), inner - 2)
        count = t("task_progress.step_count", completed=view.completed, total=view.started)
        if state == "running":
            detail = (t("task_progress.executing", step=view.completed + 1)
                      if view.completed < view.started else "")
        elif state == "waiting":
            detail = t("activity." + view.activity[0])
        else:
            detail = t("task_progress." + state)
        summary = t("task_progress.summary", detail=detail, count=count)
        total = max(1, view.started)
        filled = min(inner, int(inner * min(view.completed, total) / total))
        border = style(palette[tone])
        text = style(palette["text"])
        muted = style(palette["text_muted"])
        lines = [[(border, "╭"), (style(palette[tone], bold=True), " " + pad(title, inner - 2)),
                  (style(palette["text_muted"], bold=True), "×", clicked(self.dismiss_progress)),
                  (border, " ╮")]]
        lines.append([(border, "│ "), (style(palette[tone]), "█" * filled),
                      (style(palette["border"]), "░" * (inner - filled)), (border, " │")])
        for line in (elide(summary, inner),):
            lines.append([(border, "│ "), (muted, pad(line, inner)), (border, " │")])
        if view.step_detail:
            kind, tool, subject, step = view.step_detail
            detail = t("task_progress.step_" + kind, tool=tool)
            if subject and kind != "checkpoint":
                detail += " — " + subject
            step_text = t("task_progress.step_detail", step=step, detail=detail)
            lines.append([(border, "│ "), (text, pad(elide(step_text, inner), inner)), (border, " │")])
        lines.append([(border, "╰" + "─" * (inner + 2) + "╯")])
        fragments = []
        for position, line in enumerate(lines):
            fragments.extend(line)
            if position < len(lines) - 1:
                fragments.append(("", "\n"))
        return fragments

    def progress_height(self):
        return 5 if self.session.presentation.view.step_detail else 4

    def progress_width(self):
        return max(24, min(48, self.columns() - 4))

    def dismiss_progress(self):
        self.session.progress_dismissed = True
        self.session.notify()

    def update_fragments(self):
        update, palette = self.update, self.palette
        if update is None:
            return []
        width = self.update_width()
        inner = width - 4
        tone = {"downloading": "accent", "installing": "success", "failed": "error"}[update.phase]
        if update.phase == "downloading":
            title = t("update.downloading", version=update.release.version)
            if update.total:
                filled = min(inner, inner * update.received // update.total)
                detail = t("update.progress", received=f"{update.received / 1024 ** 2:.1f}",
                           total=f"{update.total / 1024 ** 2:.1f}", percent=update.received * 100 // update.total)
            else:
                filled = 0
                detail = t("update.progress_unknown", received=f"{update.received / 1024 ** 2:.1f}")
        elif update.phase == "installing":
            title = t("update.installing", version=update.release.version)
            filled, detail = inner, t("update.restarting")
        else:
            title = t("update.failed", version=update.release.version)
            filled, detail = inner, update.message
        border = style(palette[tone])
        close = ((style(palette["text_muted"], bold=True), "×", clicked(self.dismiss_update))
                 if update.phase != "installing" else (border, "─"))
        lines = [[(border, "╭"), (style(palette[tone], bold=True), " " + pad(elide(title, inner - 2), inner - 2)),
                  close, (border, " ╮")],
                 [(border, "│ "), (style(palette[tone]), "█" * filled),
                  (style(palette["border"]), "░" * (inner - filled)), (border, " │")],
                 [(border, "│ "), (style(palette["text_muted"]), pad(elide(detail, inner), inner)), (border, " │")],
                 [(border, "╰" + "─" * (inner + 2) + "╯")]]
        fragments = []
        for position, line in enumerate(lines):
            fragments.extend(line)
            if position < len(lines) - 1:
                fragments.append(("", "\n"))
        return fragments

    def update_width(self):
        return max(24, min(64, self.columns() - 4))

    def dismiss_update(self):
        update = self.update
        if update is None or update.phase == "installing":
            return
        update.cancel.set()
        self.update = None
        self.application.invalidate()

    def check_updates(self):
        if self.update_checking or self.update is not None:
            return
        self.update_checking = True
        self.session.flash(t("update.checking"), 30)

        def run():
            try:
                result, error = available_releases(self.version), None
            except Exception as failure:
                log.exception("The releases could not be read")
                result, error = [], failure
            self.scheduler.post(self.show_updates, result, error)

        threading.Thread(target=run, name="update-check", daemon=True).start()

    def show_updates(self, releases, error):
        self.update_checking = False
        if error is not None:
            self.session.flash(t("update.check_failed", error=error))
        elif not releases:
            self.session.flash(t("update.up_to_date", version=self.version))
        else:
            self.session.notice_until = 0
            self.tag_popup.hide()
            self.overlay = UpdateOverlay(releases)
            self.application.invalidate()

    def start_update(self, release):
        update = self.update = UpdateState(release)
        self.application.invalidate()

        def progress(received, total):
            self.scheduler.post(self.on_update_progress, update, received, total)

        def run():
            try:
                path = download(release, progress, update.cancel)
            except UpdateCancelled:
                return
            except Exception as error:
                log.exception("The update could not be downloaded")
                self.scheduler.post(self.on_update_failed, update, t("ui.error", error=error))
                return
            self.scheduler.post(self.on_update_downloaded, update, path)

        threading.Thread(target=run, name="update-download", daemon=True).start()

    def on_update_progress(self, update, received, total):
        if update is self.update and update.phase == "downloading":
            update.received, update.total = received, total
            self.application.invalidate()

    def on_update_failed(self, update, message):
        if update is self.update:
            update.phase, update.message = "failed", message
            self.application.invalidate()

    def on_update_downloaded(self, update, path):
        if update is not self.update:
            return
        update.phase = "installing"
        self.application.invalidate()
        try:
            install(path, *relaunch_command(terminal=True))
        except Exception as error:
            log.exception("The installer could not be started")
            self.on_update_failed(update, t("ui.error", error=error))
            return
        if self.session.busy and not self.session.stopping:
            self.session.stop_response()
        self.scheduler.later(0.8, self.exit)

    def overlay_rows(self):
        overlay = self.overlay
        tall, margin = (overlay.tall, overlay.margin) if overlay is not None else (12, 10)
        return max(3, min(tall, self.size().rows - margin))

    def overlay_width(self):
        wide = self.overlay.wide if self.overlay is not None else 72
        return max(24, min(wide, self.columns() - 4))

    def overlay_fragments(self):
        overlay = self.overlay
        if overlay is None:
            return []
        lines = overlay.lines(self, self.overlay_width() - 2, self.overlay_rows())
        fragments = []
        for position, line in enumerate(lines):
            fragments.extend(line)
            if position < len(lines) - 1:
                fragments.append(("", "\n"))
        return fragments

    def overlay_title(self):
        title = self.overlay.title() if self.overlay is not None else ""
        return [(style(self.c("accent"), bold=True), f" {title} ")]

    def overlay_hint(self):
        hint = self.overlay.hint() if self.overlay is not None else ""
        return [(style(self.c("text_subtle")), " " + elide(hint, self.overlay_width() - 4))]

    def overlay_height(self):
        overlay = self.overlay
        if overlay is None:
            return 3
        lines = len(overlay.lines(self, self.overlay_width() - 2, self.overlay_rows()))
        return max(1, min(self.overlay_rows(), lines)) + 1

    def dialog_fragments(self):
        return self.dialog.fragments(self.palette, self.columns())

    def dialog_height(self):
        return self.dialog.height(self.palette, self.columns())

    def build_root(self):
        center_width = lambda: exact(self.content_width())
        composer_width = lambda: exact(self.composer_width())
        centered = lambda text, **options: Window(
            FormattedTextControl(text), align=WindowAlign.CENTER, **options)

        self.panel_window = Window(
            ScrollControl(self.panel_fragments, self.panel.move), wrap_lines=False,
            height=Dimension(weight=1))
        panel_box = rounded_box(
            self.panel_window, lambda: style(self.c("border_strong")),
            top_left=self.panel_title, top_right=self.panel_close, height=Dimension(weight=1))
        output_box = rounded_box(
            Window(ScrollControl(self.output_fragments, self.output.move), wrap_lines=False,
                   height=lambda: exact(self.output_height())),
            lambda: style(self.c("border")), top_left=self.output_title, top_right=self.output_close)

        center = HSplit([
            ConditionalContainer(Window(height=1), Condition(lambda: not self.compact())),
            centered(self.banner_fragments, height=lambda: exact(len(self.banner_lines()))),
            ConditionalContainer(
                centered(self.version_fragments, height=1), Condition(lambda: not self.compact())),
            Window(height=1),
            centered(self.trail_fragments, height=1),
            centered(self.status_fragments, height=1),
            centered(self.subtitle_fragments, height=lambda: exact(self.subtitle_height())),
            ConditionalContainer(panel_box, Condition(self.panel_visible)),
            ConditionalContainer(
                output_box, Condition(lambda: self.session.command_output_visible and not self.panel_visible())),
        ], width=center_width, height=self.center_height)

        chips = ConditionalContainer(
            Window(FormattedTextControl(self.chips_fragments), wrap_lines=False,
                   height=lambda: exact(max(1, len(self.chip_rows())))),
            Condition(lambda: bool(self.session.attachments)))
        indicators = Window(FormattedTextControl(self.indicator_fragments), height=1)
        meter = Window(FormattedTextControl(self.meter_fragments), height=1)
        input_body = VSplit([
            Window(width=1),
            ConditionalContainer(self.input_window, Condition(lambda: not self.session.recording)),
            ConditionalContainer(meter, Condition(lambda: self.session.recording)),
            Window(FormattedTextControl(self.attach_fragments), width=3, height=1,
                   dont_extend_width=True),
        ])
        frame = rounded_box(
            input_body,
            lambda: style(self.tint(self.c("accent") if self.session.recording else self.c("border_strong"))))
        send = Window(FormattedTextControl(self.send_fragments), width=5, height=3,
                      dont_extend_width=True)
        composer = HSplit([
            chips, indicators,
            VSplit([frame, Window(width=1),
                    HSplit([Window(height=Dimension(weight=1)), send], width=exact(5))]),
        ], width=composer_width)

        body = HSplit([
            ConditionalContainer(Window(height=Dimension(weight=1)), Condition(lambda: not self.panel_visible())),
            VSplit([Window(width=Dimension(weight=1)), center, Window(width=Dimension(weight=1))]),
            ConditionalContainer(Window(height=Dimension(weight=1)), Condition(lambda: not self.panel_visible())),
            VSplit([Window(width=Dimension(weight=1)), composer, Window(width=Dimension(weight=1))]),
            Window(height=1),
        ])

        progress = Float(
            content=ConditionalContainer(
                Window(FormattedTextControl(self.progress_fragments),
                       width=lambda: exact(self.progress_width()),
                       height=lambda: exact(self.progress_height())),
                Condition(lambda: self.session.progress_visible())),
            left=1, top=0)

        update = Float(
            content=ConditionalContainer(
                Window(FormattedTextControl(self.update_fragments),
                       width=lambda: exact(self.update_width()), height=4),
                Condition(lambda: self.update is not None)),
            bottom=6)

        self.tag_float = tag_popup = Float(
            content=ConditionalContainer(
                Window(FormattedTextControl(self.tag_fragments), height=lambda: exact(self.tag_height()),
                       width=lambda: exact(self.tag_width()), style=f"bg:{self.c('surface_raised')}"),
                Condition(lambda: self.tag_popup.visible and self.normal())),
            left=1, bottom=4)

        overlay_body = HSplit([
            Window(FormattedTextControl(self.overlay_fragments), wrap_lines=False,
                   height=lambda: exact(self.overlay_height() - 1)),
            Window(FormattedTextControl(self.overlay_hint), height=1),
        ], style=f"bg:{self.c('surface_raised')}")
        overlay = Float(
            content=ConditionalContainer(
                rounded_box(overlay_body, lambda: style(self.c("accent")), top_left=self.overlay_title),
                Condition(lambda: self.overlay is not None and not self.dialog.visible)),
            width=lambda: self.overlay_width(), height=lambda: self.overlay_height() + 2)

        dialog_body = Window(FormattedTextControl(self.dialog_fragments), wrap_lines=False,
                             style=f"bg:{self.c('surface_raised')}")
        confirm = Float(
            content=ConditionalContainer(
                rounded_box(dialog_body, lambda: self.dialog.border(self.palette)),
                Condition(lambda: self.dialog.visible)),
            width=lambda: self.dialog.width(self.columns()), height=lambda: self.dialog_height() + 2)

        return FloatContainer(content=body, floats=[progress, update, tag_popup, overlay, confirm])

    def center_height(self):
        if self.panel_visible():
            return Dimension(weight=1)
        compact = self.compact()
        rows = (0 if compact else 2) + len(self.banner_lines()) + 3 + self.subtitle_height()
        if self.session.command_output_visible:
            rows += self.output_height() + 2
        return exact(rows)

    def toggle_recording(self):
        if self.session.voice_active():
            self.session.primary_action("")
        else:
            self.session.start_recording()

    def tag_fragments(self):
        popup = self.tag_popup
        P = self.palette
        lines = []
        width = self.tag_width()
        rows = min(8, len(popup.entries))
        first = 0 if len(popup.entries) <= rows else min(max(0, popup.index - rows // 2),
                                                          len(popup.entries) - rows)
        for position in range(first, first + rows):
            name, is_dir = popup.entries[position]
            label = " " + elide(name + ("/" if is_dir else ""), width - 2)
            selected = position == popup.index
            row_style = (style(P["on_accent"], P["accent"], bold=True) if selected
                         else style(P["text"], P["surface_raised"]))
            lines.append((row_style, pad(label, width), clicked(lambda position=position: popup.accept(position))))
            lines.append(("", "\n"))
        return lines[:-1]

    def input_rows(self):
        info = self.input_window.render_info
        return max(1, info.window_height) if info is not None else 1

    def tag_height(self):
        return max(1, min(8, len(self.tag_popup.entries)))

    def tag_width(self):
        longest = max((width_of(name) + 3 for name, _dir in self.tag_popup.entries), default=12)
        return max(16, min(44, longest + 1, self.columns() - 4))

    def commands(self):
        session = self.session
        return [
            Command("task.stop", lambda: t("palette.stop_task"), session.stop_current_task,
                    ("stop task", "detener tarea", "cancelar"), session.can_stop_task),
            Command("task.pause", lambda: t("palette.pause_task"), session.pause_current_task,
                    ("pause task", "pausar tarea"), session.can_pause_task),
            Command("task.resume", lambda: t("palette.resume_task"), session.resume_current_task,
                    ("resume task", "resumir tarea", "reanudar", "continuar"), session.can_resume_task),
            Command("attach", lambda: t("ui.attach_files"), self.open_files,
                    ("attach", "adjuntar", "file", "archivo"), session.editable),
            Command("voice.record", lambda: t("voice.record"), self.toggle_recording,
                    ("record", "voice", "grabar", "voz", "mic"),
                    lambda: session.ready and not session.busy and session.submitting is None),
            Command("response.last", lambda: t("tui.cmd_last_response"), self.show_last_response,
                    ("response", "respuesta", "last", "ultima"), lambda: bool(session.last_reply)),
            Command("voice.mute",
                    lambda: t("tui.cmd_unmute" if session.muted else "ui.mute"),
                    session.toggle_mute, ("mute", "silenciar", "voice", "voz"),
                    lambda: session.voice_enabled),
            Command("ui.subtitles",
                    lambda: t("tui.cmd_hide_subtitles" if session.subtitles_enabled else "tui.cmd_show_subtitles"),
                    session.toggle_subtitles, ("subtitles", "subtitulos", "subtítulos")),
            Command("ui.steps",
                    lambda: t("tui.cmd_hide_steps" if session.steps_enabled else "tui.cmd_show_steps"),
                    session.toggle_steps, ("steps", "pasos", "ephemeral")),
            Command("ui.language", lambda: t("tui.cmd_language"), session.toggle_language,
                    ("language", "idioma", "english", "spanish", "español", "chinese", "中文", "french",
                     "français", "german", "deutsch", "portuguese", "português", "japanese", "日本語",
                     "russian", "русский", "korean", "한국어", "italian", "italiano")),
            Command("ui.permissions",
                    lambda: t("tui.cmd_permissions", mode=session.permission_mode.upper()),
                    session.toggle_permission_mode, ("permissions", "permisos", "ask", "auto")),
            Command("session.private", lambda: t("palette.private"), session.toggle_private,
                    ("private", "privacy", "privado", "privacidad", "incognito", "隐私")),
            Command("ui.model", lambda: t("tui.cmd_model"), self.open_models, ("model", "modelo"),
                    lambda: session.ready and not session.busy),
            Command("nova.open", lambda: t("palette.nova"), lambda: self.open_nova(Section.AGENDA),
                    ("nova", "agenda", "reminders", "events", "calendar", "recordatorios", "eventos",
                     "calendario", "日程"), lambda: self.session.nova is not None),
            Command("nova.diary", lambda: t("palette.diary"), lambda: self.open_nova(Section.DIARY),
                    ("diary", "diario", "日记"), lambda: self.session.nova is not None),
            Command("nova.week", lambda: t("nova.section.review"), lambda: self.open_nova(Section.REVIEW),
                    ("week", "review", "semana", "resumen", "本周"), lambda: self.session.nova is not None),
            Command("nova.memories", lambda: t("nova.section.memories"),
                    lambda: self.open_nova(Section.MEMORIES),
                    ("memories", "pin", "recuerdos", "记忆"), lambda: self.session.nova is not None),
            Command("app.update", lambda: t("palette.update"), self.check_updates,
                    ("update", "upgrade", "version", "release", "actualizar", "actualización", "versión", "更新"),
                    lambda: not self.update_checking and self.update is None),
            Command("app.quit", lambda: t("tray.quit"), self.request_exit,
                    ("quit", "exit", "salir", "cerrar")),
        ]

    def open_palette(self):
        if not self.session.ready or self.dialog.visible:
            return
        self.tag_popup.hide()
        self.overlay = PaletteOverlay(self.commands())
        self.application.invalidate()

    def open_files(self):
        if not self.session.editable() or self.dialog.visible:
            return
        self.tag_popup.hide()
        self.overlay = FileOverlay(self.session.directory)
        self.application.invalidate()

    def open_models(self):
        session = self.session
        if not session.ready or session.busy or self.dialog.visible:
            return
        self.tag_popup.hide()
        session.refresh_models()
        overlay = ModelOverlay()
        if session.model in session.models:
            overlay.index = session.models.index(session.model)
        self.overlay = overlay
        self.application.invalidate()

    def open_nova(self, section):
        if self.session.nova is None or self.dialog.visible:
            return
        self.tag_popup.hide()
        if isinstance(self.overlay, NovaOverlay):
            self.overlay.show_section(section)
        else:
            self.overlay = NovaOverlay(self, section)
        self.application.invalidate()

    def on_nova_changed(self):
        if isinstance(self.overlay, NovaOverlay):
            self.overlay.changed()
        self.application.invalidate()

    def close_overlay(self):
        self.overlay = None
        self.application.invalidate()

    def show_last_response(self):
        session = self.session
        if session.last_reply:
            session.reply_text = session.last_reply
            session.response_title = ""
            session.response_visible = True
            self.panel.reset(follow=False)
            session.notify()

    def request_exit(self):
        if self.session.busy and not self.session.stopping:
            self.session.flash(t("status.close_wait"))
            return
        self.exit()

    def exit(self):
        if self.exiting:
            return
        self.exiting = True
        if self.application.is_running:
            self.application.exit()

    def pasted_paths(self, text):
        candidates = []
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line:
                continue
            tokens = [match.group(1) or match.group(2) or match.group(3)
                      for match in _QUOTED_PATH.finditer(line)]
            candidates.extend(tokens)
        if not candidates:
            return []
        paths = []
        for candidate in candidates:
            path = Path(candidate).expanduser()
            if not path.is_absolute() and not candidate.startswith((".", "~")):
                return []
            if not path.is_file():
                return []
            paths.append(str(path))
        return paths

    def submit(self):
        session = self.session
        text = self.input.text
        command = shell_command_text(text)
        if command is not None:
            if session.run_shell(command):
                if not session.history or session.history[-1] != text.strip():
                    session.history.append(text.strip())
                self.history_index = None
                self.input.reset(append_to_history=True)
            return
        session.send_message(text)

    def interrupt(self):
        session = self.session
        if self.dialog.visible:
            self.dialog.cancel()
        elif self.overlay is not None:
            self.close_overlay()
        elif session.cancel_shell():
            return
        elif session.busy and not session.stopping:
            session.stop_response()
        elif session.recording:
            session.primary_action("")
        elif self.input.text:
            self.input.reset()
            session.attachments.clear()
            session.notify()
        elif time.monotonic() - self.quit_armed < 1.5:
            self.request_exit()
        else:
            self.quit_armed = time.monotonic()
            session.flash(t("tui.quit_hint"), 1.5)

    def escape(self):
        session = self.session
        if self.dialog.visible:
            self.dialog.cancel()
        elif self.overlay is not None:
            if not self.overlay.back(self):
                self.close_overlay()
            self.application.invalidate()
        elif self.tag_popup.visible:
            self.tag_popup.hide()
            self.application.invalidate()
        elif session.cancel_shell():
            return
        elif session.busy and not session.stopping:
            session.stop_response()
        elif session.recording:
            session.primary_action("")
        elif self.panel_visible():
            self.close_panel()
        elif session.command_output_visible:
            session.dismiss_output()

    def build_bindings(self):
        kb = KeyBindings()
        normal = Condition(self.normal)
        overlay_open = Condition(lambda: self.overlay is not None and not self.dialog.visible)
        confirming = Condition(lambda: self.dialog.visible)
        modal = overlay_open | confirming
        popup = Condition(lambda: self.tag_popup.visible)
        editable = Condition(self.session.editable)
        scrollable = Condition(lambda: self.normal() and (
            self.panel_visible() or self.session.command_output_visible))

        @kb.add(Keys.Any, filter=modal)
        def _(event):
            data = event.data
            if self.dialog.visible:
                self.dialog.on_text(data)
            elif self.overlay is not None and len(data) == 1 and data.isprintable():
                self.overlay.on_text(self, data)
                self.application.invalidate()

        @kb.add(Keys.BracketedPaste, filter=modal)
        def _(event):
            if self.overlay is not None and isinstance(self.overlay, PaletteOverlay):
                self.overlay.on_text(self, event.data)
                self.application.invalidate()

        @kb.add(Keys.BracketedPaste, filter=normal)
        def _(event):
            data = event.data.replace("\r\n", "\n").replace("\r", "\n")
            paths = self.pasted_paths(data) if self.session.editable() else []
            if paths:
                self.session.add_files(paths)
            else:
                event.current_buffer.insert_text(data)

        for name in ("up", "down", "pageup", "pagedown", "home", "end", "tab", "s-tab", "left", "right",
                     "backspace", "delete"):
            @kb.add(name, filter=overlay_open)
            def _(event, name=name):
                self.overlay.on_key(self, name)
                self.application.invalidate()

        @kb.add("enter", filter=overlay_open)
        def _(event):
            self.overlay.on_key(self, "enter")
            self.application.invalidate()

        @kb.add("c-u", filter=overlay_open)
        def _(event):
            self.overlay.on_key(self, "clear")
            self.application.invalidate()

        for key in ("left", "right", "up", "down", "tab", "s-tab"):
            @kb.add(key, filter=confirming)
            def _(event, key=key):
                self.dialog.move(key)

        @kb.add("enter", filter=confirming)
        def _(event):
            self.dialog.activate()

        @kb.add("enter", filter=normal & popup, eager=True)
        @kb.add("tab", filter=normal & popup, eager=True)
        def _(event):
            self.tag_popup.accept()

        @kb.add("up", filter=normal & popup, eager=True)
        def _(event):
            self.tag_popup.move(-1)
            self.application.invalidate()

        @kb.add("down", filter=normal & popup, eager=True)
        def _(event):
            self.tag_popup.move(1)
            self.application.invalidate()

        @kb.add("escape", "up", filter=normal & editable)
        def _(event):
            self.browse_history(-1)

        @kb.add("escape", "down", filter=normal & editable)
        def _(event):
            self.browse_history(1)

        @kb.add("enter", filter=normal)
        def _(event):
            self.submit()

        @kb.add("c-j", filter=normal)
        @kb.add("escape", "enter", filter=normal)
        def _(event):
            event.current_buffer.newline()

        @kb.add("pageup", filter=scrollable)
        def _(event):
            scroll = self.panel if self.panel_visible() else self.output
            scroll.move(-max(1, scroll.height - 1))
            self.application.invalidate()

        @kb.add("pagedown", filter=scrollable)
        def _(event):
            scroll = self.panel if self.panel_visible() else self.output
            scroll.move(max(1, scroll.height - 1))
            self.application.invalidate()

        @kb.add("c-k")
        def _(event):
            if self.overlay is not None:
                self.close_overlay()
            else:
                self.open_palette()

        @kb.add("c-l", filter=normal)
        def _(event):
            self.open_nova(Section.DIARY)

        @kb.add("escape", "c-n", filter=normal)
        def _(event):
            self.open_nova(Section.AGENDA)

        @kb.add("c-o", filter=normal)
        def _(event):
            self.open_files()

        @kb.add("c-r", filter=normal)
        def _(event):
            self.toggle_recording()

        @kb.add("f2", filter=normal)
        def _(event):
            if self.panel_visible():
                self.close_panel()
            else:
                self.show_last_response()

        @kb.add("c-c")
        def _(event):
            self.interrupt()

        @kb.add("c-d", filter=normal)
        def _(event):
            if not self.input.text:
                self.request_exit()
            else:
                event.current_buffer.delete()

        @kb.add("escape")
        def _(event):
            self.escape()

        return kb

    async def run(self):
        from prompt_toolkit.shortcuts import clear_title, set_title

        set_title(f"{i18n.assistant_name()} {self.version}")
        self.session.start()
        self.ensure_ticker()
        try:
            await self.application.run_async()
        finally:
            self.exiting = True
            self.scheduler.cancel(self.ticker)
            clear_title()
            self.session.shutdown()
            self.session.worker.join(8)

