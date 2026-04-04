# FreeCAD Skill TODOs

## Rendering pipeline

- [ ] Fix ezdxf font discovery in Bazel sandbox — dimension text renders as tofu (empty squares) because ezdxf can't find fonts. Need to bundle a font via data dep or point ezdxf at matplotlib's bundled DejaVu fonts via env var.
- [ ] Fix DXF rendering quality: dimension labels overlap each other, corner lines extend beyond intersection points. Investigate whether `parametric_rect.py` produces a correctly constrained sketch or if the TechDraw projection is introducing artifacts.
- [ ] Fonts in the rendered PNG test — currently the test passes because golden and actual both have the same missing-font tofu squares. Once fonts are fixed, regenerate golden.
- [ ] Call ezdxf drawing API directly instead of shelling out via `subprocess`. The CLI is Python — find the right internal API call (likely in `ezdxf.__main__` or `ezdxf.addons.drawing`) that handles color inversion, viewport fitting, and font setup correctly. Previous attempt using `Frontend` + `MatplotlibBackend` directly rendered invisible output.

## FreeCAD scripting

- [ ] Entity-referenced dimensions: `DrawViewDimension.References2D = [(view, 'Edge0')]` should allow dimensions that reference specific projected edges and auto-update when sketch changes. Current working approach uses `makeDistanceDim` with computed points — functional but not entity-bound.
- [ ] Annotation anchoring: annotations are absolute-positioned on the page. Investigate if TechDraw has leaders/balloons that anchor to view geometry.
- [ ] DXF layer styling: set line colors/weights per DXF layer so `ezdxf draw` renders with visual hierarchy (walls thick/dark, furniture light).

## 3D

- [ ] 3D operations: extrude sketch faces into solids (`Part.extrude`), boolean operations, assemblies.
- [ ] 3D rendering: FreeCAD's raytracing/render workbench, or export to external renderers. May need POV-Ray or LuxRender.
- [ ] Colored/textured renders: investigate if TechDraw views can carry color per-face, or if 3D viewport screenshots are possible under xvfb.
- [ ] Multi-view drawings: front/side/top views on one TechDraw page for 3D objects.
