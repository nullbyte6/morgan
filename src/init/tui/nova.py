#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
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
"""Nova in the terminal: agenda, reminders, events, calendar, diary, week, memories and search."""
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from getpass import getuser
from pathlib import Path

from src.init.memory.integration import configured_service
from src.init.nova.agenda import agenda_groups, event_groups, reminder_groups
from src.init.nova.entries import RECURRENCES, Event, Reminder
from src.init.nova.journal import clipped, day_bounds, describe_week, local_moment, message_count, summarize
from src.init.nova.sections import Section
from src.init.tui import nova_text as fmt
from src.init.tui.i18n import assistant_name, t
from src.init.tui.overlays import Overlay, scroll_window
from src.init.tui.text import elide, pad, width_of, wrap
from src.init.tui.widgets import clicked, style

SECTIONS = list(Section)
REMINDER, EVENT = "reminder", "event"
REFRESH_SECONDS = 1.5
MESSAGE_LIMIT = 300
DATE_FORMAT, MOMENT_FORMAT = "%Y-%m-%d", "%Y-%m-%d %H:%M"


@dataclass
class Row:
    fragments: list
    key: object = None


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"
    options: tuple = field(default_factory=tuple)


def _memory():
    try:
        return configured_service(), None
    except Exception as error:
        return None, str(error)


