# Noisebridge laser — calibration log

Machine: Noisebridge **Kaitian CM1309**, ~150 W CO2, Ruida controller (bed/table moves in Z).
LightBurn-driven. Cut params: power %, speed mm/s.

## Machine basics (mechanics)

- **The bed/table moves in Z** (not the head's Z drive). **Increasing commanded Z = bed
  moves UP, toward the tool head** → the head↔material gap shrinks and focus goes deeper
  into the material. Decreasing Z = bed down, gap grows, focus rises above the surface.
- **Bed hard limit (top of travel):** max commanded **Z 2999.9** — the bed physically
  cannot go higher. Any rise must fit entirely below this.
- **Crash limit:** the bed rising until the material hits the head — i.e. when the
  head↔material gap (= the focus-spacer thickness, currently 7.4 mm) closes to zero.
- **The tool head height is independently adjustable** over a range, via a **wingnut**.
  Focus is set mechanically: loosen the wingnut, sandwich `[head | spacer | material top]`,
  tighten, remove the spacer. So **focus is decoupled from bed commanded Z** — you can make
  the focus sandwich with the bed parked anywhere in a range, then pick a bed Z that leaves
  room to rise under the hard limit.
- Power capped at **55%** (Noisebridge tube-life rule). 8.4 mm ply is over their stated
  ~6 mm reliable cut depth for the 150 W.

## Z-axis conversion factor

**The Z axis is badly miscalibrated — the table moves ~3.69× the commanded distance.**
Commanded Z (controller readout) does NOT equal physical travel. All `z_offset_mm` /
`z_per_pass_mm` values sent to this machine must be scaled by `1/f` to get real mm.

### Measurement — 2026-06-16

| Quantity                     | Value                          |
| ---------------------------- | ------------------------------ |
| Controller Z readout (lower) | 2962.4 mm                      |
| Controller Z readout (top)   | 2999.9–3000.0 mm               |
| Commanded span               | 37.6 mm (37.5 if top = 2999.9) |
| Actual span (caliper)        | 138.7 mm                       |
| **Conversion factor `f`**    | **138.7 / 37.6 ≈ 3.69**        |

`f = actual / commanded`. Direction: moving up. Single measurement so far.

### How to use it

To achieve a **true physical** Z move of `d` mm, command `d / f`:

- software scale = `1/f ≈ 0.271`
- real −0.7 mm step → command **−0.190 mm**
- real −0.1 mm offset → command **−0.027 mm**

So in the material-test TOML, set `z_offset_mm = real_offset × 0.271` and
`z_per_pass_mm = real_step × 0.271`.

Equivalent: previously commanding `z_per_pass_mm = -0.7` actually moved the focus
**~2.58 mm per pass** (−0.7 × 3.69) — overshooting focus every layer. Likely the main
cause of the inconsistent 8.4 mm cuts.

### TODO / confirm

- [ ] Repeat the measurement (2nd pair, ideally a longer span and the other direction)
      to confirm `f` and check linearity + backlash.
- [ ] If trained/authorized: the real fix is the Ruida vendor Z **step length**
      (`new_step = old_step × actual / commanded`). NB manual says don't change machine
      settings unless trained — otherwise compensate in software (above).
- [x] Run a focus test and record the focus offset (see below).

## Focus test — 2026-06-17

Photo: <focus-test-2026-06-17.jpg> (LightBurn Focus Test ladder; lines go from
wide/charred at the top to a fine kerf near focus).

### Setup

- Material: flat offcut, surface of interest on top.
- Focus reference: **7.4 mm spacer** on the material at commanded **Z 2999.0**, head
  dropped onto it (so 7.4 mm ≈ this lens's focal/gauge distance).
- Lowered to commanded **Z 2997.5** before the test (−1.5 commanded = −5.5 mm physical
  below the reference).
- LightBurn Focus Test: start Z **0.00**, end Z **2.5 mm** (commanded), ~24 lines.
- Cut params: **25 mm/s**, power **min 12% / max 15%**, single pass.

### Result

**Sharpest (narrowest, deepest) line at offset Z = 1.5 mm commanded** (LightBurn mark).

- Focus offset 1.5 commanded × `f` (3.69) ≈ **5.5 mm physical** above the 2997.5 start.
- That lands at absolute commanded **Z 2999.0** — i.e. exactly the 7.4 mm-spacer
  reference. The spacer method sets focus correctly.

### How to focus this machine

**Drop the head onto a 7.4 mm spacer on the material surface at commanded Z 2999.0.**
(7.4 mm ≈ the focal/gauge distance for the current lens.)

## Z command granularity

LightBurn/Ruida Z fields accept a **minimum increment of 0.1 commanded mm**. With
`f ≈ 3.69` the physical Z quantum is therefore:

| commanded | physical |
| --------- | -------- |
| 0.1       | 0.37 mm  |
| 0.2       | 0.74 mm  |
| 0.3       | 1.11 mm  |

All `z_offset_mm` / `z_per_pass_mm` values in cut configs must be exact multiples of
0.1 commanded, or LightBurn rounds them unpredictably. Finer Z would require fixing the
Ruida vendor step-length (trained-maintainer only) — not worth it.

## Planned experiment — 8.4 mm plywood cut scan (8mm_plywood_3)

Config: <8mm_plywood_3.toml> → `8mm_plywood_3.lbrn2`. **Not yet run.**

Goal: find a recipe that severs 8.4 mm ply consistently, now that focus + Z are known.
Prior failures were the Z miscalibration (focus jumped ~2.6 mm/pass); energy was never
the limiter, so this scan fixes energy and sweeps **pass count × focus step-down**.

| Axis | Param        | Values (commanded) | physical                |
| ---- | ------------ | ------------------ | ----------------------- |
| X    | `num_passes` | 4, 5, 6, 7         | —                       |
| Y    | `z_per_pass` | 0.0, +0.1, +0.2    | 0, +0.37, +0.74 mm/pass |

`z_per_pass` is **positive** = bed rises = focus deepens (this machine's convention; the
bed/table moves up to push focus into the board). Held constant: power **50%** (min=max,
under the 55% tube cap), speed **20 mm/s**, `z_offset = 0.0` (focus at surface).

Z envelope: focus is set by the head wingnut (sandwich `[head | 7.4mm spacer | material]`),
so the bed Z at focus is whatever you park it at — set it **≤ ~2998.6 commanded** so the
rise stays under the 2999.9 hard limit. Crash budget: worst cell = 7 passes × +0.2 = 1.2
commanded = 4.43 mm physical rise → 2.97 mm clearance below the 7.4 mm gap; reaches
≤ ~2999.8. Rule: keep `(max_passes − 1) × z_per_pass_cmd ≤ 1.35`.

At the machine:

1. Material on bed. Sandwich `[head | 7.4mm spacer | material top]`, bed parked at
   commanded Z **≤ ~2998.6**; tighten the wingnut; **remove the spacer**.
2. On the first cell, confirm the bed **rises** over passes (focus going deeper). If it
   drops instead, the Z sign is flipped — negate `z_per_pass` and rerun.
3. Judge each 20 mm square from the back: it passes only if it drops out cleanly.
4. If even 7 passes / +0.2 won't sever: round 2 raises the pass cap and/or slows to
   12–15 mm/s — not power past 55%.

### Result

_(fill in after running)_
