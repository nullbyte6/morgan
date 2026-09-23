"""Render selectable flowchart nodes and arrows in Arlo's Macchiato colors."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene

from .layout import NODE_GAP, NODE_HEIGHT, NODE_WIDTH, node_positions
from .schema import Flowchart, FlowchartNode

BACKGROUND = QColor("#24273a")
SURFACE = QColor("#363a4f")
TEXT = QColor("#cad3f5")
BORDER = QColor("#494d64")
ACCENT = QColor("#8aadf4")
SELECTION = QColor("#b7bdf8")


class NodeItem(QGraphicsPathItem):
    """A selectable shape with plain text and a full-label tooltip."""

    def __init__(self, node: FlowchartNode):
        super().__init__()
        self.node = node
        bounds = QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)
        path = QPainterPath()
        if node.kind == "decision":
            path.addPolygon(QPolygonF([
                QPointF(NODE_WIDTH / 2, 0), QPointF(NODE_WIDTH, NODE_HEIGHT / 2),
                QPointF(NODE_WIDTH / 2, NODE_HEIGHT), QPointF(0, NODE_HEIGHT / 2),
            ]))
            path.closeSubpath()
        else:
            radius = NODE_HEIGHT / 2 if node.kind == "terminal" else 16
            path.addRoundedRect(bounds, radius, radius)
        self.setPath(path)
        self.setPen(QPen(BORDER, 2))
        self.setBrush(SURFACE)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setToolTip(node.label)
        self.setData(0, node.id)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(1)

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(SURFACE)
        painter.setPen(QPen(SELECTION if self.isSelected() else BORDER, 2))
        painter.drawPath(self.path())
        text_rect = QRectF(20, 12, NODE_WIDTH - 40, NODE_HEIGHT - 24)
        if self.node.kind == "decision":
            text_rect = QRectF(60, 26, NODE_WIDTH - 120, NODE_HEIGHT - 52)
        painter.setClipRect(text_rect)
        painter.setPen(TEXT)
        font = QFont(painter.font())
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, self.node.label)
        painter.restore()


def render_flowchart(scene: QGraphicsScene, chart: Flowchart) -> dict[str, NodeItem]:
    """Replace a scene with nodes and directed, orthogonal connections."""
    scene.clear()
    scene.setBackgroundBrush(BACKGROUND)
    positions = node_positions(chart)
    items = {}
    for node in chart.nodes:
        item = NodeItem(node)
        item.setPos(*positions[node.id])
        scene.addItem(item)
        items[node.id] = item
    for index, edge in enumerate(chart.edges):
        source_y = positions[edge.source][1]
        target_y = positions[edge.target][1]
        if target_y == source_y + NODE_HEIGHT + NODE_GAP:
            points = [QPointF(NODE_WIDTH / 2, source_y + NODE_HEIGHT),
                      QPointF(NODE_WIDTH / 2, target_y)]
        else:
            lane = NODE_WIDTH + 40 + index * 16
            points = [QPointF(NODE_WIDTH, source_y + NODE_HEIGHT / 2),
                      QPointF(lane, source_y + NODE_HEIGHT / 2),
                      QPointF(lane, target_y - 28),
                      QPointF(NODE_WIDTH / 2, target_y - 28),
                      QPointF(NODE_WIDTH / 2, target_y)]
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        line = scene.addPath(path, QPen(ACCENT, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        line.setAcceptedMouseButtons(Qt.NoButton)
        tip = points[-1]
        arrow = scene.addPolygon(QPolygonF([
            tip, tip + QPointF(-6, -11), tip + QPointF(6, -11),
        ]), QPen(ACCENT), ACCENT)
        arrow.setAcceptedMouseButtons(Qt.NoButton)
    scene.setSceneRect(scene.itemsBoundingRect().adjusted(-400, -400, 400, 400))
    return items