class EntryForm:
    """Create or edit one reminder or event, field by field."""

    def __init__(self, store, close, entry=None, kind=REMINDER, day: date | None = None):
        self.store = store
        self.close = close
        self.editing = entry
        self.kind = kind if entry is None else (REMINDER if isinstance(entry, Reminder) else EVENT)
        self.index = 1 if entry is None else 0
        self.error = ""
        self.armed = False
        now = datetime.now().replace(second=0, microsecond=0)
        start = datetime.combine(day, now.time()) if day is not None and day != now.date() else now
        start = start.replace(minute=0) + timedelta(hours=1)
        self.values = {"title": "", "notes": "", "repeat": "none", "all_day": False,
                       "when": start.strftime(MOMENT_FORMAT), "starts": start.strftime(MOMENT_FORMAT),
                       "ends": (start + timedelta(hours=1)).strftime(MOMENT_FORMAT)}
        if isinstance(entry, Reminder):
            self.values.update(title=entry.title, notes=entry.notes, repeat=entry.recurrence,
                               when=entry.remind_at.strftime(MOMENT_FORMAT))
        elif isinstance(entry, Event):
            moment = DATE_FORMAT if entry.all_day else MOMENT_FORMAT
            self.values.update(title=entry.title, notes=entry.notes, repeat=entry.recurrence,
                               all_day=entry.all_day, starts=entry.starts_at.strftime(moment),
                               ends=entry.ends_at.strftime(moment))

    def fields(self) -> list[Field]:
        fields = []
        if self.editing is None:
            fields.append(Field("kind", t("tui.nova.kind"), "choice", (REMINDER, EVENT)))
        fields.append(Field("title", t("nova.dialog.title")))
        if self.kind == REMINDER:
            fields.append(Field("when", t("nova.dialog.remind_at")))
        else:
            fields += [Field("all_day", t("nova.dialog.all_day"), "toggle"),
                       Field("starts", t("nova.dialog.starts")), Field("ends", t("nova.dialog.ends"))]
        fields += [Field("repeat", t("nova.dialog.repeat"), "choice", RECURRENCES),
                   Field("notes", t("nova.dialog.notes")), Field("save", t("nova.dialog.save"), "button")]
        if self.editing is not None:
            fields.append(Field("delete", t("nova.dialog.delete"), "button"))
        fields.append(Field("cancel", t("nova.dialog.cancel"), "button"))
        return fields

    def title(self) -> str:
        key = {(REMINDER, False): "nova.dialog.new_reminder", (EVENT, False): "nova.dialog.new_event",
               (REMINDER, True): "nova.dialog.edit_reminder", (EVENT, True): "nova.dialog.edit_event"}
        return t(key[(self.kind, self.editing is not None)])

    def display(self, item: Field) -> str:
        value = self.values.get(item.key)
        if item.key == "kind":
            return t("nova.reminder" if self.kind == REMINDER else "nova.event")
        if item.key == "repeat":
            return t(f"nova.repeat.{value}")
        if item.kind == "toggle":
            return "[x]" if value else "[ ]"
        return str(value).replace("\n", " ⏎ ")

    def lines(self, app, width, rows) -> list:
        P = app.palette
        lines = [[(style(P["accent"], bold=True), " " + elide(self.title(), width - 2))],
                 [(style(P["border"]), "─" * width)]]
        fields = self.fields()
        self.index = min(self.index, len(fields) - 1)
        label_width = min(18, max(width_of(item.label) for item in fields) + 2)
        buttons = []
        for position, item in enumerate(fields):
            selected = position == self.index
            action = clicked(lambda position=position: self.click(app, position))
            if item.kind == "button":
                text = f" {item.label} "
                if item.key == "delete" and self.armed:
                    text = f" {t('tui.nova.confirm')} "
                tone = P["error"] if item.key == "delete" else P["accent"]
                buttons.append((style(P["on_accent"], tone, bold=True) if selected else style(tone, bold=True),
                                text, action))
                buttons.append(("", "  "))
                continue
            value = self.display(item)
            if item.kind == "choice":
                value = f"‹ {value} ›"
            label = pad(" " + elide(item.label, label_width - 1), label_width)
            room = max(4, width - label_width - 2)
            cursor = "▏" if selected and item.kind == "text" else ""
            shown = (value[-(room - 1):] if width_of(value) >= room else value) + cursor
            if selected:
                lines.append([(style(P["on_accent"], P["accent"], bold=True), pad(label + " " + shown, width),
                               action)])
            else:
                lines.append([(style(P["text_muted"]), label, action), (style(P["text"]), " " + shown, action)])
        lines.append([("", "")])
        lines.append([("", " ")] + buttons)
        if self.error:
            lines.append([(style(P["error"]), " " + elide(self.error, width - 2))])
        return lines

    def click(self, app, position):
        if position == self.index and self.fields()[position].kind in ("button", "choice", "toggle"):
            self.activate(app)
        else:
            self.index = position
            self.armed = False

    def current(self) -> Field:
        fields = self.fields()
        self.index = min(self.index, len(fields) - 1)
        return fields[self.index]

    def cycle(self, step: int) -> None:
        item = self.current()
        if item.key == "kind":
            self.kind = EVENT if self.kind == REMINDER else REMINDER
        elif item.key == "repeat":
            options = list(RECURRENCES)
            self.values["repeat"] = options[(options.index(self.values["repeat"]) + step) % len(options)]
        elif item.key == "all_day":
            self.set_all_day(not self.values["all_day"])

    def set_all_day(self, all_day: bool) -> None:
        self.values["all_day"] = all_day
        for key in ("starts", "ends"):
            text = self.values[key].strip()
            self.values[key] = text[:10] if all_day else (text if len(text) > 10 else f"{text[:10]} 09:00")

    def moment(self, key: str) -> datetime:
        text = self.values[key].strip()
        try:
            if self.kind == EVENT and self.values["all_day"]:
                return datetime.strptime(text[:10], DATE_FORMAT)
            return datetime.strptime(" ".join(text.split()), MOMENT_FORMAT)
        except ValueError:
            raise ValueError(t("tui.nova.error_moment")) from None

    def save(self, app) -> None:
        title = self.values["title"].strip()
        if not title:
            self.error = t("nova.dialog.title_placeholder")
            return
        notes, recurrence = self.values["notes"], self.values["repeat"]
        try:
            if self.kind == REMINDER:
                when = self.moment("when")
                if self.editing is None:
                    self.store.add_reminder(title, when, notes, recurrence)
                else:
                    self.store.update_reminder(self.editing.id, title, when, notes, recurrence)
            else:
                starts, ends = self.moment("starts"), self.moment("ends")
                if ends < starts:
                    raise ValueError(t("nova.error.order"))
                options = dict(all_day=self.values["all_day"], notes=notes, recurrence=recurrence)
                if self.editing is None:
                    self.store.add_event(title, starts, ends, **options)
                else:
                    self.store.update_event(self.editing.id, title, starts, ends, **options)
        except (ValueError, OSError) as error:
            self.error = str(error)
            return
        self.close()

    def delete(self, app) -> None:
        if not self.armed:
            self.armed = True
            return
        try:
            if isinstance(self.editing, Reminder):
                self.store.delete_reminder(self.editing.id)
            else:
                self.store.delete_event(self.editing.id)
        except OSError as error:
            self.error = str(error)
            return
        self.close()

    def activate(self, app) -> None:
        item = self.current()
        if item.key == "save":
            self.save(app)
        elif item.key == "delete":
            self.delete(app)
        elif item.key == "cancel":
            self.close()
        elif item.kind in ("choice", "toggle"):
            self.cycle(1)
        else:
            self.index += 1

    def on_key(self, app, key) -> None:
        count = len(self.fields())
        if key in ("up", "s-tab"):
            self.index = (self.index - 1) % count
            self.armed = False
        elif key in ("down", "tab"):
            self.index = (self.index + 1) % count
            self.armed = False
        elif key in ("left", "right") and self.current().kind in ("choice", "toggle"):
            self.cycle(-1 if key == "left" else 1)
        elif key == "enter":
            self.activate(app)
        elif key == "backspace" and self.current().kind == "text":
            name = self.current().key
            self.values[name] = self.values[name][:-1]
        elif key == "clear" and self.current().kind == "text":
            self.values[self.current().key] = ""

    def on_text(self, app, text) -> None:
        item = self.current()
        if item.kind == "text":
            self.values[item.key] += text.replace("\r", "")
            self.error = ""
        elif text == " ":
            self.activate(app)


