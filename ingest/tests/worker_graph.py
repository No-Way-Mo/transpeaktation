"""Tiny synthetic OSM graph for worker tests.

    1 ---- 2      two-way east-west street (edges 1-2-0 and 2-1-0), ~88 m, "Test St", maxspeed 25 mph
    3
    |             one-way northbound (edge 3-4-0), ~111 m, no maxspeed
    4 (north)
"""
from __future__ import annotations

import json
from pathlib import Path

A = (-122.4000, 37.7800)   # node 1
B = (-122.3990, 37.7800)   # node 2
C = (-122.3950, 37.7800)   # node 3
D = (-122.3950, 37.7810)   # node 4

GRAPHML = """<?xml version='1.0' encoding='utf-8'?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="d0" for="node" attr.name="x" attr.type="string"/>
  <key id="d1" for="node" attr.name="y" attr.type="string"/>
  <key id="d2" for="edge" attr.name="name" attr.type="string"/>
  <key id="d3" for="edge" attr.name="highway" attr.type="string"/>
  <key id="d4" for="edge" attr.name="length" attr.type="string"/>
  <key id="d5" for="edge" attr.name="maxspeed" attr.type="string"/>
  <key id="d6" for="edge" attr.name="oneway" attr.type="string"/>
  <key id="d7" for="edge" attr.name="geometry" attr.type="string"/>
  <graph edgedefault="directed">
    <node id="1"><data key="d0">{A[0]}</data><data key="d1">{A[1]}</data></node>
    <node id="2"><data key="d0">{B[0]}</data><data key="d1">{B[1]}</data></node>
    <node id="3"><data key="d0">{C[0]}</data><data key="d1">{C[1]}</data></node>
    <node id="4"><data key="d0">{D[0]}</data><data key="d1">{D[1]}</data></node>
    <edge source="1" target="2" id="0"><data key="d2">Test St</data><data key="d3">residential</data>
      <data key="d4">88.0</data><data key="d5">['25 mph', '30 mph']</data><data key="d6">False</data></edge>
    <edge source="2" target="1" id="0"><data key="d2">Test St</data><data key="d3">residential</data>
      <data key="d4">88.0</data><data key="d5">25 mph</data><data key="d6">False</data></edge>
    <edge source="3" target="4" id="0"><data key="d2">North Way</data><data key="d3">secondary</data>
      <data key="d4">111.0</data><data key="d6">True</data>
      <data key="d7">LINESTRING ({C[0]} {C[1]}, {C[0]} 37.7805, {D[0]} {D[1]})</data></edge>
  </graph>
</graphml>
""".format(A=A, B=B, C=C, D=D)

EAST = "1-2-0"
WEST = "2-1-0"
NORTH = "3-4-0"


def write_graph(directory: Path) -> Path:
    path = directory / "osm_drive_graph.graphml"
    path.write_text(GRAPHML, encoding="utf-8")
    return path


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def along(a: tuple, b: tuple, n: int) -> list[list[float]]:
    """n+1 evenly spaced points from a to b."""
    return [[a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n] for i in range(n + 1)]
