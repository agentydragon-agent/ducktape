"""
Example: Set up TechDraw page, add dimensions, add annotations.
Run under xvfb: timeout 60 xvfb-run -a -s "-screen 0 1024x768x24" freecadcmd this_script.py

Key discovery: TechDraw computes views in a background Qt thread.
You MUST pump Qt events with processEvents() — sleep() alone doesn't work.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, "/usr/lib/freecad-python3/lib")
import FreeCAD as App
import FreeCADGui as Gui

Gui.showMainWindow()
from PySide2 import QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance()
import Part  # noqa: E402
import TechDraw  # noqa: E402


def pump(seconds=3):
    """Process Qt events to let TechDraw background computation run."""
    for _ in range(int(seconds * 10)):
        if app:
            app.processEvents()
        time.sleep(0.1)


# === Create a simple test shape ===
doc = App.newDocument("DimExample")
edges = [
    Part.makeLine(App.Vector(0, 0, 0), App.Vector(100, 0, 0)),
    Part.makeLine(App.Vector(100, 0, 0), App.Vector(100, 60, 0)),
    Part.makeLine(App.Vector(100, 60, 0), App.Vector(0, 60, 0)),
    Part.makeLine(App.Vector(0, 60, 0), App.Vector(0, 0, 0)),
]
feat = doc.addObject("Part::Feature", "Rect")
feat.Shape = Part.Face(Part.Wire(edges))

# === TechDraw page ===
page = doc.addObject("TechDraw::DrawPage", "Page")
tmpl = doc.addObject("TechDraw::DrawSVGTemplate", "Tmpl")
tmpl.Template = "/usr/share/freecad/Mod/TechDraw/Templates/A3_Landscape_blank.svg"
page.Template = tmpl

view = doc.addObject("TechDraw::DrawViewPart", "TopView")
page.addView(view)
view.Source = [feat]
view.Direction = App.Vector(0, 0, 1)
view.Scale = 1.0
view.X = 200
view.Y = 150

doc.recompute(None, True, True)
pump(5)  # CRITICAL: let TechDraw compute edges

print(f"Edges: {len(view.getVisibleEdges())}")

# === Dimensions ===
# makeDistanceDim takes UNSCALED 2D view-local points (relative to shape center).
# The shape center is the midpoint of the bounding box.
bb = feat.Shape.BoundBox
cx, cy = (bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2


def vpt(sketch_x, sketch_y):
    """Convert sketch coords to view-local unscaled coords."""
    return App.Vector(sketch_x - cx, sketch_y - cy, 0)


# Width dimension along bottom edge
d1 = TechDraw.makeDistanceDim(view, "DistanceX", vpt(0, -8), vpt(100, -8))
if d1:
    page.addView(d1)

# Height dimension along right edge
d2 = TechDraw.makeDistanceDim(view, "DistanceY", vpt(108, 0), vpt(108, 60))
if d2:
    page.addView(d2)

# NOTE: These dimensions measure from arbitrary points, not edge references.
# For entity-referenced dimensions, use DrawViewDimension with References2D:
#   dim.References2D = [(view, 'Edge0')]
# This requires knowing edge indices from view.getVisibleEdges().
# TODO: test entity-referenced dimensions that auto-update when sketch changes.

# === Annotations ===
ann = doc.addObject("TechDraw::DrawViewAnnotation", "Label")
page.addView(ann)
ann.Text = ["100 x 60 Rectangle"]
# Position using same sk2page formula:
ann.X = 200 + (50 - cx) * view.Scale  # centered on shape
ann.Y = 150 - (30 - cy) * view.Scale
ann.TextSize = 5

doc.recompute(None, True, True)
pump(2)

# === Export ===
TechDraw.writeDXFPage(page, "/home/claude/dim_example.dxf")
doc.saveAs("/home/claude/dim_example.FCStd")
print(f"DXF: {Path('/home/claude/dim_example.dxf').stat().st_size} bytes")
print("Done. Render with: python3 -m ezdxf draw --background WHITE --dpi 200 -f -o output.png dim_example.dxf")
sys.exit(0)
