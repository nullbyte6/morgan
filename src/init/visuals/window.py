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
"""Standalone viewer. Run with python -m src.init.visuals.window."""

import sys
from html import escape
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QMainWindow

from src.init.utils import get_stylesheet, resource_path

from src.init.visuals.renderer import BACKGROUND, render_flowchart
from src.init.visuals.schema import Flowchart


def demo_flowchart() -> Flowchart:
    """Return a branching file-analysis workflow with a shared finish step."""
    return Flowchart.model_validate({
        "title": "File Analysis",
        "nodes": [
            {"id": "start", "label": "Start", "kind": "terminal"},
            {"id": "read_file", "label": "Read File", "kind": "process"},
            {"id": "valid_file", "label": "Valid File?", "kind": "decision"},
            {"id": "analyze_data", "label": "Analyze Data", "kind": "process"},
            {"id": "report_error", "label": "Report Error", "kind": "process"},
            {"id": "finish_task", "label": "Finish Task", "kind": "process"},
            {"id": "end", "label": "End", "kind": "terminal"},
        ],
        "edges": [
            {"source": "start", "target": "read_file"},
            {"source": "read_file", "target": "valid_file"},
            {"source": "valid_file", "target": "analyze_data", "label": "Yes"},
            {"source": "valid_file", "target": "report_error", "label": "No"},
            {"source": "analyze_data", "target": "finish_task"},
            {"source": "report_error", "target": "finish_task"},
            {"source": "finish_task", "target": "end"},
        ],
    })


class FlowchartView(QGraphicsView):
    """A selectable canvas with bounded wheel zoom and background-drag panning."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(BACKGROUND)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setAccessibleName("Flowchart canvas")
        self.setToolTip("Click a node to select it. Drag the background to pan. Scroll to zoom.")

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta:
            event.ignore()
            return
        position = event.position().toPoint()
        before = self.mapToScene(position)
        current = self.transform().m11()
        target = max(0.25, min(3.0, current * 1.15 ** (max(-480, min(480, delta)) / 120)))
        self.scale(target / current, target / current)
        after = self.mapToScene(position)
        self.translate(after.x() - before.x(), after.y() - before.y())
        event.accept()


class FlowchartWindow(QMainWindow):
    """An independent window with no assistant or model initialization."""

    def __init__(self, chart: Flowchart | None = None, parent=None):
        super().__init__(parent)
        self.chart = chart if chart is not None else demo_flowchart()
        self.setWindowTitle(f"Arlo Flowchart — {self.chart.title}")
        self.resize(800, 720)
        self.setMinimumSize(400, 360)
        self.scene = QGraphicsScene(self)
        try:
            self.nodes = render_flowchart(self.scene, self.chart)
        except Exception:
            self.deleteLater()
            raise
        self.view = FlowchartView(self.scene, self)
        self.setCentralWidget(self.view)
        if self.chart.description:
            self.setToolTip("<qt>" + escape(self.chart.description).replace("\n", "<br/>") + "</qt>")
        self.view.centerOn(self.scene.itemsBoundingRect().center())
        self._initial_view_pending = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._initial_view_pending:
            self._initial_view_pending = False
            QTimer.singleShot(0, self._fit_initial_view)

    def _fit_initial_view(self):
        """Frame the initial graph once without resetting later user navigation."""
        bounds = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        viewport = self.view.viewport().rect()
        scale = max(0.25, min(1.0, viewport.width() / bounds.width(), viewport.height() / bounds.height()))
        self.view.resetTransform()
        self.view.scale(scale, scale)
        self.view.centerOn(bounds.center())


def main() -> int:
    """Launch the local demo without importing the agent, Ollama or TTS."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(get_stylesheet())
    assets = Path(__file__).resolve().parents[3] / "assets"
    font_path = resource_path(assets, "fonts", "Inter_24pt-Regular.ttf")
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if families:
            app.setFont(QFont(families[0], 11))
    window = FlowchartWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
