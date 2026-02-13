# Font rendering investigation: gVisor vs RBE pixel diffs

## Root cause

**The Inter font was never loading.** The visual test's HTTP server was rooted
at `tests/harness/`, but `test-fonts.css` references `../fonts/Inter.woff2`
which the browser resolves to `/fonts/Inter.woff2` — outside the server root.
Both local (gVisor) and remote (RBE) fell back to different system sans-serif
fonts, producing 1-4% pixel diffs.

The initial investigation (render_glyphs.mjs, glyph pixel data) also had broken
font loading — it used `data:` URLs for `@font-face`, which don't work for web
font loading. The "74/88 glyphs have different measured widths" finding was
comparing different system fallback fonts, not Inter.

## Proof: widths are identical when font loads

`font_load_spike.mjs` serves Inter via HTTP (matching the real test pattern).
With Inter loading correctly, `measureText()` widths are **bit-for-bit
identical** across gVisor (Intel Emerald Rapids) and RBE (AMD EPYC Turin):

```
'0' = 20.1875000000  (both)
'a' = 17.9687500000  (both)
'g' = 19.6250000000  (both)
'W' = 31.5312500000  (both)
```

The text metrics path (FreeType -> HarfBuzz -> Skia -> measureText) uses only
exact IEEE 754 operations (`floorf`, `ceilf`, `floor`) — no transcendental
`libm` functions whose implementations could differ across CPU architectures.

## Fix applied

Server root changed from `tests/harness/` to `tests/` (parent directory), so
`/fonts/Inter.woff2` maps to `tests/fonts/Inter.woff2`. All page URLs now use
`/harness/` prefix. Added a font load check that fails fast if Inter doesn't
load. Pixel diff tolerance tightened from 5% to 2%.

## Environment data (still valid)

- `env_dump_gvisor.txt`, `env_dump_rbe.txt`: Full environment dumps
- `glyph_pixels_gvisor.txt`, `glyph_pixels_rbe.txt`: Per-glyph pixel data
  (captured with broken font loading — shows system font differences, not Inter)
- `dump_env.sh`: Environment dump script (Bazel `sh_test`)
- `render_glyphs.mjs`: Per-glyph pixel extraction (broken font loading via data: URL)
- `measure_widths.mjs`: Raw measureText() width extraction (HTTP font serving)
- `font_load_spike.mjs`: Font loading verification spike (HTTP font serving)

Bazel targets (`manual` tag, not in CI):

- `//props/frontend:font_rendering_dump_env`
- `//props/frontend:font_rendering_glyph_pixels`
- `//props/frontend:font_rendering_measure_widths`
- `//props/frontend:font_rendering_spike`
