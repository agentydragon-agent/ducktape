"""Watchdog: invoke FoxFlss when MM gets stuck FCC-locked on the DW5934e.

Listens to ModemManager state changes via `mmcli -m any -w`. When the modem
sits in {enabling, disabled, failed} with power-state=low for >= STUCK_THRESHOLD_S,
runs FoxFlss + restarts ModemManager. Cooldown COOLDOWN_S between fires.

Why this exists: MM only invokes fcc-unlock.d/<vid:pid> reactively on a narrow
set of QMI/MBIM error codes. The SDX72 reports the generic "Cannot power-up:
sotware radio switch is OFF" instead, which MM doesn't classify as FCC-locked,
so the wired script never fires. See debug/rugged/hw/foxflss_wwan.md.
"""

from __future__ import annotations

import logging
import selectors
import subprocess
import sys
import time

STUCK_THRESHOLD_S = 12
COOLDOWN_S = 120
RESPAWN_DELAY_S = 2
# Backstop polling interval — re-check state if mmcli -w stays silent this long.
# When the modem is wedged in disabled/low without retrying, no state-change
# events arrive, so the elapsed-time check would never run on event arrival
# alone. The DBus monitor still gives us sub-second reaction during the
# enabling↔disabled bounce loop.
TICK_S = 5
STUCK_STATES = {"enabling", "disabled", "failed"}

log = logging.getLogger("foxflss-watchdog")


def find_modem_id() -> str | None:
    out = subprocess.run(["mmcli", "-L"], check=False, capture_output=True, text=True).stdout
    for tok in out.split():
        if tok.startswith("/org/freedesktop/ModemManager1/Modem/"):
            return tok.rsplit("/", 1)[-1]
    return None


def query_state(mid: str) -> tuple[str | None, str | None]:
    out = subprocess.run(["mmcli", "-m", mid, "-K"], check=False, capture_output=True, text=True).stdout
    state = power = None
    for raw in out.splitlines():
        key, _, val = raw.partition(":")
        match key.strip():
            case "modem.generic.state":
                state = val.strip()
            case "modem.generic.power-state":
                power = val.strip()
    return state, power


def fire_unlock() -> None:
    log.warning("invoking FoxFlss")
    rc = subprocess.run(["FoxFlss"], check=False).returncode
    log.warning("FoxFlss exit=%d", rc)
    time.sleep(3)
    log.warning("restarting ModemManager")
    subprocess.run(["systemctl", "restart", "ModemManager"], check=False)


def watch() -> None:
    stuck_since: float | None = None
    last_fire = 0.0
    sel = selectors.DefaultSelector()

    while True:
        proc = subprocess.Popen(
            ["mmcli", "-m", "any", "-w"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        assert proc.stdout is not None
        sel.register(proc.stdout, selectors.EVENT_READ)
        mmcli_alive = True
        try:
            while mmcli_alive:
                # Block until either an mmcli -w event arrives OR TICK_S elapses.
                # Both paths fall through to the state re-check below.
                if sel.select(timeout=TICK_S) and not proc.stdout.readline():
                    mmcli_alive = False
                mid = find_modem_id()
                state, power = query_state(mid) if mid else (None, None)
                stuck = state in STUCK_STATES and power == "low"
                now = time.time()
                if not stuck:
                    stuck_since = None
                    continue
                if stuck_since is None:
                    stuck_since = now
                    log.info("stuck: state=%s power=%s", state, power)
                elapsed = now - stuck_since
                if elapsed >= STUCK_THRESHOLD_S and now - last_fire >= COOLDOWN_S:
                    log.warning(
                        "stuck modem=%s state=%s power=%s for %.0fs; FoxFlss + restart MM", mid, state, power, elapsed
                    )
                    fire_unlock()
                    last_fire = time.time()
                    stuck_since = None
        finally:
            sel.unregister(proc.stdout)
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        log.info("mmcli -w exited; respawn in %ds", RESPAWN_DELAY_S)
        time.sleep(RESPAWN_DELAY_S)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    watch()


if __name__ == "__main__":
    main()
