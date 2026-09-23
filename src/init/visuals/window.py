"""Standalone viewer. Run with python -m src.init.visuals.window."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QMainWindow

from src.init.utils import get_stylesheet, resource_path

from src.init.visuals.renderer import BACKGROUND, render_flowchart
from src.init.visuals.schema import Flowchart


def demo_flowchart() -> Flowchart:
    """Return the fixed three-node example for this milestone."""
    return Flowchart.model_validate({
        "title": "File Analysis",
        "nodes": [
            {"id": "start", "label": "Start", "kind": "terminal"},
            {"id": "read_file", "label": "Read File", "kind": "process"},
            {"id": "analyze_data", "label": "Analyze Data", "kind": "process"},
        ],
        "edges": [
            {"source": "start", "target": "read_file"},
            {"source": "read_file", "target": "analyze_data"},
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
        self.nodes = render_flowchart(self.scene, self.chart)
        self.view = FlowchartView(self.scene, self)
        self.setCentralWidget(self.view)
        self.view.centerOn(self.scene.itemsBoundingRect().center())


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