class MemoryEditor:
    """Rewrite the text of one stored memory."""

    def __init__(self, memory: dict, close):
        self.memory = memory
        self.close = close
        self.text = memory["content"]
        self.error = ""

    def lines(self, app, width, rows) -> list:
        P = app.palette
        lines = [[(style(P["accent"], bold=True), " " + elide(t("nova.memories.edit"), width - 2))],
                 [(style(P["border"]), "─" * width)]]
        for line in wrap(self.text + "▏", width - 2) or ["▏"]:
            lines.append([(style(P["text"]), " " + line)])
        if self.error:
            lines.append([(style(P["error"]), " " + elide(self.error, width - 2))])
        return lines

    def save(self, app) -> None:
        service, error = _memory()
        try:
            if service is None:
                raise ValueError(error or t("nova.diary.disabled"))
            service.update_memory(self.memory["id"], self.text, category=self.memory["category"])
        except Exception as failure:
            self.error = str(failure)
            return
        self.close()

    def on_key(self, app, key) -> None:
        if key == "enter":
            self.save(app)
        elif key == "backspace":
            self.text = self.text[:-1]
        elif key == "clear":
            self.text = ""

    def on_text(self, app, text) -> None:
        self.text += text.replace("\r", "").replace("\n", " ")
        self.error = ""


