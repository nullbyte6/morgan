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
"""Validated, bounded input for local flowcharts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NodeId = Annotated[str, StringConstraints(
    strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class FlowchartNode(BaseModel):
    """A named process, decision or terminal node."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: NodeId = Field(
        description=(
            "Unique machine-readable identifier. Use ASCII snake_case, "
            "such as 'productos_finales'. Never use spaces, accents, "
            "or display labels as IDs."))

    label: Label = Field(
        description=(
            "Human-readable node title. Spaces and accented characters "
            "are allowed, such as 'Productos Finales'."))

    kind: Literal["process", "decision", "terminal"] = "process"
    description: Description | None = None


class FlowchartEdge(BaseModel):
    """A directed connection between two node IDs."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: NodeId = Field(
        description="Exact ID of an existing source node, not its label.")

    target: NodeId = Field(
        description="Exact ID of an existing target node, not its label.")

    label: Label | None = None
    description: Description | None = None


class Flowchart(BaseModel):
    """An immutable chart of at most 100 nodes and 200 directed edges."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: Label = "Flowchart"
    description: Description | None = None
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
