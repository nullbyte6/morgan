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
"""The conversation state machine of the terminal interface, free of any rendering."""
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from getpass import getuser

from src.init.attachments import Attachment, DesktopMessage, DesktopVoiceMessage, inspect_attachment, normalized_path
from src.init.config import load_config, save_config
from src.init.core import Assistant
from src.init.events import Emitter
from src.init.identity import register_assistant
from src.init.lang import LANGUAGES, set_language
from src.init.session_runner import SessionRunner
from src.init.task_view import TaskProjection
from src.init.tui import i18n
from src.init.tui.i18n import t
from src.init.tui.shell import ShellRun, is_change_directory
from src.init.tui.text import elapsed
from src.init.voice_client import SilentVoice
from src.init.voice_input import VoiceInputRunner

log = logging.getLogger("assistant.tui")
SUSPENDED = {"interrupted", "waiting", "blocked", "limit_reached"}


class WorkerThread(threading.Thread):
    """Runs session jobs one after another, like the desktop's worker thread."""

    def __init__(self):
        super().__init__(name="tui-worker", daemon=True)
        self.jobs = queue.Queue()

    def submit(self, function, *arguments):
        self.jobs.put((function, arguments))

    def stop(self):
        self.jobs.put(None)

    def run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            try:
                job[0](*job[1])
            except Exception:
                log.exception("Worker job failed")


class VoiceThread(VoiceInputRunner, threading.Thread):
    """Live microphone capture on its own thread."""

    def __init__(self, *, automatic=False, live=False):
        threading.Thread.__init__(self, name="tui-voice", daemon=True)
        VoiceInputRunner.__init__(self, automatic=automatic, live=live)
        self.finished = Emitter()

    def run(self):
        try:
            VoiceInputRunner.run(self)
        finally:
            self.finished.emit()


class TuiRunner(SessionRunner):
    report_git_diff = False
    response_surface = None

    def show_response_surface(self, title):
        callback = self.response_surface
        if callback is None:
            return True
        callback(title)
        return False


@dataclass
class Confirmation:
    turn_id: int
    message: str
    request_id: int
    deadline: float

    def remaining(self) -> int:
        return max(0, int(self.deadline - time.monotonic() + 0.999))


