# Seatbelt Policy Notes

This directory contains a base policy we can iterate on when launching sandboxed kernels.

- policies/kernel_base.sb — permissive read policy with dynamic write roots:
  - WORKSPACE — repo/workspace root; kernel may R/W under this path
  - RUN_ROOT — per-run root under /tmp; runtime logs/kernelspec/config
  - /tmp and /private/tmp — currently allowed; TODO: evaluate necessity
  - Process, signals, IPC, mach-lookup, system-socket, sysctl-read allowed (TODO tighten)
  - Networking allowed outbound/inbound local (TODO: restrict to loopback only)

## Planned tightening steps

1. Limit outbound network to loopback (127.0.0.1)
2. Remove writes to global /tmp; rely on RUN_ROOT only
3. Reduce file-read* surface to essential system libs and site-packages
4. Trim mach-lookup/system-socket allowances to required subset
5. Drop /dev/tty writes if not needed

Each step should be validated with the manual tmux recipe, then encoded into tests.