class NovaOverlay(Overlay):
    """Every Nova section in one panel, switched with Tab or the number keys."""

    wide = 110
    tall = 60
    margin = 4

    def __init__(self, app, section: Section = Section.AGENDA):
        self.app = app
        self.store = app.session.nova
        self.section = section
        self.index = 0
        self.form = None
        self.armed = None
        self.notice = ""
        self.calendar_day = date.today()
        self.calendar_entries = False
        self.diary_day = date.today()
        self.expanded: set[str] = set()
        self.week_first = fmt.week_start(date.today())
        self.summaries: dict[date, tuple[str, bool]] = {}
        self.pending: set[date] = set()
        self.query = ""
        self.rows: list[Row] = []
        self.stale = True
        self.loaded = (0.0, 0)

    def title(self):
        return t("palette.nova")

    def hint(self):
        if isinstance(self.form, EntryForm):
            return t("tui.nova.hint.form")
        if isinstance(self.form, MemoryEditor):
            return t("tui.nova.hint.memory_edit")
        if self.notice:
            return self.notice
        if self.section is Section.CALENDAR:
            return t("tui.nova.hint.calendar_day" if self.calendar_entries else "tui.nova.hint.calendar")
        names = {Section.DIARY: "diary", Section.REVIEW: "week", Section.MEMORIES: "memories",
                 Section.SEARCH: "search"}
        return t(f"tui.nova.hint.{names.get(self.section, 'list')}")

    def changed(self):
        self.stale = True

    def show_section(self, section: Section) -> None:
        self.section = section
        self.index = 0
        self.armed = None
        self.notice = ""
        self.calendar_entries = False
        self.stale = True

    def show_day(self, day: date) -> None:
        self.diary_day = day
        self.expanded.clear()
        self.show_section(Section.DIARY)

    def close_form(self) -> None:
        self.form = None
        self.stale = True

    def back(self, app) -> bool:
        if self.form is not None:
            self.close_form()
            return True
        if self.calendar_entries:
            self.calendar_entries = False
            self.stale = True
            return True
        if self.armed is not None:
            self.armed = None
            self.notice = ""
            return True
        return False

    def tabs(self, P, width) -> list:
        labels = [f" {position} {section.title} " for position, section in enumerate(SECTIONS, 1)]
        if sum(width_of(label) for label in labels) + 1 > width:
            labels = [f" {position}{(' ' + section.title) if section is self.section else ''} "
                      for position, section in enumerate(SECTIONS, 1)]
        fragments = [("", " ")]
        for section, label in zip(SECTIONS, labels):
            selected = section is self.section
            fragments.append((style(P["on_accent"], P["accent"], bold=True) if selected else style(P["text_muted"]),
                              label, clicked(lambda section=section: self.show_section(section))))
        return fragments

    def lines(self, app, width, rows):
        P = app.palette
        if self.form is not None:
            body = self.form.lines(app, width, rows)
            return body + [[("", "")]] * max(0, rows - len(body))
        loaded_at, loaded_width = self.loaded
        if self.stale or loaded_width != width or time.monotonic() - loaded_at > REFRESH_SECONDS:
            self.rows = self.build(app, width)
            self.stale = False
            self.loaded = (time.monotonic(), width)
        header = [self.tabs(P, width),
                  [(style(P["text_subtle"]), " " + elide(self.section.tagline, width - 2))],
                  [(style(P["border"]), "─" * width)]]
        selectable = [position for position, row in enumerate(self.rows) if row.key is not None]
        self.index = min(self.index, max(0, len(selectable) - 1))
        target = selectable[self.index] if selectable else 0
        room = max(1, rows - len(header))
        first = scroll_window(len(self.rows), target, room)
        body = []
        for position, row in enumerate(self.rows[first:first + room], first):
            if selectable and position == target and self.focused():
                text = "".join(fragment[1] for fragment in row.fragments)
                body.append([(style(P["on_accent"], P["accent"], bold=True), pad(elide(text, width), width),
                              clicked(lambda position=position: self.click(app, position)))])
            elif row.key is not None:
                body.append([(*fragment[:2], clicked(lambda position=position: self.click(app, position)))
                             for fragment in row.fragments])
            else:
                body.append(row.fragments)
        return header + body + [[("", "")]] * max(0, room - len(body))

    def focused(self) -> bool:
        return self.section is not Section.CALENDAR or self.calendar_entries

    def click(self, app, position):
        selectable = [index for index, row in enumerate(self.rows) if row.key is not None]
        if position not in selectable:
            return
        if self.section is Section.CALENDAR and not self.calendar_entries:
            self.calendar_entries = True
        if selectable.index(position) == self.index:
            self.activate(app)
        else:
            self.index = selectable.index(position)
            self.armed = None

    def fresh(self) -> None:
        if self.stale:
            width = self.loaded[1] or self.wide - 2
            self.rows = self.build(self.app, width)
            self.stale = False
            self.loaded = (time.monotonic(), width)

    def selected(self):
        self.fresh()
        keys = [row.key for row in self.rows if row.key is not None]
        if not keys or not self.focused():
            return None
        return keys[min(self.index, len(keys) - 1)]

    def heading(self, P, text) -> Row:
        return Row([(style(P["accent"], bold=True), " " + text)])

    def note(self, P, text, width, tone="text_muted") -> list[Row]:
        return [Row([(style(P[tone]), " " + line)]) for line in wrap(text, width - 2)]

    def entry_rows(self, P, entry, width, now, dated=True) -> list[Row]:
        today = now.date()
        repeat = f" {fmt.REPEAT}" if entry.is_recurring else ""
        if isinstance(entry, Reminder):
            overdue = not entry.is_completed and entry.remind_at < now
            mark = "☑" if entry.is_completed else "☐"
            tone = "text_disabled" if entry.is_completed else "warning" if overdue else "text"
        else:
            mark, tone = "◆", "text"
        if dated:
            when = fmt.entry_when(entry, today)
        else:
            when = fmt.time_text(entry.remind_at) if isinstance(entry, Reminder) else fmt.event_time_text(entry)
        rows = [Row([(style(P["accent"]), f"  {mark} "), (style(P["text_secondary"]), pad(when, 16) + " "),
                     (style(P[tone], bold=not isinstance(entry, Reminder) or not entry.is_completed),
                      elide(entry.title + repeat, max(4, width - 22 - width_of(when))))], ("entry", entry))]
        notes = " ".join(entry.notes.split())
        if notes:
            rows.append(Row([(style(P["text_muted"]), "      " + elide(notes, width - 7))]))
        return rows

    def build(self, app, width) -> list[Row]:
        P = app.palette
        if self.store is None:
            return self.note(P, t("nova.diary.error", error="Nova"), width, "error")
        builder = {Section.CALENDAR: self.build_calendar, Section.DIARY: self.build_diary,
                   Section.REVIEW: self.build_week, Section.MEMORIES: self.build_memories,
                   Section.SEARCH: self.build_search}.get(self.section, self.build_list)
        try:
            return builder(P, width)
        except Exception as error:
            return self.note(P, t("nova.diary.error", error=error), width, "error")

    def build_list(self, P, width) -> list[Row]:
        now = datetime.now()
        if self.section is Section.AGENDA:
            groups, empty = agenda_groups(self.store, now, fmt.day_heading), "nova.empty.agenda"
        elif self.section is Section.REMINDERS:
            groups, empty = reminder_groups(self.store), "nova.empty.reminders"
        else:
            groups, empty = event_groups(self.store, now), "nova.empty.events"
        rows = []
        for position, (heading, entries) in enumerate(groups):
            if not entries:
                continue
            rows.append(self.heading(P, heading))
            dated = self.section is not Section.AGENDA or position == 0
            for entry in entries:
                rows += self.entry_rows(P, entry, width, now, dated)
            rows.append(Row([("", "")]))
        return rows or self.note(P, t(empty), width)

    def build_calendar(self, P, width) -> list[Row]:
        now = datetime.now()
        today, chosen = now.date(), self.calendar_day
        cell = max(4, min(10, (width - 2) // 7))
        month_first = chosen.replace(day=1)
        first = fmt.week_start(month_first)
        last = first + timedelta(days=41)
        busy = self.store.busy_days(first, last)
        rows = [self.heading(P, fmt.month_title(chosen)),
                Row([("", " ")] + [(style(P["text_muted"]), pad(elide(fmt.weekday_name(index), cell - 1), cell))
                                   for index in range(7)])]
        for week in range(6):
            cells = [("", " ")]
            for offset in range(7):
                day = first + timedelta(days=week * 7 + offset)
                text = pad(f"{day.day:>2}{'•' if day in busy else ' '}", cell)
                if day == chosen:
                    tone = style(P["on_accent"], P["accent"], bold=True)
                elif day == today:
                    tone = style(P["accent"], bold=True)
                elif day.month != chosen.month:
                    tone = style(P["text_disabled"])
                else:
                    tone = style(P["text"])
                cells.append((tone, text, clicked(lambda day=day: self.pick_day(day))))
            rows.append(Row(cells))
        rows += [Row([("", "")]), self.heading(P, fmt.day_heading(chosen, today))]
        entries = self.store.entries(chosen, chosen)
        for entry in entries:
            rows += self.entry_rows(P, entry, width, now, dated=False)
        if not entries:
            rows += self.note(P, t("nova.empty.agenda"), width)
        return rows

    def pick_day(self, day: date) -> None:
        if day == self.calendar_day and not self.calendar_entries:
            self.enter_calendar_day()
        self.calendar_day = day
        self.stale = True

    def enter_calendar_day(self) -> None:
        if self.store.entries(self.calendar_day, self.calendar_day):
            self.calendar_entries = True
            self.index = 0
        else:
            self.form = EntryForm(self.store, self.close_form, kind=EVENT, day=self.calendar_day)
        self.stale = True

    def diary_data(self):
        service, error = _memory()
        data = {"sessions": [], "memories": []}
        if service is not None:
            try:
                data = service.diary(*day_bounds(self.diary_day))
            except Exception as failure:
                error = str(failure)
        return service, data, error

    def conversation(self, service, session_id: str) -> list[dict]:
        since, until = day_bounds(self.diary_day)
        return service.diary_messages(session_id, since, until)

    def build_diary(self, P, width) -> list[Row]:
        now = datetime.now()
        rows = [self.heading(P, fmt.day_heading(self.diary_day, now.date()))]
        service, data, error = self.diary_data()
        entries = self.store.entries(self.diary_day, self.diary_day)
        if entries:
            rows.append(Row([(style(P["text_secondary"], bold=True), " " + t("nova.diary.agenda"))]))
            for entry in entries:
                rows += self.entry_rows(P, entry, width, now, dated=False)
        if data["memories"]:
            rows.append(Row([(style(P["text_secondary"], bold=True), " " + t("nova.diary.learned"))]))
            for memory in data["memories"]:
                for position, line in enumerate(wrap(" ".join(memory["content"].split()), width - 6)):
                    rows.append(Row([(style(P["text"]), ("   • " if position == 0 else "     ") + line)]))
        authors = {"user": getuser().capitalize(), "assistant": assistant_name(), "system": "System"}
        if data["sessions"]:
            rows.append(Row([(style(P["text_secondary"], bold=True), " " + t("nova.diary.conversations"))]))
        for session in data["sessions"]:
            session_id = session["session_id"]
            is_open = session_id in self.expanded
            started = local_moment(session["started_at"])
            topic = clipped(session["topic"]) or t("nova.diary.untitled")
            caption = message_count(session["messages"])
            mark = t("tui.nova.confirm") if self.armed == ("session", session_id) else caption
            rows.append(Row([(style(P["accent"]), "  ▾ " if is_open else "  ▸ "),
                             (style(P["text_secondary"]), fmt.time_text(started) + " · "),
                             (style(P["text"], bold=True), elide(topic, max(4, width - 16 - width_of(mark)))),
                             (style(P["text_muted"]), "  " + mark)], ("session", session_id)))
            if not is_open or service is None:
                continue
            for message in self.conversation(service, session_id):
                stamp = local_moment(message["created_at"]).strftime("%H:%M:%S")
                author = authors.get(message["role"], message["role"])
                armed = f"  {t('tui.nova.confirm')}" if self.armed == ("message", message["id"]) else ""
                tone = P["accent"] if message["role"] == "assistant" else P["success"]
                rows.append(Row([(style(tone, bold=True), f"     {author}"),
                                 (style(P["text_muted"]), f" · {stamp}{armed}")], ("message", message["id"])))
                for line in message["content"].strip("\n").splitlines() or [""]:
                    for part in wrap(line, width - 8) or [""]:
                        rows.append(Row([(style(P["text"]), "       " + part)]))
        if error is not None:
            rows += self.note(P, t("nova.diary.error", error=error), width, "error")
        elif not (entries or data["memories"] or data["sessions"]):
            rows += self.note(P, t("nova.diary.disabled" if service is None else "nova.diary.empty"), width)
        return rows

    def export_day(self, app) -> None:
        service, data, error = self.diary_data()
        conversations = []
        authors = {"user": getuser().capitalize(), "assistant": assistant_name(), "system": "System"}
        for session in data["sessions"]:
            messages = [(authors.get(row["role"], row["role"]), local_moment(row["created_at"]).strftime("%H:%M:%S"),
                         row["content"].strip("\n")) for row in self.conversation(service, session["session_id"])]
            conversations.append(({"topic": session["topic"], "started": local_moment(session["started_at"])},
                                  messages))
        markdown = fmt.day_markdown(self.diary_day, self.store.entries(self.diary_day, self.diary_day),
                                    data["memories"], conversations)
        directory = Path(app.session.directory)
        path = directory / f"{self.diary_day:%Y-%m-%d}.md"
        copy = 2
        while path.exists():
            path = directory / f"{self.diary_day:%Y-%m-%d} ({copy}).md"
            copy += 1
        try:
            path.write_text(markdown, encoding="utf-8")
        except OSError as failure:
            self.notice = t("nova.diary.export_error", error=failure)
            return
        self.notice = t("tui.nova.exported", path=path)

    def step_diary(self, earlier: bool | None) -> None:
        if earlier is None:
            self.diary_day = date.today()
        else:
            service, _data, _error = self.diary_data()
            stamp = None
            if service is not None:
                bound = day_bounds(self.diary_day)[0 if earlier else 1]
                try:
                    stamp = service.adjacent_activity(bound, earlier=earlier)
                except Exception:
                    stamp = None
            if stamp is None:
                return
            self.diary_day = local_moment(stamp).date()
        self.expanded.clear()
        self.index = 0
        self.stale = True

    def week_data(self):
        last = self.week_first + timedelta(days=6)
        reminders = self.store.reminders(datetime.combine(self.week_first, datetime.min.time()),
                                         datetime.combine(last + timedelta(days=1), datetime.min.time()))
        events = self.store.events(self.week_first, last)
        service, error = _memory()
        data = {"sessions": [], "memories": []}
        if service is not None:
            try:
                data = service.diary(day_bounds(self.week_first)[0], day_bounds(last)[1])
            except Exception as failure:
                error = str(failure)
        return reminders, events, data, error

    def build_week(self, P, width) -> list[Row]:
        now = datetime.now()
        last = self.week_first + timedelta(days=6)
        busy = self.week_first in self.pending
        action = t("nova.review.summarizing" if busy else "nova.review.summarize")
        rows = [Row([(style(P["accent"], bold=True), " " + fmt.week_title(self.week_first, last)),
                     (style(P["text_muted"]), f"   s · {action}")])]
        reminders, events, data, error = self.week_data()
        sessions = data["sessions"]
        summary = self.summaries.get(self.week_first)
        if summary is not None:
            text, failed = summary
            rows.append(Row([("", "")]))
            rows.append(self.heading(P, t("nova.review.summary")))
            rows += self.note(P, t("nova.review.summary_error", error=text) if failed else text, width,
                              "error" if failed else "text")
        active = bool(reminders or events or sessions or data["memories"])
        if active:
            done = sum(1 for reminder in reminders if reminder.is_completed)
            pending = sum(1 for reminder in reminders if not reminder.is_completed and reminder.remind_at >= now)
            rows += [Row([("", "")]), self.heading(P, t("nova.review.overview"))]
            for text in (t("nova.review.reminders", done=done, pending=pending, missed=len(reminders) - done - pending),
                         t("nova.review.events", count=len(events)),
                         t("nova.review.conversations", count=len(sessions),
                           messages=sum(session["messages"] for session in sessions)),
                         t("nova.review.memories", count=len(data["memories"]))):
                rows.append(Row([(style(P["text"]), "   " + text)]))
        days: dict[date, dict] = {}
        for session in sessions:
            info = days.setdefault(local_moment(session["started_at"]).date(),
                                   {"conversations": 0, "messages": 0, "entries": 0, "topic": ""})
            info["conversations"] += 1
            info["messages"] += session["messages"]
            info["topic"] = info["topic"] or session["topic"]
        for entry in [*reminders, *events]:
            for day in entry.days():
                if self.week_first <= day <= last:
                    days.setdefault(day, {"conversations": 0, "messages": 0, "entries": 0, "topic": ""})
                    days[day]["entries"] += 1
        if days:
            rows += [Row([("", "")]), self.heading(P, t("nova.review.days"))]
            for day in sorted(days):
                info = days[day]
                caption = t("nova.review.day_caption", conversations=info["conversations"],
                            messages=info["messages"], entries=info["entries"])
                rows.append(Row([(style(P["text"], bold=True), "   " + fmt.day_heading(day, now.date())),
                                 (style(P["text_muted"]), "  " + caption)], ("day", day)))
                if info["topic"]:
                    rows.append(Row([(style(P["text_muted"]), "     " + elide(clipped(info["topic"]), width - 6))]))
        if error is not None:
            rows += self.note(P, t("nova.diary.error", error=error), width, "error")
        elif not active:
            rows += self.note(P, t("nova.review.empty"), width)
        return rows

    def summarize_week(self, app) -> None:
        first = self.week_first
        if first in self.pending:
            return
        reminders, events, data, _error = self.week_data()
        if not (reminders or events or data["sessions"] or data["memories"]):
            return
        facts = describe_week(first, reminders, events, data, datetime.now())
        self.pending.add(first)
        self.stale = True

        def run() -> None:
            try:
                result = (summarize(facts), False)
            except Exception as error:
                result = (str(error), True)
            app.scheduler.post(self.summarized, app, first, result)

        threading.Thread(target=run, name="nova-week-review", daemon=True).start()

    def summarized(self, app, first: date, result: tuple[str, bool]) -> None:
        self.pending.discard(first)
        self.summaries[first] = result
        self.stale = True
        app.application.invalidate()

    def build_memories(self, P, width) -> list[Row]:
        service, error = _memory()
        if service is None:
            return self.note(P, error or t("nova.diary.disabled"), width, "error" if error else "text_muted")
        memories = service.stored_memories()
        rows = []
        for heading, group in ((t("nova.memories.pinned"), [memory for memory in memories if memory["pinned"]]),
                               (t("nova.memories.stored"), [memory for memory in memories if not memory["pinned"]])):
            if not group:
                continue
            rows.append(self.heading(P, heading))
            for memory in group:
                mark = "★ " if memory["pinned"] else "  "
                caption = " · ".join((t(f"nova.diary.category.{memory['category']}"),
                                      fmt.date_time_text(local_moment(memory["modified_at"]))))
                if self.armed == ("memory", memory["id"]):
                    caption = t("tui.nova.confirm")
                content = " ".join(memory["content"].split())
                rows.append(Row([(style(P["accent"]), "  " + mark),
                                 (style(P["text"]), elide(content, max(4, width - 8 - width_of(caption)))),
                                 (style(P["text_muted"]), "  " + caption)], ("memory", memory)))
            rows.append(Row([("", "")]))
        return rows or self.note(P, t("nova.memories.empty"), width)

    def memory_action(self, action, memory) -> None:
        service, error = _memory()
        try:
            if service is None:
                raise ValueError(error or t("nova.diary.disabled"))
            action(service, memory)
        except Exception as failure:
            self.notice = t("nova.diary.error", error=failure)
        self.stale = True

    def build_search(self, P, width) -> list[Row]:
        rows = [Row([(style(P["text_subtle"]), " ⌕ "),
                     (style(P["text"]) if self.query else style(P["text_subtle"]),
                      elide(self.query or t("nova.search.placeholder"), width - 6)),
                     (style(P["accent"], bold=True), "▏")]), Row([("", "")])]
        query = self.query.strip()
        if not query:
            return rows + self.note(P, t("nova.search.hint"), width)
        now = datetime.now()
        entries = self.store.search(query)
        groups = ((t("nova.section.reminders"), [entry for entry in entries if isinstance(entry, Reminder)]),
                  (t("nova.section.events"), [entry for entry in entries if isinstance(entry, Event)]))
        for heading, found in groups:
            if found:
                rows.append(self.heading(P, heading))
                for entry in found:
                    rows += self.entry_rows(P, entry, width, now)
        service, error = _memory()
        days: dict[date, list[str]] = {}
        if service is not None:
            try:
                for row in service.search_messages(query, limit=MESSAGE_LIMIT):
                    days.setdefault(local_moment(row["created_at"]).date(), []).append(row["excerpt"])
            except Exception as failure:
                error = str(failure)
        if days:
            rows.append(self.heading(P, t("nova.search.days")))
            for day in sorted(days, reverse=True):
                excerpts = days[day]
                rows.append(Row([(style(P["text"], bold=True), "   " + fmt.day_heading(day, now.date())),
                                 (style(P["text_muted"]), "  " + message_count(len(excerpts)))], ("day", day)))
                rows.append(Row([(style(P["text_muted"]), "     " + elide(clipped(excerpts[0]), width - 6))]))
        if error is not None:
            rows += self.note(P, t("nova.diary.error", error=error), width, "error")
        elif not (entries or days):
            rows += self.note(P, t("nova.search.empty", query=query), width)
        return rows

    def activate(self, app) -> None:
        key = self.selected()
        if key is None:
            if self.section is Section.CALENDAR:
                self.enter_calendar_day()
            return
        kind, value = key
        if kind == "entry":
            stored = (self.store.reminder(value.id) if isinstance(value, Reminder) else self.store.find_event(value.id))
            if stored is not None:
                self.form = EntryForm(self.store, self.close_form, stored)
        elif kind == "session":
            (self.expanded.discard if value in self.expanded else self.expanded.add)(value)
        elif kind == "day":
            self.show_day(value)
        elif kind == "memory":
            self.form = MemoryEditor(value, self.close_form)
        self.stale = True

    def toggle_done(self) -> None:
        key = self.selected()
        if key is not None and key[0] == "entry" and isinstance(key[1], Reminder):
            stored = self.store.reminder(key[1].id)
            if stored is not None:
                self.store.set_reminder_completed(stored.id, not stored.is_completed)
            self.stale = True

    def remove(self) -> None:
        key = self.selected()
        if key is None:
            return
        identity = (key[0], key[1].id if key[0] in ("entry", "memory") else key[1])
        if self.armed != identity:
            self.armed = identity
            self.notice = t("tui.nova.confirm")
            self.stale = True
            return
        self.armed = None
        self.notice = ""
        kind, value = key
        if kind == "entry":
            if isinstance(value, Reminder):
                self.store.delete_reminder(value.id)
            else:
                self.store.delete_event(value.id)
        elif kind == "memory":
            self.memory_action(lambda service, memory: service.delete_memory(memory["id"]), value)
        elif kind in ("session", "message"):
            service, _data, _error = self.diary_data()
            if service is not None:
                ids = ([value] if kind == "message"
                       else [row["id"] for row in self.conversation(service, value)])
                try:
                    service.forget_messages(ids)
                except Exception as failure:
                    self.notice = t("nova.diary.error", error=failure)
        self.stale = True

    def new_entry(self) -> None:
        if self.section is Section.CALENDAR:
            self.form = EntryForm(self.store, self.close_form, kind=EVENT, day=self.calendar_day)
        elif self.section is Section.DIARY:
            self.form = EntryForm(self.store, self.close_form, kind=REMINDER, day=self.diary_day)
        else:
            kind = EVENT if self.section is Section.EVENTS else REMINDER
            self.form = EntryForm(self.store, self.close_form, kind=kind)

    def move(self, step: int) -> None:
        self.fresh()
        count = sum(1 for row in self.rows if row.key is not None)
        if count:
            self.index = (self.index + step) % count if abs(step) == 1 else min(count - 1, max(0, self.index + step))
        self.armed = None

    def switch(self, step: int) -> None:
        self.show_section(SECTIONS[(SECTIONS.index(self.section) + step) % len(SECTIONS)])

    def on_calendar_key(self, key) -> bool:
        if self.calendar_entries:
            return False
        shifts = {"left": -1, "right": 1, "up": -7, "down": 7}
        if key in shifts:
            self.calendar_day += timedelta(days=shifts[key])
        elif key in ("pageup", "pagedown"):
            month = self.calendar_day.month - 1 + (-1 if key == "pageup" else 1)
            year = self.calendar_day.year + month // 12
            month = month % 12 + 1
            following = date(year + month // 12, month % 12 + 1, 1)
            self.calendar_day = date(year, month, min(self.calendar_day.day, (following - timedelta(days=1)).day))
        elif key == "home":
            self.calendar_day = date.today()
        elif key == "enter":
            self.enter_calendar_day()
        else:
            return False
        self.stale = True
        return True

    def on_key(self, app, key):
        if self.form is not None:
            self.form.on_key(app, key)
            return
        self.notice = "" if key not in ("enter",) else self.notice
        if key == "tab":
            self.switch(1)
        elif key == "s-tab":
            self.switch(-1)
        elif self.section is Section.CALENDAR and self.on_calendar_key(key):
            return
        elif self.section is Section.DIARY and key in ("left", "right", "pageup", "pagedown", "home"):
            if key in ("left", "right"):
                self.diary_day += timedelta(days=-1 if key == "left" else 1)
                self.expanded.clear()
                self.index = 0
            else:
                self.step_diary({"pageup": True, "pagedown": False, "home": None}[key])
            self.stale = True
        elif self.section is Section.REVIEW and key in ("left", "right", "home"):
            self.week_first = (fmt.week_start(date.today()) if key == "home"
                               else self.week_first + timedelta(days=-7 if key == "left" else 7))
            self.index = 0
            self.stale = True
        elif key == "up":
            self.move(-1)
        elif key == "down":
            self.move(1)
        elif key == "pageup":
            self.move(-8)
        elif key == "pagedown":
            self.move(8)
        elif key == "enter":
            self.activate(app)
        elif key == "delete":
            self.remove()
        elif self.section is Section.SEARCH and key == "backspace":
            self.query = self.query[:-1]
            self.index = 0
            self.stale = True
        elif self.section is Section.SEARCH and key == "clear":
            self.query = ""
            self.index = 0
            self.stale = True

    def on_text(self, app, text):
        if self.form is not None:
            self.form.on_text(app, text)
            return
        if self.section is Section.SEARCH:
            self.query += text.replace("\r", "").replace("\n", " ")
            self.index = 0
            self.stale = True
            return
        if text.isdigit() and 1 <= int(text) <= len(SECTIONS):
            self.show_section(SECTIONS[int(text) - 1])
        elif text == "n" and self.section not in (Section.REVIEW, Section.MEMORIES):
            self.new_entry()
        elif text == " ":
            self.toggle_done()
        elif text == "x":
            self.remove()
        elif text == "t":
            self.on_key(app, "home")
        elif text == "e" and self.section is Section.DIARY:
            self.export_day(app)
        elif text == "s" and self.section is Section.REVIEW:
            self.summarize_week(app)
        elif text == "p" and self.section is Section.MEMORIES:
            key = self.selected()
            if key is not None:
                self.memory_action(lambda service, memory: service.pin_memory(memory["id"], not memory["pinned"]),
                                   key[1])
