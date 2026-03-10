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

## Outstanding Issue: Software Radio Stuck OFF

ModemManager reports `failed reason: esim-without-profiles` because the software radio
is stuck OFF even though a Google Fi profile is installed and enabled:

```
Hardware radio state: 'on'
Software radio state: 'off'
```

Attempted (Jan 2026, did not help):

- `mbimcli --set-radio-state=on` — doesn't persist
- `rfkill unblock wwan` — WWAN not listed in rfkill
- `mmcli -m 0 --reset` — radio stays off

### Things to investigate

- **BIOS setting**: Dell BIOS may have WWAN disabled. Check under Wireless settings.
- **Hardware switch**: Physical wireless kill switch on tablet body.
- **`fwupd`**: Run `fwupdmgr update` — modem firmware may need update.
  Worth trying now (March 2026) since rugged is fully set up.
- **`cctk`** (Dell Command Configure): May need to enable WWAN via `cctk --WirelessLan=Enable` or similar.

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
