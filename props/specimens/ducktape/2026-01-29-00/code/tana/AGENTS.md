@README.md

# Agent Guide for `tana`

## Gotchas

- `TanaGraph` sets the `_graph` reference on nodes; avoid calling legacy
  `attach_supertag_property` helpers—supertags resolve via `node.supertags`.
- Prefer absolute imports (`tana.query.search_parser`, etc.) to keep layering clear.
- CLI scripts expect JSON dumps that mirror Tana’s export structure (`docs` array with node dicts).
