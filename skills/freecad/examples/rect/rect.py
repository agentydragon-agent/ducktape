"""
Minimal FreeCAD script: create a 100x50 rectangle and export to DXF.

Designed to run headlessly (no TechDraw, no GUI). Tested with:
  freecadcmd rect.py

Output written to OUTDIR env var (default: /tmp).
"""

import os
from pathlib import Path

import FreeCAD
import importDXF
import Part

outdir = Path(os.environ.get("OUTDIR", "/tmp"))
outdir.mkdir(parents=True, exist_ok=True)

doc = FreeCAD.newDocument("RectTest")

# A closed rectangular wire: 100 x 50
pts = [
    FreeCAD.Vector(0, 0, 0),
    FreeCAD.Vector(100, 0, 0),
    FreeCAD.Vector(100, 50, 0),
    FreeCAD.Vector(0, 50, 0),
    FreeCAD.Vector(0, 0, 0),  # close
]
wire = Part.makePolygon(pts)
face = Part.Face(wire)

feat = doc.addObject("Part::Feature", "Rect")
feat.Shape = face
doc.recompute()

importDXF.export([feat], str(outdir / "rect.dxf"))
doc.saveAs(str(outdir / "rect.FCStd"))

os._exit(0)