class TuiSession:
    """One conversation; every method runs on the interface thread."""

    def __init__(self, scheduler, prefs, *, voice_enabled=True):
        self.scheduler = scheduler
        self.prefs = prefs
        self.assistant = Assistant()
        register_assistant(lambda: self.assistant)
        self.voice_enabled = voice_enabled
        self.assistant.voice_service_required = voice_enabled
        if not voice_enabled:
            self.assistant.voice = SilentVoice()
        self.muted = prefs["muted"] or not voice_enabled
        self.subtitles_enabled = prefs["subtitles"]
        self.steps_enabled = prefs["ephemeral_steps"]
        self.username = getuser().capitalize()
        self.runner = TuiRunner(True, muted=self.muted, session_key=0, primary=True)
        self.runner.response_surface = lambda title: scheduler.post(self.on_response_surface, title)
        self.presentation = TaskProjection()
        self.worker = WorkerThread()
        self.executor = None

        self.changed = Emitter()
        self.draft_accepted = Emitter()
        self.exit_requested = Emitter()

        self.ready = False
        self.started_at = None
        self.ready_at = None
        self.failed = False
        self.busy = False
        self.stopping = False
        self.speaking = False
        self.submitting = None
        self.pending_prompt = None
        self.active_prompt = None
        self.paused_prompt = None
        self.task_stop_requested = False
        self.permission_denied_state = False
        self.pending_voice_barge = False
        self.turn_id = 0
        self.current_reply = None
        self.showing_greeting = True
        self.status_key = "status.waking"
        self.notice = ""
        self.notice_until = 0.0
        self.subtitle_text = ""
        self.visual_state = "idle"
        self.trail_activity = ("", "")
        self.trail_text = ""
        self.trail_timer = None
        self.progress_dismissed = False
        self.progress_turn = 0
        self.command_output = ""
        self.command_output_visible = False
        self.last_command = ""
        self.shell = None
        self.reply_text = ""
        self.last_reply = ""
        self.response_visible = False
        self.response_title = ""
        self.timer_started = None
        self.timer_text = "0s"
        self.attachments = {}
        self.history = []
        self.attachment_jobs = 0
        self.confirmation = None
        self.recording = False
        self.voice_thread = None
        self.levels = []
        self.model = ""
        self.model_switching = False
        self.models = []
        self.permission_mode = load_config()["permission_mode"]
        self.runner.set_permission_mode(self.permission_mode)
        self.directory = self.runner.session.context.working_directory
        self.branch = ""
        self.branch_checked = 0.0
        self.quitting = False
        self.presentation.changed.connect(self.on_view)
        self._bind()

    @property
    def text_mode(self):
        return self.muted or not self.voice_enabled

    def notify(self):
        self.changed.emit()

    def flash(self, message, seconds=6.0):
        self.notice = message
        self.notice_until = time.monotonic() + seconds
        self.scheduler.later(seconds + 0.05, self.notify)
        self.notify()

    def _bind(self):
        runner, post = self.runner, self.scheduler.post
        runner.ready.connect(lambda: post(self.on_ready))
        runner.failed.connect(lambda error: post(self.on_failed, error))
        runner.accepted.connect(lambda turn: post(self.on_accepted, turn))
        runner.rejected.connect(lambda turn, error: post(self.on_rejected, turn, error))
        runner.chunk.connect(lambda turn, chunk: post(self.on_chunk, turn, chunk))
        runner.audio.connect(lambda turn, levels: post(self.on_audio, turn, levels))
        runner.speaking.connect(lambda turn, speaking: post(self.on_speaking, turn, speaking))
        runner.subtitle.connect(lambda turn, text: post(self.on_subtitle, turn, text))
        runner.activity.connect(lambda turn, activity: post(self.presentation.on_activity, turn, activity))
        runner.phase.connect(lambda turn, phase: post(self.presentation.on_phase, turn, phase))
        runner.task_title.connect(lambda turn, title: post(self.presentation.set_task_title, turn, title))
        runner.permission_denied.connect(lambda turn: post(self.on_permission_denied, turn))
        runner.finished.connect(lambda reply: post(self.on_finished, reply))
        runner.directory.connect(lambda directory: post(self.on_directory, directory))
        runner.confirmation_requested.connect(
            lambda turn, message, request, timeout: post(
                self.on_confirmation_requested, turn, message, request, timeout))
        runner.confirmation_closed.connect(lambda request: post(self.on_confirmation_closed, request))
        runner.model_changed.connect(lambda model: post(self.on_model_changed, model))
        runner.model_failed.connect(lambda error: post(self.on_model_failed, error))
        runner.exit_requested.connect(lambda: post(self.exit_requested.emit))

    def start(self):
        self.started_at = time.monotonic()
        self.worker.start()
        self.worker.submit(self.runner.initialize)
        self.refresh_branch()

    def shutdown(self):
        self.quitting = True
        if self.shell is not None:
            self.shell.cancel()
        if self.voice_thread is not None:
            self.voice_thread.stop_event.set()
        if self.busy:
            self.runner.interrupt()
        self.worker.submit(self.runner.shutdown)
        self.worker.stop()
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)

    def background(self, function, *arguments):
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tui-io")
        return self.executor.submit(function, *arguments)

    def set_visual(self, state):
        self.visual_state = state

    def on_view(self, view):
        if view.turn_id != self.progress_turn:
            self.progress_turn = view.turn_id
            self.progress_dismissed = False
        self.set_visual(view.orb_state)
        self.update_trail(view)
        self.notify()

    def update_trail(self, view):
        activity = view.activity
        if (activity == self.trail_activity and view.active
                and view.lifecycle == "active" and not view.permission):
            return
        self.trail_activity = activity
        self.trail_text = ""
        self.scheduler.cancel(self.trail_timer)
        if (not self.steps_enabled or view.state == "waiting"
                or view.lifecycle != "active" or not view.active):
            self.show_trail()
        else:
            self.trail_timer = self.scheduler.later(0.14, self.show_trail)

    def show_trail(self):
        category, subject = self.trail_activity
        key = "read_file" if category == "read" and subject else category
        self.trail_text = t("activity." + key, name=subject) if key and self.steps_enabled else ""
        self.notify()

    def progress_visible(self):
        view = self.presentation.view
        return (view.started >= 2 or view.lifecycle == "blocked") and not self.progress_dismissed

    def on_ready(self):
        self.ready = True
        self.ready_at = time.monotonic()
        self.status_key = ""
        self.set_visual("idle")
        self.model = self.assistant.selected_model
        self.refresh_models()
        self.notify()

    def on_failed(self, error):
        if (self.voice_thread is not None and self.voice_thread.live):
            self.voice_thread.stop_event.set()
        if self.task_stop_requested:
            self.cancel_current_task()
        if not self.ready:
            self.failed = True
            self.status_key = ""
            self.notice = t("ui.error", error=error)
            self.notice_until = float("inf")
        self.reset_timer()
        self.presentation.finish(self.turn_id, failed=True)
        self.showing_greeting = False
        self.update_subtitles(t("ui.error", error=error))
        self.current_reply = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        if not self.ready:
            self.set_visual("denied_error")
        self.scheduler.later(0.7, self.presentation.settle, self.turn_id)
        self.resume_after_turn(live=False)
        self.notify()

    def on_directory(self, directory):
        self.directory = directory
        self.refresh_branch()
        self.notify()

    def refresh_branch(self, force=False):
        now = time.monotonic()
        if not force and now - self.branch_checked < 3.0:
            return
        self.branch_checked = now
        directory = self.directory
        self.background(self._read_branch, directory)

    def _read_branch(self, directory):
        import os
        import subprocess

        branch = ""
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                ["git", "-C", directory, "symbolic-ref", "--quiet", "--short", "HEAD"],
                capture_output=True, text=True, errors="replace", timeout=2, creationflags=flags)
            if result.returncode == 0:
                branch = result.stdout.strip()
            elif result.returncode == 1:
                result = subprocess.run(
                    ["git", "-C", directory, "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, errors="replace", timeout=2, creationflags=flags)
                if result.returncode == 0:
                    branch = f"detached:{result.stdout.strip()}"
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.scheduler.post(self.set_branch, directory, branch)

    def set_branch(self, directory, branch):
        if directory == self.directory and branch != self.branch:
            self.branch = branch
            self.notify()

    def on_response_surface(self, title):
        self.response_title = title or ""
        self.response_visible = True
        self.notify()

    def timer_seconds(self):
        return 0.0 if self.timer_started is None else time.monotonic() - self.timer_started

    def start_timer(self):
        self.timer_started = time.monotonic()
        self.timer_text = "0s"

    def stop_timer(self):
        if self.timer_started is not None:
            self.timer_text = elapsed(self.timer_seconds())
        self.timer_started = None

    def reset_timer(self):
        self.timer_started = None
        self.timer_text = "0s"

    def timer_label(self):
        return elapsed(self.timer_seconds()) if self.timer_started is not None else self.timer_text

    def update_subtitles(self, text):
        self.subtitle_text = text

    def build_message(self, text):
        controller = self.runner.session.context.task_controller if self.busy else None
        return DesktopMessage(
            text.strip(), tuple(self.attachments.values()),
            resume_task_id=(controller.state.id if controller is not None
                            and controller.state.status == "active" else ""))

    def can_send(self):
        return (all(item.status == "ready" for item in self.attachments.values())
                and sum(item.size for item in self.attachments.values())
                <= load_config()["attachments"]["max_total_bytes"])

    def voice_active(self):
        return self.voice_thread is not None

    def send_message(self, text):
        if not self.ready or self.voice_active():
            return False
        if self.submitting is not None or not self.can_send():
            return False
        message = self.build_message(text)
        if not message.text and not message.attachments:
            return False
        if self.busy and self.stopping:
            return False
        self.submitting = message
        if self.busy:
            self.pending_prompt = message
            self.stop_response()
            return True
        self.start_prompt(message)
        return True

    def on_accepted(self, turn_id):
        if turn_id != self.turn_id or self.submitting is None:
            return
        text = self.submitting.text
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.attachments.clear()
        self.submitting = None
        self.draft_accepted.emit()
        self.notify()

    def on_rejected(self, turn_id, error):
        if turn_id != self.turn_id:
            return
        self.reset_timer()
        self.presentation.finish(turn_id, failed=True)
        self.submitting = None
        self.busy = False
        self.current_reply = None
        if self.voice_thread is not None and self.voice_thread.live:
            self.voice_thread.stop_event.set()
        self.flash(error)

    def start_prompt(self, prompt):
        self.active_prompt = prompt
        self.paused_prompt = None
        self.task_stop_requested = False
        self.status_key = ""
        self.turn_id += 1
        self.presentation.begin(self.turn_id)
        self.showing_greeting = False
        self.runner.cancel_event = threading.Event()
        self.stopping = False
        self.permission_denied_state = False
        self.speaking = False
        self.set_command_output("", False)
        self.current_reply = ""
        self.reply_text = ""
        self.response_visible = False
        self.response_title = ""
        self.start_timer()
        self.update_subtitles(prompt.display_text)
        self.busy = True
        try:
            if not self.worker.is_alive():
                raise RuntimeError(t("ui.worker_unavailable"))
            self.worker.submit(self.runner.ask, self.turn_id, prompt)
        except Exception as error:
            self.on_rejected(self.turn_id, str(error))
        self.notify()

    def set_command_output(self, text, visible):
        self.command_output = text
        self.command_output_visible = visible

    def on_chunk(self, turn_id, chunk):
        if turn_id != self.turn_id or self.current_reply is None:
            return
        self.current_reply += chunk
        self.reply_text += chunk
        if self.text_mode and not self.stopping:
            self.response_visible = True
        self.presentation.writing(turn_id)
        self.notify()

    def on_subtitle(self, turn_id, text):
        if turn_id == self.turn_id and not self.stopping:
            self.update_subtitles(text)
            self.notify()

    def on_audio(self, turn_id, levels):
        if self.muted:
            return
        if turn_id == self.turn_id and (self.busy or not self.ready) and not self.stopping:
            self.levels = levels
            self.notify()

    def on_speaking(self, turn_id, speaking):
        if turn_id != self.turn_id:
            return
        self.speaking = (speaking and not self.muted and (self.busy or not self.ready)
                         and not self.stopping)
        if not self.ready:
            self.set_visual("reading" if self.speaking else "idle")
        else:
            self.presentation.speaking(turn_id, self.speaking)
        if not self.speaking:
            self.levels = []
        self.notify()

    def on_permission_denied(self, turn_id):
        if turn_id == self.turn_id:
            self.permission_denied_state = True
            self.presentation.permission_denied(turn_id)

    def on_finished(self, reply):
        self.stop_timer()
        interrupted = self.stopping
        self.presentation.finish(self.turn_id, interrupted=interrupted,
                                 failed=self.permission_denied_state)
        task_state = self.runner.session.context.task_state
        if self.paused_prompt is not None and (
                task_state is not None and task_state.status == "complete"
                or task_state is None and reply):
            self.paused_prompt = None
        if self.task_stop_requested:
            self.cancel_current_task()
        if self.runner.command_reply:
            self.set_command_output(reply, True)
            self.update_subtitles(reply.splitlines()[0] if reply.strip() else "")
        elif not self.current_reply:
            self.update_subtitles(reply or t("status.paused" if self.paused_prompt is not None else
                                             "status.stopped" if interrupted else "ui.no_response"))
        else:
            self.update_subtitles("")
        if reply.strip():
            self.last_reply = reply
        elif self.reply_text.strip():
            self.last_reply = self.reply_text
        self.current_reply = None
        self.busy = False
        self.speaking = False
        self.stopping = False
        self.levels = []
        if self.paused_prompt is not None:
            self.status_key = "status.paused"
        self.scheduler.later(0.7, self.presentation.settle, self.turn_id)
        self.refresh_branch(force=True)
        self.resume_after_turn()
        self.notify()

    def resume_after_turn(self, *, live=True):
        if self.pending_voice_barge:
            self.pending_voice_barge = False
            self.scheduler.post(self.start_recording)
        else:
            self.resume_pending_prompt()
            if live:
                self.resume_live_listening()

    def resume_pending_prompt(self):
        if self.assistant.shutdown_requested.is_set():
            self.pending_prompt = None
            return
        prompt, self.pending_prompt = self.pending_prompt, None
        if prompt:
            self.start_prompt(prompt)

    def stop_response(self):
        self.stop_timer()
        self.stopping = True
        self.presentation.finish(self.turn_id, interrupted=True)
        self.runner.interrupt()
        self.speaking = False
        self.levels = []
        self.notify()

    def suspended_controller(self):
        controller = self.runner.session.context.task_controller
        if controller is not None and controller.state.status in SUSPENDED:
            return controller
        return None

    def can_stop_task(self):
        return self.ready and (self.busy and not self.stopping or self.paused_prompt is not None)

    def can_pause_task(self):
        return self.ready and self.busy and not self.stopping

    def can_resume_task(self):
        return (self.ready and (self.paused_prompt is not None or self.suspended_controller() is not None)
                and not self.busy and not self.stopping and not self.recording
                and self.voice_thread is None and self.submitting is None
                and self.pending_prompt is None and not self.quitting)

    def pause_current_task(self):
        if not self.can_pause_task():
            return
        self.paused_prompt = self.active_prompt
        self.stop_response()

    def cancel_current_task(self):
        from src.init.task_state import Lifecycle

        context = self.runner.session.context
        controller = context.task_controller
        if (controller is not None and controller.state is context.task_state
                and controller.state.status in {
                Lifecycle.INTERRUPTED, Lifecycle.WAITING, Lifecycle.BLOCKED, Lifecycle.LIMIT_REACHED}):
            controller.state.suspend(Lifecycle.CANCELLED, "Stopped by the user.")
            controller.context.task_controller = controller.pending_task
        self.task_stop_requested = False

    def stop_current_task(self):
        if not self.can_stop_task():
            return
        self.paused_prompt = None
        self.task_stop_requested = True
        self.status_key = ""
        if self.busy:
            if not self.stopping:
                self.stop_response()
        else:
            self.cancel_current_task()
        self.notify()

    def resume_current_task(self):
        if not self.can_resume_task():
            return
        prompt = self.paused_prompt
        context = self.runner.session.context
        controller = context.task_controller
        if (controller is not None and (prompt is None or controller.state is context.task_state)
                and controller.state.status in SUSPENDED):
            prompt = DesktopMessage(t("palette.resume_prompt"),
                                    prompt.attachments if prompt is not None else (),
                                    resume_task_id=controller.state.id)
        self.start_prompt(prompt)

    def run_shell(self, command):
        if not self.ready or self.busy or self.shell is not None or not command.strip():
            return False
        if is_change_directory(command):
            return self.send_message(command.strip())
        self.set_command_output("", True)
        self.notice = ""
        self.last_command = command.strip()
        run = ShellRun(command, self.directory,
                       lambda item: self.scheduler.post(self.on_shell_output, item),
                       lambda item: self.scheduler.post(self.on_shell_done, item))
        self.shell = run
        self.set_visual("executing")
        run.start()
        self.notify()
        return True

    def on_shell_output(self, run):
        if run is self.shell:
            self.command_output = run.output
            self.notify()

    def on_shell_done(self, run):
        if run is not self.shell:
            return
        self.shell = None
        footer = (t("tui.shell_cancelled") if run.cancelled else run.error
                  or t("tui.shell_exit", code=run.exit_code))
        output = run.output.rstrip("\n") or ("" if run.error else t("tui.shell_no_output"))
        self.command_output = (output + "\n" if output else "") + footer
        self.command_output_visible = True
        self.set_visual("idle")
        self.refresh_branch(force=True)
        self.notify()

    def cancel_shell(self):
        if self.shell is not None:
            self.shell.cancel()
            return True
        return False

    def dismiss_output(self):
        if self.shell is None:
            self.set_command_output("", False)
            self.notify()

    def add_files(self, paths):
        limits = load_config()["attachments"]
        known = {normalized_path(item.path) for item in self.attachments.values()}
        added = rejected = 0
        for path in paths:
            if normalized_path(path) in known:
                continue
            if len(self.attachments) >= limits["max_files"]:
                rejected = limits["max_files"]
                break
            known.add(normalized_path(path))
            item = Attachment.pending(path)
            self.attachments[item.id] = item
            added += 1
            self.background(self._validate, item, dict(limits))
        if rejected:
            self.flash(t("ui.attachment_count", count=rejected))
        self.notify()
        return added

    def _validate(self, item, limits):
        try:
            result = inspect_attachment(item, limits)
        except Exception as error:
            result = replace(item, status="error", error=str(error))
        self.scheduler.post(self.on_validated, result)

    def on_validated(self, item):
        if item.id not in self.attachments:
            return
        if any(other.id != item.id and normalized_path(other.path) == normalized_path(item.path)
               and other.status == "ready" for other in self.attachments.values()):
            self.attachments.pop(item.id)
        else:
            self.attachments[item.id] = item
        self.notify()

    def remove_attachment(self, item_id):
        self.attachments.pop(item_id, None)
        self.notify()

    def send_state(self, has_text):
        voice_active = self.voice_active()
        recording = self.recording and voice_active
        live_active = voice_active and self.voice_thread.live
        stopping_available = self.busy and self.speaking and not self.stopping
        kind = ("stop" if stopping_available or recording or live_active
                else "send" if has_text else "mic")
        enabled = self.ready and (live_active or recording or stopping_available or (
            not voice_active and not self.busy and self.submitting is None and self.can_send()))
        return kind, enabled

    def editable(self):
        return self.ready and self.submitting is None and not self.voice_active()

    def primary_action(self, text):
        if self.voice_thread is not None and self.voice_thread.live:
            self.voice_thread.stop_event.set()
            if isinstance(self.pending_prompt, DesktopVoiceMessage):
                self.pending_prompt = None
            if self.busy and not self.stopping:
                self.stop_response()
            self.recording = False
            self.notify()
        elif self.recording:
            self.voice_thread.stop_event.set()
            self.recording = False
            self.notify()
        elif self.voice_thread is not None:
            return
        elif self.busy:
            if self.speaking and not self.stopping:
                self.pending_voice_barge = True
                self.stop_response()
        elif text.strip() or self.attachments:
            self.send_message(text)
        else:
            self.start_recording()

    def start_recording(self):
        if (not self.ready or self.busy or self.submitting is not None
                or self.voice_thread is not None or self.quitting):
            return
        if not self.assistant.voice.supports_playback_reference:
            self.flash(t("voice.restart"))
            return
        try:
            self.assistant.voice.set_playback_reference(True)
        except RuntimeError as error:
            self.flash(str(error))
            return
        thread = VoiceThread(automatic=True, live=True)
        post = self.scheduler.post
        thread.levels.connect(lambda levels: post(self.on_voice_levels, levels))
        thread.processing.connect(lambda: post(self.on_voice_processing))
        thread.speech_started.connect(lambda: post(self.on_voice_started))
        thread.utterance.connect(lambda message: post(self.on_voice_utterance, message))
        thread.finished.connect(lambda: post(self.on_voice_finished, thread))
        self.voice_thread = thread
        self.runner.live_capture = thread
        self.recording = True
        self.levels = []
        self.set_visual("writing")
        thread.start()
        self.notify()

    def on_voice_levels(self, levels):
        if not self.busy or self.stopping:
            self.levels = levels
            self.notify()

    def on_voice_started(self):
        if self.voice_thread is None or self.voice_thread.stop_event.is_set():
            return
        if self.busy and not self.stopping:
            self.stop_response()
        self.recording = True
        self.set_visual("writing")
        self.notify()

    def on_voice_utterance(self, message):
        if self.quitting or self.voice_thread is None or self.voice_thread.stop_event.is_set():
            return
        if self.busy:
            self.pending_prompt = message
            if not self.stopping:
                self.stop_response()
        else:
            self.start_prompt(message)

    def resume_live_listening(self):
        if (self.voice_thread is None or not self.voice_thread.live
                or self.voice_thread.stop_event.is_set() or self.busy or self.quitting):
            return
        self.voice_thread.waiting_response.clear()
        self.recording = True
        self.set_visual("writing")
        self.notify()

    def on_voice_processing(self):
        self.recording = False
        self.set_visual("processing")
        self.levels = []
        self.notify()

    def on_voice_finished(self, thread):
        if thread is not self.voice_thread:
            return
        self.voice_thread = None
        self.runner.live_capture = None
        try:
            self.assistant.voice.set_playback_reference(False)
        except RuntimeError:
            log.exception("Unable to stop playback reference")
        self.recording = False
        self.levels = []
        if not self.busy:
            self.set_visual(self.presentation.view.orb_state)
        if thread.error:
            self.flash(thread.error)
        elif thread.audio_wav and not thread.live:
            self.start_prompt(DesktopVoiceMessage(thread.audio_wav, thread.transcript))
        self.notify()

    def on_confirmation_requested(self, turn_id, message, request_id, timeout):
        if turn_id != self.turn_id:
            return
        if self.stopping:
            self.runner.resolve_confirmation(False, request_id)
            return
        self.presentation.awaiting_permission(turn_id)
        self.confirmation = Confirmation(turn_id, message, request_id, time.monotonic() + timeout)
        self.notify()

    def answer_confirmation(self, accepted):
        confirmation, self.confirmation = self.confirmation, None
        if confirmation is None:
            return
        self.presentation.awaiting_permission(confirmation.turn_id, waiting=False)
        self.runner.resolve_confirmation(accepted, confirmation.request_id)
        self.notify()

    def on_confirmation_closed(self, request_id):
        confirmation = self.confirmation
        if confirmation is not None and confirmation.request_id == request_id:
            self.confirmation = None
            self.presentation.awaiting_permission(confirmation.turn_id, waiting=False)
            self.notify()

    def set_permission_mode(self, mode):
        self.permission_mode = mode
        self.runner.set_permission_mode(mode)
        try:
            config = load_config()
            config["permission_mode"] = mode
            save_config(config)
        except (OSError, ValueError):
            log.exception("Unable to persist permission mode")
        self.notify()

    def toggle_permission_mode(self):
        self.set_permission_mode("auto" if self.permission_mode == "ask" else "ask")

    def refresh_models(self):
        from src.init.brain import main_models

        def read():
            models = list(main_models() or ())
            self.scheduler.post(self.set_models, models)

        self.background(read)

    def set_models(self, models):
        self.models = models
        self.notify()

    def request_model(self, model):
        from src.init.brain import MODEL_OVERRIDE

        if (not model or model == self.model or self.busy or self.model_switching
                or MODEL_OVERRIDE):
            return
        self.model_switching = True
        self.worker.submit(self.runner.select_model, model)
        self.notify()

    def on_model_changed(self, model):
        self.model_switching = False
        self.model = model
        self.notify()

    def on_model_failed(self, error):
        self.model_switching = False
        self.flash(error)

    def toggle_mute(self):
        if not self.voice_enabled:
            self.flash(t("tui.no_voice"))
            return
        self.muted = not self.muted
        self.prefs["muted"] = self.muted
        try:
            self.runner.set_muted(self.muted)
        except Exception as error:
            self.flash(str(error))
        if self.muted:
            self.speaking = False
            self.levels = []
        self.notify()

    def toggle_subtitles(self):
        self.subtitles_enabled = not self.subtitles_enabled
        self.prefs["subtitles"] = self.subtitles_enabled
        self.notify()

    def toggle_steps(self):
        self.steps_enabled = not self.steps_enabled
        self.prefs["ephemeral_steps"] = self.steps_enabled
        self.scheduler.cancel(self.trail_timer)
        self.show_trail()

    def toggle_language(self):
        languages = list(LANGUAGES)
        target = languages[(languages.index(i18n.language()) + 1) % len(languages)]
        try:
            set_language(target)
        except (OSError, ValueError) as error:
            self.flash(t("ui.error", error=error))
            return
        i18n.refresh()
        self.notify()

    def toggle_private(self):
        self.runner.session.private = not self.runner.session.private
        self.notify()

    def on_exit(self):
        self.exit_requested.emit()
