"""
Export FCStd → DXF via TechDraw.

Console mode (default, no xvfb needed — uses cached TechDraw views from FCStd):
  freecadcmd export_dxf.py <input.FCStd> <output.dxf>

GUI mode (recomputes TechDraw views via Qt event pump, needs xvfb):
  xvfb-run -a -s "-screen 0 1024x768x24" freecadcmd export_dxf.py --gui <input.FCStd> <output.dxf>

Render to PNG: python3 -m ezdxf draw --background WHITE --dpi 200 -f -o output.png output.dxf
"""

import os
import sys
import time

gui_mode = "--gui" in sys.argv
args = [a for a in sys.argv[1:] if a != "--gui"]
fcstd_path = args[0] if len(args) > 0 else "input.FCStd"
dxf_path = args[1] if len(args) > 1 else "output.dxf"

import FreeCAD as App  # noqa: E402 — must parse args before FreeCAD import

if gui_mode:
    import FreeCADGui as Gui

    Gui.showMainWindow()
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    qapp = QtWidgets.QApplication.instance()

    def pump(seconds=3):
        for _ in range(int(seconds * 10)):
            if qapp:
                qapp.processEvents()
            time.sleep(0.1)


import TechDraw  # noqa: E402

doc = App.openDocument(fcstd_path)
doc.recompute(None, True, True)
if gui_mode:
    pump(5)
    doc.recompute(None, True, True)
    pump(2)

# Find the TechDraw page
page = None
for obj in doc.Objects:
    if obj.TypeId == "TechDraw::DrawPage":
        page = obj
        break

if not page:
    print("ERROR: No TechDraw::DrawPage found")
    sys.exit(1)

# Report view edge counts
for obj in doc.Objects:
    if "DrawViewPart" in obj.TypeId:
        print(f"{obj.Name}: {len(obj.getVisibleEdges())} edges")

TechDraw.writeDXFPage(page, dxf_path)
from pathlib import Path  # noqa: E402

print(f"Exported: {dxf_path} ({Path(dxf_path).stat().st_size} bytes)")

if gui_mode:
    os._exit(0)  # Skip Qt cleanup to avoid segfault under xvfb
