# TODO

## Panel label: show the most urgent / most restrictive limit

Right now the panel shows both windows (5h and 7d for Claude, primary/secondary for Codex)
unconditionally. Most of the time the short burst window (5h / primary) is not the binding
constraint — the weekly one is. The label should surface whichever limit is tightest (highest
`used_percent`, or closest to reset if both are high), so a quick glance immediately shows the
real pressure. Only show the non-binding window if it is itself close to exhausted.

Current state observed: 7d at 93%, 5h at 3% — panel still leads with the 5h number.

## Show staleness indicator when data is old

If the last successful fetch was more than ~5 minutes ago (e.g. network down, machine
suspended and resumed), add a visual cue so stale data is not mistaken for live. Options:
a `⚠` prefix, greyed-out text via CSS (`opacity: 0.5`), or a trailing `·` dot. Record
`this._lastFetchTime = Date.now()` on each successful parse and check the age in
`_updateLabel()`.

## More compact + graphical presentation

Replace raw `%` text in the panel label with a small visual indicator (e.g. a Unicode block
fill character like `▁▂▃▄▅▆▇█`, or a simple filled/empty bar using `■□`) so quota level is
legible at a glance without parsing numbers. Something like:

```
C ▆ | O ▂
```

where the block height encodes used percentage. The detailed popup can still show exact numbers.

## Use provider icons instead of "C" / "O" text prefixes

Replace the `C` and `O` letter prefixes in the panel label with the actual brand icons. Both
providers use SVG logos that are available publicly:

- Claude: the Anthropic/Claude icon (the angular "A" or Claude face mark)
- Codex/OpenAI: the OpenAI logo (the swirl/bloom mark)

In GNOME Shell extensions, panel icons are typically `St.Icon` with a `gicon` set to a
`Gio.FileIcon` pointing to an SVG, or embedded as a `St.Icon` with `icon-name` if the icon
is in the theme. Ship small SVG files in the extension directory and load them via
`Gio.File.new_for_path(extension.path + '/icons/claude.svg')`. Scale to ~16px.

## Align detail popup format between Claude and Codex

Claude popup: `Claude  5h: 3% ↻4h35m  7d: 93% ↻90h48m`
Codex popup: `Codex  primary: 3% ↻4h35m  secondary: 93% ↻90h48m`

Rename to consistent labels and align spacing so the two rows look parallel. Suggested:

```
Claude  burst: 3% ↻4h35m   weekly: 93% ↻90h48m
Codex   burst: 3% ↻4h35m   weekly: 93% ↻90h48m
```
