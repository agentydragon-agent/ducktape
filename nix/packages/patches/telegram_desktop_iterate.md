# Iterating on the telegram-desktop patch

Workflow for editing <telegram-desktop-poll-timer-debug.patch> (or any other
local tdesktop patch) without paying for a full nix-side rebuild every time.

The override at <../telegram-desktop.nix> is what we ship via home-manager.
This doc is for the inner loop — patch tweaks, log line shape, testing the
binary against a live account — where round-tripping through `nix build`
of `telegram-desktop-unwrapped` is too slow.

## One-time setup

1. Shallow-clone tdesktop into the standard `/code` layout, at the same
   tag the local nixpkgs has pinned (currently `v6.6.2`):

   ```bash
   GIT_SSH_COMMAND='ssh -F /dev/null -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519' \
   git clone --depth 1 --branch v6.6.2 \
     --recurse-submodules --shallow-submodules --jobs 8 \
     https://github.com/telegramdesktop/tdesktop.git \
     /code/github.com/telegramdesktop/tdesktop
   ```

   The `GIT_SSH_COMMAND` override exists because home-manager symlinks
   `~/.ssh/config` into the nix store with 0777 perms; openssh refuses
   to read it, and a global `url.<ssh>.insteadOf=<https>` rewrite forces
   SSH. The override gives ssh an empty config (`-F /dev/null`) so it
   skips the symlink entirely.

2. Apply the patch in-tree:

   ```bash
   cd /code/github.com/telegramdesktop/tdesktop
   patch -p1 -N < /home/agentydragon/code/ducktape/nix/packages/patches/telegram-desktop-poll-timer-debug.patch
   ```

   `-N` makes re-application a no-op (silently skipped) so this step is
   idempotent across iterations. To revert before re-patching after
   editing the source:

   ```bash
   patch -p1 -R < /home/agentydragon/code/ducktape/nix/packages/patches/telegram-desktop-poll-timer-debug.patch
   ```

## Build environment

`mkShell` with the inputs of `pkgs.telegram-desktop.unwrapped`. This pulls
qtbase, qtsvg, qtwayland, ffmpeg, openalSoft, hunspell, kcoreaddons,
range-v3, tl-expected, microsoft-gsl, libheif, libavif, libjxl, lz4,
minizip-ng, rnnoise, ada, boost, protobuf, **tg_owt**, **tde2e** —
substituted from cache.nixos.org for stable nixpkgs. `mkShell` itself
never builds tdesktop.

```bash
nix-shell --pure --extra-experimental-features 'nix-command flakes' -E '
  let
    flake = builtins.getFlake "git+file:///home/agentydragon/code/ducktape";
    pkgs = flake.nixosConfigurations.wyrm2.pkgs;
    drv = pkgs.telegram-desktop.unwrapped;
  in pkgs.mkShell {
    inherit (drv) nativeBuildInputs buildInputs cmakeFlags;
  }'
```

Drop `--pure` if you want your usual `$PATH`/aliases.

Preview what nix would substitute vs. build:

```bash
nix --extra-experimental-features 'nix-command flakes' build --no-link --dry-run --impure --expr '
  let f = builtins.getFlake "git+file:///home/agentydragon/code/ducktape";
      pkgs = f.nixosConfigurations.wyrm2.pkgs;
      drv = pkgs.telegram-desktop.unwrapped;
  in (pkgs.mkShell { inherit (drv) nativeBuildInputs buildInputs; }).inputDerivation'
```

If `tg_owt` / `tde2e` show as `will be built`, expect 15–45 min of
one-time C++ before the shell drops. Otherwise it's a download.

## Configure + build (inside the shell)

```bash
cd /code/github.com/telegramdesktop/tdesktop
mkdir -p build && cd build
cmake -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo $cmakeFlags ..
ninja Telegram
```

`$cmakeFlags` carries `TDESKTOP_API_ID` / `TDESKTOP_API_HASH` from
nixpkgs (snap-store credentials; fine for personal builds). Cold
`ninja Telegram` is roughly 30–90 minutes on wyrm2; incremental
re-runs after a single-file patch edit are seconds.

## Run

Inside the same shell so the build inputs stay on `LD_LIBRARY_PATH`
and `QT_PLUGIN_PATH`:

```bash
./Telegram/Telegram -workdir /tmp/td-test
```

`-workdir` keeps the run isolated from `~/.local/share/TelegramDesktop`
so we don't pollute the real client state during iteration. Log in via
QR scan from the phone, let it sync, then:

```bash
grep "Poll Debug" /tmp/td-test/log.txt
```

That's the marker emitted by the patch when clamping kicks in. The line
includes `pollId`, `closeDate`, `deltaSec`, `deltaDays`, and the first
120 chars of the question — enough to identify which chat the bad poll
lives in.

To run from outside the dev shell later (e.g., quick re-test after
restart) without re-entering nix-shell:

```bash
patchelf --set-rpath "$LD_LIBRARY_PATH" build/Telegram/Telegram
```

…done from inside the shell. After that the binary carries its own
rpath and can be invoked from any shell.

## When to promote back into the nix override

Once a patch shape is settled here, the only change needed in
<../telegram-desktop.nix> / <telegram-desktop-poll-timer-debug.patch>
is the patch file content itself — the override is already wired to
include it. Run `home-manager switch --flake .#wyrm2` to deploy the
new patched build system-wide.
