# Adapter exposing gaffer-private-built artifacts as Nix packages without
# fetching gaffer-private source. The pin file `nix/gaffer-pins.json` is
# updated by gaffer-private's CI after a successful push to
# cache.allegedly.works/gaffer; consumers reach the closures via Nix
# substitution against that cache (per-host reader JWTs).
#
# Empty pins (initial state, before gaffer CI's first push) → empty attrset.
# Populated pins → derivations realized via `builtins.storePath`, which the
# Nix daemon substitutes from the gaffer cache at realize time. Eval never
# touches gaffer-private's source.
_:
let
  inherit ((builtins.fromJSON (builtins.readFile ../gaffer-pins.json))) pins;
in
builtins.mapAttrs (_: spec: builtins.storePath spec.store_path) pins
