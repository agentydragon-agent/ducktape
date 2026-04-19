# Dell Rugged 12 — 5G Modem / eSIM

## Hardware

- **Modem**: Foxconn DP25-42843-47
- **Capabilities**: GSM-UMTS, LTE, 5G NR
- **Interface**: MBIM (`/dev/wwan0mbim0`)
- **EID**: `89033023427100000000053696008750`

## NixOS Configuration

In `nix/nixos/hosts/rugged/default.nix`:

```nix
networking.modemmanager.enable = true;
programs.nm-applet.enable = true;
```

## eSIM Profiles

| ICCID                | Provider    | Status   |
| -------------------- | ----------- | -------- |
| 89000123456789012341 | GSMA (test) | disabled |
| 8901240270175304567  | Google Fi   | enabled  |

To activate a profile from a QR code (`LPA:1$<server>$<code>`):

```bash
sudo mmcli -m 0 -e --esim-activation-code='LPA:1$<server>$<code>'
```

## FCC Lock — SOLVED (2026-04-18)

The Foxconn DW5934e has an FCC lock that prevents software radio activation.
Without unlocking, ModemManager reports `power state: low` and the software radio
stays OFF.

### Root cause

The modem requires an FCC unlock handshake before the software radio can be turned on.
This must happen **every time the modem powers on** (boot, PCI rescan, resume).

### What works: FoxFlss binary

