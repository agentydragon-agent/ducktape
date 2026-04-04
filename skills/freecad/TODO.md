# FreeCAD Skill TODOs

## Rendering pipeline

- [x] Fix ezdxf font discovery in Bazel sandbox — solved by pointing `ezdxf.options.support_dirs` at matplotlib's bundled DejaVu fonts directory.
- [ ] Fix DXF rendering quality: dimension labels overlap each other, corner lines extend beyond intersection points. Investigate whether `parametric_rect.py` produces a correctly constrained sketch or if the TechDraw projection is introducing artifacts.
- [x] Fonts in the rendered PNG test — golden regenerated with working font rendering.
- [x] Call ezdxf drawing API directly instead of shelling out via `subprocess` — now uses `Frontend` + `MatplotlibFileOutput` directly with `BackgroundPolicy.WHITE` and `finalize=True`.

## FreeCAD scripting

- [ ] Entity-referenced dimensions: `DrawViewDimension.References2D = [(view, 'Edge0')]` should allow dimensions that reference specific projected edges and auto-update when sketch changes. Current working approach uses `makeDistanceDim` with computed points — functional but not entity-bound.
- [ ] Annotation anchoring: annotations are absolute-positioned on the page. Investigate if TechDraw has leaders/balloons that anchor to view geometry.
- [ ] DXF layer styling: set line colors/weights per DXF layer so `ezdxf draw` renders with visual hierarchy (walls thick/dark, furniture light).

## 3D

- [ ] Raytraced renders: Coin3D shading works but is basic. Investigate FreeCAD Render workbench for POV-Ray/LuxRender output.
- [ ] Multi-view drawings: front/side/top views on one TechDraw page for 3D objects.
- [ ] Assemblies: multi-part models with positioning.
