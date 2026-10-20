# GPU crash mitigation + diagnostics for the Lunar Lake (Arc 130V/140V) iGPU.
#
# gnome-shell aborts every few days inside Mesa iris's batch-submit error path
# (_iris_batch_flush -> abort), which on Wayland tears the whole session down to
# GDM (tmux survives — the machine never reboots). Full forensics, including the
# native backtraces shared across crashes, are in:
#   nix/debug/rugged/gnome_shell_iris_abort.md
#
# Keep Mesa from the host's Nixpkgs package set so its driver ABI matches the
# system glibc. The previous unstable-package-set override made fresh GNOME
# sessions fail while loading Iris. The remaining settings track the older
# GNOME Shell crash investigation below.
{
  pkgs,
  ...
}:
{
  # Keep the graphics drivers on the same Nixpkgs revision as the system
  # libraries they load, including glibc.
  hardware.graphics = {
    package = pkgs.mesa;
    package32 = pkgs.pkgsi686Linux.mesa;
  };

  # --- Active experiment: disable PSR2 selective fetch ------------------------
  # Half the iris aborts fire within seconds of resume-from-suspend (one is 1s
  # post-resume; ~2.6%/resume cycle), and the boot log shows
  #   xe 0000:00:02.0: [drm] Selective fetch area calculation failed in pipe A
  # so PSR2 selective fetch is the targeted suspect. This disables only selective
  # fetch — full-frame PSR still self-refreshes static content, so battery cost is
  # ~nil. Observing naturally (no repro harness); verdict via the resumes-vs-crashes
  # denominator in the note.
  # EXPERIMENT(2026-06-27): if crash-free over many resume cycles, selective fetch
  #   was the trigger — keep it, or escalate to xe.enable_psr=0 / revert if not.
  #   Tracking: nix/debug/rugged/gnome_shell_iris_abort.md
  boot.kernelParams = [ "xe.enable_psr2_sel_fetch=0" ];

  # --- Diagnostics for the next crash -----------------------------------------

  # iris logs the GPU submit failure (and errno) to stderr — which lands in the
  # journal under org.gnome.Shell@wayland.service — before it calls abort().
  # CLEANUP: remove MESA_DEBUG once the iris batch-flush abort is root-caused
  #   (nix/debug/rugged/gnome_shell_iris_abort.md). It is global session log noise.
  environment.sessionVariables.MESA_DEBUG = "1";

  # Keep gnome-shell cores long enough to inspect (default rotates aggressively).
  systemd.coredump.settings.Coredump = {
    MaxUse = "4G";
    KeepFree = "2G";
    ProcessSizeMax = "8G";
    ExternalSizeMax = "8G";
  };

  # The xe kernel driver drops a devcoredump under /sys/class/devcoredump/ on a
  # GPU fault, but it self-deletes after ~5 minutes. On appearance, copy it to
  # /var/lib/devcoredump (which also frees the kernel slot).
  services.udev.extraRules = ''
    ACTION=="add", SUBSYSTEM=="devcoredump", TAG+="systemd", ENV{SYSTEMD_WANTS}+="capture-devcoredump@$kernel.service"
  '';
  systemd.services."capture-devcoredump@" = {
    description = "Capture GPU devcoredump %i";
    path = [ pkgs.coreutils ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart =
        let
          script = pkgs.writeShellScript "capture-devcoredump" ''
            set -eu
            dev="/sys/class/devcoredump/$1"
            out="/var/lib/devcoredump"
            mkdir -p "$out"
            ts="$(date +%Y%m%d-%H%M%S)"
            [ -r "$dev/data" ] && cp "$dev/data" "$out/$ts-$1.bin" || true
            # Writing to data releases the kernel devcoredump slot.
            echo 1 > "$dev/data" 2>/dev/null || true
          '';
        in
        "${script} %i";
    };
  };
}