The closed-source `FoxFlss` binary from
[foxconn-pc/fii_linux](https://github.com/foxconn-pc/fii_linux) (v1.0.15) performs the
FCC unlock. It communicates via the MBIM proxy (needs ModemManager running) and reads
the system SKU via `dmidecode` to verify platform support (SKU `0D67` is supported).

**Dependencies**: only glibc + `dmidecode` on PATH.

**Sequencing** (order matters):

1. ModemManager must be running and have probed the modem (can take 20-60s after boot/PCI rescan)
2. Run `FoxFlss` (needs MBIM proxy from MM, needs `dmidecode` on PATH)
3. Restart ModemManager to pick up the new radio state (modem appears with `power state: on`)
4. Wait for MM to re-probe the modem (~20-60s)
5. Enable the modem: `mmcli -m 0 --enable`
6. Connect: `mmcli -m 0 --simple-connect="apn=h2g2,ip-type=ipv4v6"`

After step 5, the modem registers on Google Fi (5G NR, 92% signal observed).

### What doesn't work

- **libqmi DMS commands** (`--dms-foxconn-set-fcc-authentication`): SDX72 rejects all
  DMS Foxconn extensions with `WmsInvalidMessageId`. The DMS path is SDX55-only.
- **libqmi FOX service** (`--fox-set-fcc-authentication`): Needs libqmi >= 1.38.0.
  nixpkgs has 1.36.0 (only `--fox-noop` and `--fox-get-firmware-version`).
- `mbimcli --set-radio-state=on` — doesn't persist
- `rfkill unblock wwan` — WWAN not listed in rfkill
- `mmcli -m 0 --reset` — radio stays off
- ~~`fwupd`~~: Firmware already at latest (checked March 2026)

### Remaining work

- **Declarative NixOS setup** — make the FCC unlock automatic on boot. Plan:
  1. **Package FoxFlss** as a Nix derivation (it's a single ELF binary with only
     glibc dependency). Fetch from the fii_linux GitHub repo, `patchelf` the
     interpreter, install binary + RF data files.

  2. **Write an FCC unlock wrapper script** that MM calls via `fcc-unlock.d`.
     Based on the `DW593Xe` script from fii_linux — it finds the MBIM port,
     calls `FoxFlss`, and exits. Must have `dmidecode` and `FoxFlss` on PATH.

  3. **Wire via `networking.modemmanager.fccUnlockScripts`**:

     ```nix
     networking.modemmanager.fccUnlockScripts = [{
       id = "105b:e11d";
       path = "${foxflss-fcc-unlock-script}";
     }];
     ```

     This creates a symlink in `/etc/ModemManager/fcc-unlock.d/105b:e11d` so MM
     runs the script automatically when the modem is detected.

  4. **Add `dmidecode`** to system packages (FoxFlss shells out to it).

  The MM `fcc-unlock.d` mechanism runs the script automatically during modem
  probing, so no manual `FoxFlss` + MM restart cycle is needed — MM handles it.

- **NM connection**: After FCC unlock + MM restart + `mmcli --enable` +
  `mmcli --simple-connect`, GNOME Settings can manage the cellular connection
  and configures IP automatically (IPv4 + IPv6). The `nmcli` CLI showed
  `wwan0mbim0` as `gsm / unavailable` during testing, but GNOME GUI was able
  to activate the connection. Some apps (pip) had IPv4 connectivity issues —
  may need DNS or routing investigation when WiFi is off.
- **libqmi 1.38.0 overlay**: Once nixpkgs updates (or via overlay), the FCC unlock
  could be done via `qmicli --fox-set-fcc-authentication` instead of the closed-source
  binary. The FOX service (0xE3) works on this modem (confirmed: `--fox-get-firmware-version`
  returns `FDE2.F0.0.0.1.2.TO.003.062`).
- **Suspend**: `mhi_pci_suspend` returns EBUSY (-16). FoxFlss v1.0.9+ has
  `--test-quick-suspend-resume` for MM, and the fii_linux repo includes
  `mm-suspend-resume-options.conf`. Needs investigation.

### Google Fi APN

- APN: `h2g2`
- No username/password
- Authentication: None

## eSIM Slot Setup

The modem has two slots:

- Slot 0: Physical SIM (empty)
- Slot 1: Embedded eSIM

To switch to eSIM slot before using `lpac`:

```bash
# Stop ModemManager to release device
sudo systemctl stop ModemManager

# Switch to eSIM slot (slot 1, 0-based)
sudo nix-shell -p libmbim --run "mbimcli -d /dev/wwan0mbim0 --ms-set-device-slot-mappings=1"
```

## lpac Commands

```bash
# Environment (required for this modem)
export LPAC_APDU=mbim
export LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0
export LPAC_APDU_MBIM_UIM_SLOT=2      # 1-based: 2 = slot index 1 (eSIM)
export LPAC_APDU_MBIM_USE_PROXY=1     # required for this modem

# Chip info
sudo nix-shell -p lpac --run 'LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 LPAC_APDU_MBIM_USE_PROXY=1 lpac chip info'

# List profiles
sudo nix-shell -p lpac --run 'LPAC_APDU=mbim LPAC_APDU_MBIM_DEVICE=/dev/wwan0mbim0 LPAC_APDU_MBIM_UIM_SLOT=2 LPAC_APDU_MBIM_USE_PROXY=1 lpac profile list'

# Download profile (from QR code: LPA:1$server$code)
sudo nix-shell -p lpac --run 'LPAC_APDU=mbim ... lpac profile download -s <server> -m <matching-id>'

# Enable profile
sudo nix-shell -p lpac --run 'LPAC_APDU=mbim ... lpac profile enable <iccid>'
```

Decode a QR code to get the activation string:

```bash
nix-shell -p zbar --run "zbarimg --raw /path/to/qrcode.png"
```

## Useful Diagnostics

```bash
# ModemManager
mmcli -L
mmcli -m 0

# MBIM
sudo nix-shell -p libmbim --run "mbimcli -d /dev/wwan0mbim0 --query-device-caps"
sudo nix-shell -p libmbim --run "mbimcli -d /dev/wwan0mbim0 --query-radio-state"
sudo nix-shell -p libmbim --run "mbimcli -d /dev/wwan0mbim0 --ms-query-device-slot-mappings"
sudo nix-shell -p libmbim --run "mbimcli -d /dev/wwan0mbim0 --ms-query-slot-info-status=1"

# NetworkManager
nmcli device status
nmcli connection show

# Firmware update
fwupdmgr get-devices   # check modem shows up
fwupdmgr update        # update modem firmware if available
```

## References

- [lpac GitHub](https://github.com/estkme-group/lpac)
- [lpac MBIM driver source](https://github.com/estkme-group/lpac/blob/main/driver/apdu/mbim.c)
