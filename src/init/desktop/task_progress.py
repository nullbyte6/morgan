from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)


class TaskProgressPill(QWidget):
    """A dismissible view of the desktop's existing execution-phase signals."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskProgressHost")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.turn_id = None
        self.started = 0
        self.completed = 0
        self.active = False
        self.dismissed = False
        self.state = "running"
        self.language = "spanish"
        self.order_title = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 14, 20, 12)
        row.setSpacing(0)
        self.pill = QFrame(self)
        self.pill.setObjectName("taskProgressPill")
        self.pill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        body = QVBoxLayout(self.pill)
        body.setContentsMargins(20, 12, 16, 14)
        body.setSpacing(8)
        heading = QHBoxLayout()
        heading.setSpacing(12)
        self.title = QLabel()
        self.title.setObjectName("taskProgressTitle")
        self.title.setTextFormat(Qt.PlainText)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("taskProgressClose")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(self.dismiss)
        heading.addWidget(self.title, 1)
        heading.addWidget(self.close_button)
        body.addLayout(heading)
        self.bar = QProgressBar()
        self.bar.setObjectName("taskProgressBar")
        self.bar.setTextVisible(False)
        body.addWidget(self.bar)
        self.step = QLabel()
        self.step.setObjectName("taskProgressStep")
        self.step.setTextFormat(Qt.PlainText)
        self.step.setWordWrap(True)
        body.addWidget(self.step)
        row.addWidget(self.pill)
        row.addStretch(1)
        self.refresh_language(self.language)
        self.hide()

    def begin(self, turn_id, title):
        self.turn_id = turn_id
        self.order_title = " ".join(str(title).split())[:240]
        self.started = self.completed = 0
        self.active = True
        self.dismissed = False
        self.state = "running"
        self.hide()
        self._render()

    @Slot(int, str)
    def on_phase(self, turn_id, phase):
        if turn_id != self.turn_id or not self.active:
            return
        if phase == "executing":
            self.started += 1
            self.state = "running"
        elif phase == "processing" and self.completed < self.started:
            self.completed += 1
            self.state = "running"
        else:
            return
        self._render()
        if self.started >= 2 and not self.dismissed:
            self.show()

    def awaiting_permission(self, turn_id, *, waiting=True):
        if turn_id == self.turn_id and self.active:
            self.state = "waiting" if waiting else "running"
            self._render()

    def finish(self, turn_id, *, interrupted=False, failed=False):
        if turn_id != self.turn_id or not self.active:
            return
        self.active = False
        # Never invent completion for a step whose result has not arrived.
        self.state = ("stopped" if interrupted else "error" if failed
                      else "finished" if self.completed == self.started else "stopped")
        self._render()

    @Slot()
    def dismiss(self):
        self.dismissed = True
        self.hide()

    def refresh_language(self, language):
        self.language = language
        spanish = language != "english"
        close = "Ocultar progreso (la tarea continúa)" if spanish else "Hide progress (task continues)"
        self.close_button.setToolTip(close)
        self.close_button.setAccessibleName(close)
        self.bar.setToolTip(
            "Pasos realizados de los detectados hasta ahora; Arlo puede añadir más."
            if spanish else "Finished steps out of those detected so far; Arlo may add more.")
        self._render()

    def _render(self):
        spanish = self.language != "english"
        title = self.order_title or ("Orden de voz" if spanish else "Voice request")
        self.title.setToolTip(title)
        self.title.setAccessibleName(title)
        self.title.setText(self.title.fontMetrics().elidedText(
            title, Qt.ElideRight, max(1, self.title.width())))
        count = (f"{self.completed} de {self.started} pasos realizados" if spanish
                 else f"{self.completed} of {self.started} steps finished")
        labels = ({"waiting": "Esperando permiso", "stopped": "Detenida",
                   "error": "Finalizada con incidencias", "finished": "Ejecución finalizada"}
                  if spanish else
                  {"waiting": "Awaiting permission", "stopped": "Stopped",
                   "error": "Finished with issues", "finished": "Execution finished"})
        if self.state == "running":
            detail = ((f"Ejecutando paso {self.completed + 1}" if spanish
                       else f"Executing step {self.completed + 1}")
                      if self.completed < self.started else
                      ("Revisando resultados…" if spanish else "Reviewing results…"))
        else:
            detail = labels[self.state]
        self.step.setText(f"{detail} · {count}")
        self.bar.setRange(0, max(1, self.started))
        self.bar.setValue(self.completed)
        self.bar.setAccessibleName(self.step.text())
        for widget in (self.pill, self.bar):
            if widget.property("state") != self.state:
                widget.setProperty("state", self.state)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def showEvent(self, event):
        super().showEvent(event)
        self._render()
