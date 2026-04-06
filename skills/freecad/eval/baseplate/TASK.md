# Task: Parametric Mounting Baseplate

Produce a FreeCAD file `baseplate.FCStd` containing a parametric mounting
baseplate. The model must be fully parametric — all dimensions driven by a
spreadsheet, sketch fully constrained.

## Shape

A rectangular plate (200 x 120 mm) with:

- 10 mm radius fillet on each corner
- 4 mounting holes, 8 mm diameter, centered 20 mm from the two nearest edges
- A rectangular slot (40 x 15 mm) centered on the plate, with the long axis
  parallel to the plate width

## Parametric behavior

Changing the plate width from 200 to 250 must widen the plate, shift the
right-side holes, keep the slot centered, and leave the height unchanged.

## TechDraw

Include a TechDraw page with a dimensioned top-down view.
