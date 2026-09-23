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
"""Render selectable flowchart nodes and arrows in Arlo's Macchiato colors."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem

from .layout import NODE_HEIGHT, NODE_WIDTH, NodeGeometry, hierarchical_layout
from .schema import Flowchart, FlowchartNode

BACKGROUND = QColor("#24273a")
SURFACE = QColor("#363a4f")
TEXT = QColor("#cad3f5")
BORDER = QColor("#494d64")
ACCENT = QColor("#8aadf4")
SELECTION = QColor("#b7bdf8")


class NodeItem(QGraphicsPathItem):
    """A selectable shape with plain text and a full-label tooltip."""

    def __init__(self, node: FlowchartNode, geometry: NodeGeometry | None = None):
        super().__init__()
        self.node = node
        self.width = geometry.width if geometry else NODE_WIDTH
        self.height = geometry.height if geometry else NODE_HEIGHT
        bounds = QRectF(0, 0, self.width, self.height)
        path = QPainterPath()
        if node.kind == "decision":
            path.addPolygon(QPolygonF([
                QPointF(self.width / 2, 0), QPointF(self.width, self.height / 2),
                QPointF(self.width / 2, self.height), QPointF(0, self.height / 2),
            ]))
            path.closeSubpath()
        else:
            radius = self.height / 2 if node.kind == "terminal" else 16
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
        text_rect = QRectF(20, 12, self.width - 40, self.height - 24)
        if self.node.kind == "decision":
            text_rect = QRectF(self.width / 4, 26, self.width / 2, self.height - 52)
        painter.setClipRect(text_rect)
        painter.setPen(TEXT)
        font = QFont(painter.font())
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, self.node.label)
        painter.restore()


class EdgeLabelItem(QGraphicsSimpleTextItem):
    """A padded plain-text label on the scene background."""

    def boundingRect(self):
        return super().boundingRect().adjusted(-4, -2, 4, 2)

    def paint(self, painter, option, widget=None):
        painter.fillRect(self.boundingRect(), BACKGROUND)
        super().paint(painter, option, widget)


def _place_label(label, anchor, segments):
    """Find the nearest clear horizontal interval in the label's reserved row."""
    bounds = label.boundingRect()
    center_x, track_y = anchor
    top = track_y - bounds.height() - 6
    bottom = top + bounds.height()
    blocked = []
    for start, end in segments:
        if start.x() == end.x() and max(start.y(), end.y()) >= top and min(start.y(), end.y()) <= bottom:
            blocked.append((start.x() - 4, start.x() + 4))
        elif start.y() == end.y() and top <= start.y() <= bottom:
            blocked.append((min(start.x(), end.x()) - 4, max(start.x(), end.x()) + 4))
    preferred = center_x - bounds.width() / 2
    candidates = [preferred]
    for left, right in blocked:
        candidates.extend((left - bounds.width() - 2, right + 2))
    valid = [x for x in candidates if all(x + bounds.width() <= left or x >= right
                                         for left, right in blocked)]
    left = min(valid, key=lambda x: (abs(x - preferred), x))
    label.setPos(left - bounds.left(), top - bounds.top())


def _boundary_point(point, node, geometry, *, entering):
    """Project a vertical port onto the actual diamond or rounded boundary."""
    x, y = point
    offset = abs(x - geometry.x - geometry.width / 2)
    if node.kind == "decision":
        inset = offset * geometry.height / geometry.width
    else:
        radius = geometry.height / 2 if node.kind == "terminal" else 16
        corner_offset = max(0, offset - (geometry.width / 2 - radius))
        inset = radius - (max(0, radius * radius - corner_offset * corner_offset)) ** 0.5
    return QPointF(x, y + inset if entering else y - inset)


def render_flowchart(scene: QGraphicsScene, chart: Flowchart) -> dict[str, NodeItem]:
    """Replace a scene with nodes and directed, orthogonal connections."""
    layout = hierarchical_layout([node.id for node in chart.nodes],
                                 [(edge.source, edge.target) for edge in chart.edges])
    scene.clear()
    scene.setBackgroundBrush(BACKGROUND)
    items = {}
    for node in chart.nodes:
        geometry = layout.nodes[node.id]
        item = NodeItem(node, geometry)
        item.setPos(geometry.x, geometry.y)
        scene.addItem(item)
        items[node.id] = item
    label_font = QFont(scene.font())
    label_font.setPointSize(10)
    label_metrics = QFontMetricsF(label_font)
    segments = []
    labels = []
    for edge, route in zip(chart.edges, layout.edges):
        points = [QPointF(*point) for point in route.points]
        points[0] = _boundary_point(route.points[0], items[edge.source].node,
                                    layout.nodes[edge.source], entering=False)
        points[-1] = _boundary_point(route.points[-1], items[edge.target].node,
                                     layout.nodes[edge.target], entering=True)
        segments.extend(zip(points, points[1:]))
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        line = scene.addPath(path, QPen(ACCENT, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        line.setAcceptedMouseButtons(Qt.NoButton)
        tip = points[-1]
        direction = tip - points[-2]
        length = (direction.x() ** 2 + direction.y() ** 2) ** 0.5
        direction /= length
        normal = QPointF(-direction.y(), direction.x())
        arrow = scene.addPolygon(QPolygonF([
            tip, tip - direction * 11 + normal * 6, tip - direction * 11 - normal * 6,
        ]), QPen(ACCENT), ACCENT)
        arrow.setAcceptedMouseButtons(Qt.NoButton)
        if edge.label is not None:
            label = EdgeLabelItem(label_metrics.elidedText(edge.label, Qt.ElideRight, 160))
            label.setFont(label_font)
            label.setBrush(TEXT)
            label.setToolTip(edge.label)
            label.setAcceptedMouseButtons(Qt.NoButton)
            label.setZValue(2)
            labels.append((label, route.label_anchor))
    for label, anchor in labels:
        _place_label(label, anchor, segments)
        scene.addItem(label)
    scene.setSceneRect(scene.itemsBoundingRect().adjusted(-400, -400, 400, 400))
    return items
