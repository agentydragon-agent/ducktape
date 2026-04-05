"""
Build a compound shape from a wall shell and a closed rectangle, then export via TechDraw.

Demonstrates:
- Part.makeCompound for grouping multiple faces into a single Part::Feature
- Wall shell as fully constrained sketch geometry (inner + outer outlines with thickness)
- Single compound, single TechDraw view (preserves relative positions)

Runs inside freecadcmd under xvfb (needs Qt event pump for TechDraw view computation).
Output directory is read from OUTDIR env var (default: current directory).

Usage:
  OUTDIR=/tmp/out xvfb-run -a -s "-screen 0 1024x768x24" freecadcmd build_compound.py
"""

import os
import time
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher

Gui.showMainWindow()

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

qapp = QtWidgets.QApplication.instance()
import TechDraw  # noqa: E402

outdir = os.environ.get("OUTDIR", ".")

# === Parameters (FreeCAD uses mm internally) ===
ROOM_W = 4000.0  # mm (4 m)
ROOM_H = 3000.0  # mm (3 m)
TABLE_W = 1200.0  # mm (1.2 m)
TABLE_H = 600.0  # mm (0.6 m)
TABLE_X = 500.0  # mm — table offset from left wall
TABLE_Y = 500.0  # mm — table offset from bottom wall
WALL_THICKNESS = 150.0  # mm (15 cm)


def pump(seconds=3):
    """Process Qt events to let TechDraw background computation run."""
    for _ in range(int(seconds * 10)):
        if qapp:
            qapp.processEvents()
        time.sleep(0.1)


# === Sketch (fully constrained) ===
doc = App.newDocument("CompoundExample")
sk = doc.addObject("Sketcher::SketchObject", "Layout")

# Wall shell: L-shaped closed polygon with 6 vertices tracing inner and outer outlines.
# All geometry is constrained — dimensions drive the shape.
#
#    s4(Rw-t,Rh+t)──s3(Rw+t,Rh+t)
#         │              │
#         │  right wall  │
#         │              │
#    s5(Rw-t,t)          │
#         │              │
#  s6(0,t)┘              │
#    │                   │
#  s1(0,-t)──────────s2(Rw+t,-t)
#        bottom wall
#
# Points (counterclockwise from bottom-left outer):
t = WALL_THICKNESS
pts = [
    App.Vector(0, -t, 0),  # s1: bottom-left outer
    App.Vector(ROOM_W + t, -t, 0),  # s2: bottom-right outer
    App.Vector(ROOM_W + t, ROOM_H + t, 0),  # s3: top-right outer
    App.Vector(ROOM_W - t, ROOM_H + t, 0),  # s4: top-right inner (cap)
    App.Vector(ROOM_W - t, t, 0),  # s5: inner L-bend
    App.Vector(0, t, 0),  # s6: bottom-left inner
]
# 6 line segments forming the closed shell
wall_indices = []
for i in range(6):
    j = (i + 1) % 6
    idx = sk.addGeometry(Part.LineSegment(pts[i], pts[j]))
    wall_indices.append(idx)
s1, s2, s3, s4, s5, s6 = wall_indices

# Chain corners (each segment end → next segment start)
for i in range(6):
    sk.addConstraint(Sketcher.Constraint("Coincident", wall_indices[i], 2, wall_indices[(i + 1) % 6], 1))

# Orientation constraints
for i in [s1, s3, s5]:  # bottom outer, top cap, inner horizontal
    sk.addConstraint(Sketcher.Constraint("Horizontal", i))
for i in [s2, s4, s6]:  # right outer, right inner, left cap
    sk.addConstraint(Sketcher.Constraint("Vertical", i))

# Pin bottom-left outer corner (s1 start) at origin X, below origin Y by thickness
sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, s1, 1, 0.0))
sk.addConstraint(Sketcher.Constraint("DistanceY", s1, 1, -1, 1, t))

