#!/usr/bin/env bash
# Build all Nix flake outputs and push closures to Attic binary cache.
set -euo pipefail

# gaffer-private is a private repo. CI doesn't need access — stub it out
# with a no-op module so Nix doesn't try to fetch it.
stub_path=$(mktemp -d)
cat >"$stub_path/flake.nix" <<'STUB'
{
  outputs = { ... }: {
    homeManagerModules.google-drive = { lib, ... }: {
      options.services.google-drive.enable = lib.mkEnableOption "stub";
    };
  };
}
STUB
git -C "$stub_path" init -q
git -C "$stub_path" add .
git -C "$stub_path" -c user.email=ci@localhost -c user.name=CI commit -qm stub

OVERRIDE="--override-input gaffer-private path:$stub_path"
out_paths=$(mktemp)

# NixOS configurations
for host in $(nix eval --json .#nixosConfigurations --apply builtins.attrNames $OVERRIDE | jq -r '.[]'); do
  nix build --impure $OVERRIDE \
    ".#nixosConfigurations.$host.config.system.build.toplevel" \
    --no-link --print-out-paths >>"$out_paths"
done

# Home configurations (google-drive disabled via extendModules +
# gaffer-private stubbed out so the private binary is never fetched)
for host in $(nix eval --impure --json .#homeConfigurations --apply builtins.attrNames $OVERRIDE | jq -r '.[]'); do
  nix build --impure $OVERRIDE --expr "
    let flake = builtins.getFlake \"path:$(pwd)\";
    in (flake.homeConfigurations.$host.extendModules {
      modules = [{ services.google-drive.enable = false; }];
    }).activationPackage
  " --no-link --print-out-paths >>"$out_paths"
done

# Other outputs
nix build --impure $OVERRIDE \
  .#packages.x86_64-linux.web-session \
  .#devShells.x86_64-linux.default.inputDerivation \
  --no-link --print-out-paths >>"$out_paths"

echo "Pushing $(wc -l <"$out_paths") paths to Attic..."
xargs attic push main <"$out_paths"
