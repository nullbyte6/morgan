"""A concise, debounced view of the current observable task activity."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QSizePolicy

from src.init.lang import tr


class ActivityTrail(QLabel):
    def __init__(self, presentation, parent=None):
        super().__init__(parent)
        self.setObjectName("activityTrail")
        self.setProperty("orbContext", True)
        self.setAlignment(Qt.AlignCenter)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.presentation = presentation
        self.activity = ("", "")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(140)
        self.timer.timeout.connect(self._render)
        presentation.changed.connect(self.on_view)
        self.hide()

    def on_view(self, view):
        activity = view.activity
        if activity == self.activity and view.active and view.lifecycle == "active" and not view.permission:
            return
        self.activity = activity
        self.clear()
        self.setToolTip("")
        self.setAccessibleName("")
        self.timer.stop()
        if view.state == "waiting" or view.lifecycle != "active" or not view.active:
            self._render()
        else:
            self.timer.start()

    def refresh_language(self, _language=None):
        if self.activity[0] and not self.timer.isActive():
            self._render()

    def _render(self):
        category, subject = self.activity
        key = "read_file" if category == "read" and subject else category
        text = tr("activity." + key, name=subject) if key else ""
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setText(self.fontMetrics().elidedText(text, Qt.ElideRight, max(1, self.width())))
        self.setVisible(bool(text))
        self.updateGeometry()

    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(self.fontMetrics().height() + 4)
        return size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.timer.isActive():
            self._render()
