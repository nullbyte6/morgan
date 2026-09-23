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
"""Deterministic hierarchical geometry, independent of Qt and data models."""

from collections import deque
from dataclasses import dataclass
from statistics import mean

NODE_WIDTH = 240.0
NODE_HEIGHT = 96.0
NODE_GAP = 80.0
BRANCH_GAP = 120.0
PORT_GAP = 24.0
TRACK_GAP = 36.0


@dataclass(frozen=True)
class NodeGeometry:
    """Scene bounds and rank of one node."""

    x: float
    y: float
    width: float
    height: float
    rank: int


@dataclass(frozen=True)
class EdgeGeometry:
    """Orthogonal route and label anchor, in original edge order."""

    points: tuple[tuple[float, float], ...]
    label_anchor: tuple[float, float]


@dataclass(frozen=True)
class GraphLayout:
    """Computed geometry that never becomes part of the input schema."""

    nodes: dict[str, NodeGeometry]
    edges: tuple[EdgeGeometry, ...]


def hierarchical_layout(node_ids, edges) -> GraphLayout:
    """Rank a DAG, balance its layers and route edges through reserved lanes.

    Inputs are node IDs and source/target pairs. Long edges receive intermediate
    slots so their paths cannot pass through intervening nodes. Distinct tracks
    avoid coincident horizontal segments; crossings in nonplanar graphs remain
    possible. Invalid references, duplicate node IDs and cycles are rejected.
    """
    node_ids, edges = list(node_ids), list(edges)
    if not node_ids or len(set(node_ids)) != len(node_ids):
        raise ValueError("Layout requires nonempty, unique node IDs")
    index = {node_id: i for i, node_id in enumerate(node_ids)}
    parents = [[] for _ in node_ids]
    children = [[] for _ in node_ids]
    for source, target in edges:
        if source not in index or target not in index:
            raise ValueError("Every edge must reference existing nodes")
        children[index[source]].append(index[target])
        parents[index[target]].append(index[source])
    pending = [len(items) for items in parents]
    queue = deque(i for i, degree in enumerate(pending) if not degree)
    ranks = [0] * len(node_ids)
    visited = 0
    while queue:
        source = queue.popleft()
        visited += 1
        for target in children[source]:
            ranks[target] = max(ranks[target], ranks[source] + 1)
            pending[target] -= 1
            if not pending[target]:
                queue.append(target)
    if visited != len(node_ids):
        raise ValueError("Hierarchical layout requires a directed acyclic graph")
    layers = [[] for _ in range(max(ranks) + 1)]
    for vertex, rank in enumerate(ranks):
        layers[rank].append(vertex)
    incoming = {i: [] for i in range(len(node_ids))}
    outgoing = {i: [] for i in range(len(node_ids))}
    chains = []
    next_vertex = len(node_ids)
    for source, target in edges:
        start, end = index[source], index[target]
        chain = [start]
        for rank in range(ranks[start] + 1, ranks[end]):
            layers[rank].append(next_vertex)
            incoming[next_vertex], outgoing[next_vertex] = [], []
            chain.append(next_vertex)
            next_vertex += 1
        chain.append(end)
        chains.append(chain)
        for left, right in zip(chain, chain[1:]):
            outgoing[left].append(right)
            incoming[right].append(left)
    order = {vertex: i for layer in layers for i, vertex in enumerate(layer)}
    for _ in range(4):
        for sequence, neighbors in ((layers[1:], incoming), (layers[-2::-1], outgoing)):
            for layer in sequence:
                layer.sort(key=lambda vertex: (
                    mean(order[n] for n in neighbors[vertex]) if neighbors[vertex] else order[vertex],
                    order[vertex]))
                order.update({vertex: i for i, vertex in enumerate(layer)})
    degree = max(len(neighbors) for mapping in (incoming, outgoing) for neighbors in mapping.values())
    width = max(NODE_WIDTH, (degree + 3) * PORT_GAP)
    pitch = width + BRANCH_GAP
    centers = {vertex: (i - (len(layer) - 1) / 2) * pitch
               for layer in layers for i, vertex in enumerate(layer)}
    for _ in range(6):
        for sequence, neighbors in ((layers, incoming), (layers[::-1], outgoing)):
            for layer in sequence:
                desired = [mean(centers[n] for n in neighbors[v]) if neighbors[v] else centers[v]
                           for v in layer]
                placed = []
                for position in desired:
                    placed.append(max(position, placed[-1] + pitch) if placed else position)
                shift = mean(placed) - mean(desired)
                centers.update({v: round((x - shift) / PORT_GAP) * PORT_GAP
                                for v, x in zip(layer, placed)})
    segments = [[] for _ in layers[:-1]]
    vertex_ranks = {v: rank for rank, layer in enumerate(layers) for v in layer}
    for edge_id, chain in enumerate(chains):
        for source, target in zip(chain, chain[1:]):
            segments[vertex_ranks[source]].append((edge_id, source, target))
    heights = [0.0]
    for band in segments:
        heights.append(heights[-1] + NODE_HEIGHT + max(NODE_GAP, (len(band) + 1) * TRACK_GAP))
    routes = [[] for _ in edges]
    anchors = [None for _ in edges]
    for rank, band in enumerate(segments):
        exits, entries = {}, {}
        for endpoint, ports, neighbor in ((1, exits, 2), (2, entries, 1)):
            groups = {}
            for segment in band:
                groups.setdefault(segment[endpoint], []).append(segment)
            for vertex, group in groups.items():
                group.sort(key=lambda segment: (centers[segment[neighbor]], segment[0]))
                for i, (edge_id, _, _) in enumerate(group):
                    ports[edge_id] = centers[vertex] + (i - (len(group) - 1) / 2) * PORT_GAP
        for edge_id, x in list(entries.items()):
            if any(other != edge_id and abs(x - source_x) < PORT_GAP / 4
                   for other, source_x in exits.items()):
                entries[edge_id] += PORT_GAP / 4
        band.sort(key=lambda segment: (min(exits[segment[0]], entries[segment[0]]), segment[0]))
        for track, (edge_id, source, target) in enumerate(band, 1):
            start_y = heights[rank] + NODE_HEIGHT
            end_y = heights[rank + 1]
            track_y = start_y + track * TRACK_GAP
            source_x, target_x = exits[edge_id], entries[edge_id]
            points = [(source_x, start_y), (source_x, track_y),
                      (target_x, track_y), (target_x, end_y)]
            if routes[edge_id]:
                points.insert(0, (source_x, heights[rank]))
            routes[edge_id].extend(points)
            if anchors[edge_id] is None:
                anchors[edge_id] = ((source_x + target_x) / 2, track_y)
    nodes = {node_id: NodeGeometry(centers[i] - width / 2, heights[ranks[i]], width, NODE_HEIGHT, ranks[i])
             for i, node_id in enumerate(node_ids)}
    return GraphLayout(nodes, tuple(EdgeGeometry(_simplify(points), anchor)
                                    for points, anchor in zip(routes, anchors)))


def _simplify(points):
    """Remove duplicate points and redundant bends without changing the route."""
    result = []
    for point in points:
        if result and point == result[-1]:
            continue
        while len(result) >= 2 and (
                result[-2][0] == result[-1][0] == point[0]
                or result[-2][1] == result[-1][1] == point[1]):
            result.pop()
        result.append(point)
    return tuple(result)


def node_positions(chart) -> dict[str, tuple[float, float]]:
    """Return hierarchical positions through the original convenience API."""
    layout = hierarchical_layout([node.id for node in chart.nodes],
                                 [(edge.source, edge.target) for edge in chart.edges])
    return {node_id: (node.x, node.y) for node_id, node in layout.nodes.items()}
