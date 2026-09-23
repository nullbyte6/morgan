"""Validated, bounded input for local flowcharts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NodeId = Annotated[str, StringConstraints(
    strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class FlowchartNode(BaseModel):
    """A named process, decision or terminal node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NodeId
    label: Label
    kind: Literal["process", "decision", "terminal"] = "process"


class FlowchartEdge(BaseModel):
    """A directed connection between two node IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: NodeId
    target: NodeId


class Flowchart(BaseModel):
    """An immutable chart of at most 100 nodes and 200 directed edges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: Label = "Flowchart"
    nodes: tuple[FlowchartNode, ...] = Field(min_length=1, max_length=100)
    edges: tuple[FlowchartEdge, ...] = Field(default=(), max_length=200)

    @model_validator(mode="after")
    def validate_references(self):
        identifiers = {node.id for node in self.nodes}
        if len(identifiers) != len(self.nodes):
            raise ValueError("Node IDs must be unique")
        for edge in self.edges:
            if edge.source not in identifiers or edge.target not in identifiers:
                raise ValueError("Every edge must reference existing nodes")
        return self