# Dimensional constraints — all positive values (swap point order for reversed segments)
# 4 independent lengths (top cap and left cap are implied by the other four)
sk.addConstraint(Sketcher.Constraint("DistanceX", s1, 1, s1, 2, ROOM_W + t))  # bottom outer →
sk.addConstraint(Sketcher.Constraint("DistanceY", s2, 1, s2, 2, ROOM_H + 2 * t))  # right outer ↑
sk.addConstraint(Sketcher.Constraint("DistanceY", s4, 2, s4, 1, ROOM_H))  # inner right ↓ (swapped)
sk.addConstraint(Sketcher.Constraint("DistanceX", s5, 2, s5, 1, ROOM_W - t))  # inner bottom ← (swapped)

# Table: fully constrained rectangle
x, y, w, h = TABLE_X, TABLE_Y, TABLE_W, TABLE_H
t0 = sk.addGeometry(Part.LineSegment(App.Vector(x, y, 0), App.Vector(x + w, y, 0)))
t1 = sk.addGeometry(Part.LineSegment(App.Vector(x + w, y, 0), App.Vector(x + w, y + h, 0)))
t2 = sk.addGeometry(Part.LineSegment(App.Vector(x + w, y + h, 0), App.Vector(x, y + h, 0)))
t3 = sk.addGeometry(Part.LineSegment(App.Vector(x, y + h, 0), App.Vector(x, y, 0)))
for a, b in [(t0, t1), (t1, t2), (t2, t3), (t3, t0)]:
    sk.addConstraint(Sketcher.Constraint("Coincident", a, 2, b, 1))
for i in [t0, t2]:
    sk.addConstraint(Sketcher.Constraint("Horizontal", i))
for i in [t1, t3]:
    sk.addConstraint(Sketcher.Constraint("Vertical", i))
sk.addConstraint(Sketcher.Constraint("DistanceX", t0, 1, t0, 2, w))
sk.addConstraint(Sketcher.Constraint("DistanceY", t1, 1, t1, 2, h))
sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, t0, 1, x))
sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, t0, 1, y))
table_indices = (t0, t1, t2, t3)

doc.recompute()
assert sk.FullyConstrained, "Sketch not fully constrained!"
print(f"Sketch: {sk.GeometryCount} geom, {sk.ConstraintCount} constraints")

# === Part Features ===
# Extract solved geometry from sketch → Part faces → compound


def sketch_face(indices):
    """Build a Part.Face from sketch geometry indices."""
    edges = [
        Part.makeLine(
            App.Vector(sk.Geometry[i].StartPoint.x, sk.Geometry[i].StartPoint.y, 0),
            App.Vector(sk.Geometry[i].EndPoint.x, sk.Geometry[i].EndPoint.y, 0),
        )
        for i in indices
    ]
    return Part.Face(Part.Wire(edges))


all_faces = [sketch_face(wall_indices), sketch_face(table_indices)]

feat = doc.addObject("Part::Feature", "AllShapes")
feat.Shape = Part.makeCompound(all_faces)
doc.recompute()
print(f"Compound: {len(all_faces)} faces")

# === TechDraw Page ===
tmpl_path = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates", "ISO", "A4_Landscape_blank.svg")  # noqa: PTH118 — FreeCAD API expects str
page = doc.addObject("TechDraw::DrawPage", "Page")
tmpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
tmpl.Template = tmpl_path
page.Template = tmpl

view = doc.addObject("TechDraw::DrawViewPart", "TopView")
page.addView(view)
view.Source = [feat]
view.Direction = App.Vector(0, 0, 1)
view.Scale = 1.0
view.X = 150
view.Y = 120

doc.recompute(None, True, True)
pump(5)
doc.recompute(None, True, True)
pump(2)

n_edges = len(view.getVisibleEdges())
print(f"TechDraw view: {n_edges} visible edges")
assert n_edges > 0, "TechDraw view has 0 edges — Qt event pump may have failed"

# === Export ===
dxf_path = os.path.join(outdir, "compound.dxf")  # noqa: PTH118 — FreeCAD API expects str
TechDraw.writeDXFPage(page, dxf_path)
print(f"DXF: {Path(dxf_path).stat().st_size} bytes")

fcstd_path = os.path.join(outdir, "compound.FCStd")  # noqa: PTH118 — FreeCAD API expects str
doc.saveAs(fcstd_path)

os._exit(0)  # Skip Qt cleanup to avoid potential segfault under xvfb
