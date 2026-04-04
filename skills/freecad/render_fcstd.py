"""
Render a FreeCAD FCStd file to PNG with 3D perspective and lighting.

Runs inside freecadcmd under xvfb (needs Qt/OpenGL for 3D viewport rendering).
Reads INPUT env var for the FCStd path and OUTDIR for output directory.

Usage:
  INPUT=/work/model.FCStd OUTDIR=/output xvfb-run -a -s "-screen 0 1024x768x24" freecadcmd render_fcstd.py
"""

import os
import time

import FreeCAD as App
import FreeCADGui as Gui

Gui.showMainWindow()

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

qapp = QtWidgets.QApplication.instance()


def pump(seconds=3):
    """Process Qt events to let FreeCAD's background computation run."""
    for _ in range(int(seconds * 10)):
        if qapp:
            qapp.processEvents()
        time.sleep(0.1)


input_path = os.environ.get("INPUT", "cube_with_hole.FCStd")
outdir = os.environ.get("OUTDIR", ".")

# === Load document ===
doc = App.openDocument(input_path)
App.setActiveDocument(doc.Name)
Gui.ActiveDocument = Gui.getDocument(doc.Name)

pump(2)

# Ensure all objects are visible with proper display mode
for obj in doc.Objects:
    if hasattr(obj, "ViewObject"):
        vo = obj.ViewObject
        vo.Visibility = True
        if hasattr(vo, "DisplayMode"):
            vo.DisplayMode = "Shaded"
        if hasattr(vo, "ShapeColor"):
            vo.ShapeColor = (0.75, 0.75, 0.80)  # light blue-gray
        if hasattr(vo, "Lighting"):
            vo.Lighting = "Two side"
        if hasattr(vo, "Transparency"):
            vo.Transparency = 0

pump(2)

view = Gui.ActiveDocument.ActiveView

# === Configure view ===
# Set white background before rendering
param = App.ParamGet("User parameter:BaseApp/Preferences/View")
param.SetBool("Gradient", False)
param.SetUnsigned("BackgroundColor", 0xFFFFFFFF)

view.viewIsometric()
view.fitAll()

pump(3)

view.fitAll()

# === Save image ===
output_path = os.path.join(outdir, "cube_with_hole.png")  # noqa: PTH118 — FreeCAD API expects str
view.saveImage(output_path, 800, 600, "Current")
print(f"Rendered: {output_path}")

os._exit(0)  # Skip Qt cleanup to avoid potential segfault under xvfb
