"""Sync CPAP data from ez Share WiFi SD card to local directory."""

import logging
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from ezshare import ezshare

logger = logging.getLogger(__name__)

EZSHARE_BASE = "http://ezshare.card/dir?dir=A:"
EZSHARE_IP = "192.168.4.1"
CONNECT_TIMEOUT_S = 30


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    logger.debug("running: %s", args)
    return subprocess.run(args, check=True, **kwargs)


def _bring_up(iface: str) -> None:
    _run(["ip", "link", "set", iface, "up"])


def _bring_down(iface: str) -> None:
    subprocess.run(["ip", "link", "set", iface, "down"], check=False)


def _connect(iface: str, ssid: str, password: str, wpa_pid_file: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False, prefix="ezshare-wpa-") as wpa_conf:
        wpa_conf.write(f'network={{\n    ssid="{ssid}"\n    psk="{password}"\n    key_mgmt=WPA-PSK\n}}\n')
        conf_path = wpa_conf.name

    _run(["wpa_supplicant", "-B", "-i", iface, "-c", conf_path, "-P", wpa_pid_file])
    Path(conf_path).unlink(missing_ok=True)

    # Wait for association
    deadline = time.monotonic() + CONNECT_TIMEOUT_S
    while time.monotonic() < deadline:
        result = subprocess.run(["iw", "dev", iface, "link"], capture_output=True, text=True, check=False)
        if "Connected to" in result.stdout:
            logger.info("associated with AP")
            break
        time.sleep(1)
    else:
        raise TimeoutError(f"failed to associate with {ssid!r} within {CONNECT_TIMEOUT_S}s")


def _get_dhcp(iface: str) -> None:
    # -1: exit after obtaining lease (don't daemonize)
    _run(["dhclient", "-1", "-d", "--no-pid", iface])
    # Remove any default route dhclient may have installed via this interface.
    subprocess.run(["ip", "route", "del", "default", "dev", iface], check=False)
    logger.info("DHCP lease obtained on %s", iface)


def _release_dhcp(iface: str) -> None:
    subprocess.run(["dhclient", "-r", iface], check=False)


def _kill_wpa(wpa_pid_file: str) -> None:
    try:
        pid = int(Path(wpa_pid_file).read_text().strip())
        os.kill(pid, signal.SIGTERM)
        logger.info("wpa_supplicant (pid %d) terminated", pid)
    except (FileNotFoundError, ValueError, ProcessLookupError) as e:
        logger.warning("could not terminate wpa_supplicant: %s", e)


def sync(iface: str, ssid: str, password: str, output_dir: Path) -> None:
    wpa_pid_file = f"/tmp/ezshare-wpa-{iface}.pid"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("bringing up %s", iface)
    _bring_up(iface)

    try:
        logger.info("connecting to %r", ssid)
        _connect(iface, ssid, password, wpa_pid_file)

        logger.info("getting DHCP lease")
        _get_dhcp(iface)

        logger.info("syncing from card to %s", output_dir)
        card = ezshare(EZSHARE_BASE, num_retries=5)
        if not card.ping():
            raise RuntimeError(f"card at {EZSHARE_IP} is not responding")
        card.sync("/", local_dir=str(output_dir), recursive=True)
        logger.info("sync complete")

    finally:
        logger.info("cleaning up")
        _release_dhcp(iface)
        _kill_wpa(wpa_pid_file)
        _bring_down(iface)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    iface = os.environ.get("WIFI_IFACE", "wlx9cefd5f62ee0")
    ssid = os.environ.get("WIFI_SSID", "Rai CPAP ez Share")
    password = os.environ["WIFI_PASSWORD"]
    output_dir = Path(os.environ.get("OUTPUT_DIR", "/data/cpap"))

    sync(iface=iface, ssid=ssid, password=password, output_dir=output_dir)


if __name__ == "__main__":
    main()
