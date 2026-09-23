"""Deterministic vertical layout for the initial flowchart viewer."""

from .schema import Flowchart

NODE_WIDTH = 240.0
NODE_HEIGHT = 96.0
NODE_GAP = 72.0


def node_positions(chart: Flowchart) -> dict[str, tuple[float, float]]:
    """Place nodes in input order with a fixed gap between their bounds."""
    return {node.id: (0.0, index * (NODE_HEIGHT + NODE_GAP))
            for index, node in enumerate(chart.nodes)}
