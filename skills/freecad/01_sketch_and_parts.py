"""
Example: Create a constrained sketch and extract Part features for TechDraw.
Demonstrates rectangle helper, wall segments as thin faces, and single-compound approach.
"""

import sys

sys.path.insert(0, "/usr/lib/freecad-python3/lib")
import FreeCAD as App
import Part
import Sketcher

# === PARAMETERS ===
width = 175.0
depth = 58.4
desk_w = 76.0
desk_h = 165.0

# === SKETCH ===
doc = App.newDocument("Example")
sk = doc.addObject("Sketcher::SketchObject", "Layout")


def add_rect(sketch, x, y, w, h, construction=False):
    """Add a fully constrained rectangle. Returns (i0,i1,i2,i3) geometry indices."""
    i0 = sketch.addGeometry(Part.LineSegment(App.Vector(x, y, 0), App.Vector(x + w, y, 0)), construction)
    i1 = sketch.addGeometry(Part.LineSegment(App.Vector(x + w, y, 0), App.Vector(x + w, y + h, 0)), construction)
    i2 = sketch.addGeometry(Part.LineSegment(App.Vector(x + w, y + h, 0), App.Vector(x, y + h, 0)), construction)
    i3 = sketch.addGeometry(Part.LineSegment(App.Vector(x, y + h, 0), App.Vector(x, y, 0)), construction)
    for a, b in [(i0, i1), (i1, i2), (i2, i3), (i3, i0)]:
        sketch.addConstraint(Sketcher.Constraint("Coincident", a, 2, b, 1))
    for i in [i0, i2]:
        sketch.addConstraint(Sketcher.Constraint("Horizontal", i))
    for i in [i1, i3]:
        sketch.addConstraint(Sketcher.Constraint("Vertical", i))
    sketch.addConstraint(Sketcher.Constraint("DistanceX", i0, 1, i0, 2, w))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", i1, 1, i1, 2, h))
    sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, i0, 1, x))
    sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, i0, 1, y))
    return (i0, i1, i2, i3)


# Walls (non-construction)
w0 = sk.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(width, 0, 0)), False)
sk.addConstraint(Sketcher.Constraint("Coincident", w0, 1, -1, 1))  # pin to origin
sk.addConstraint(Sketcher.Constraint("Horizontal", w0))
sk.addConstraint(Sketcher.Constraint("DistanceX", w0, 1, w0, 2, width))

w1 = sk.addGeometry(Part.LineSegment(App.Vector(width, 0, 0), App.Vector(width, depth, 0)), False)
sk.addConstraint(Sketcher.Constraint("Coincident", w1, 1, w0, 2))  # chain to wall end
sk.addConstraint(Sketcher.Constraint("Perpendicular", w0, w1))  # perpendicular to first wall
sk.addConstraint(Sketcher.Constraint("DistanceY", w1, 1, w1, 2, depth))

# Desk (non-construction, positioned at origin)
desk_indices = add_rect(sk, 0, 0, desk_w, desk_h, False)

doc.recompute()
assert sk.FullyConstrained, "Under-constrained!"
print(f"Geometry: {sk.GeometryCount}, Constraints: {sk.ConstraintCount}")

# === PART FEATURES ===
# Single compound of Faces for TechDraw (preserves relative positions)
all_faces = []

# Walls: thin face strips (0.3cm) for open segments
for i in range(2):  # w0, w1
    geo = sk.Geometry[i]
    p1, p2 = App.Vector(geo.StartPoint.x, geo.StartPoint.y, 0), App.Vector(geo.EndPoint.x, geo.EndPoint.y, 0)
    dx, dy = p2.x - p1.x, p2.y - p1.y
    length = (dx**2 + dy**2) ** 0.5
    t = 0.3
    nx, ny = -dy / length * t, dx / length * t
    corners = [p1, p2, App.Vector(p2.x + nx, p2.y + ny, 0), App.Vector(p1.x + nx, p1.y + ny, 0)]
    wire = Part.makePolygon([*corners, corners[0]])
    all_faces.append(Part.Face(Part.Wire(wire.Edges)))

# Desk: closed rectangle → Face
desk_edges = []
for i in desk_indices:
    geo = sk.Geometry[i]
    desk_edges.append(
        Part.makeLine(App.Vector(geo.StartPoint.x, geo.StartPoint.y, 0), App.Vector(geo.EndPoint.x, geo.EndPoint.y, 0))
    )
all_faces.append(Part.Face(Part.Wire(desk_edges)))

feat = doc.addObject("Part::Feature", "AllShapes")
feat.Shape = Part.makeCompound(all_faces)

doc.recompute()
doc.saveAs("/home/claude/example_sketch.FCStd")
print(f"Saved. Compound: {len(all_faces)} faces")
