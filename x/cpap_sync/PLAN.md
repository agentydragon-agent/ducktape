# CPAP ez Share Sync

Nightly sync of ResMed CPAP data from the ez Share WiFi SD card to the cluster.

## Status

Live. CronJob running on wyrm2, syncing to `cpap-data` PVC at 10:00 UTC daily.

## Background

- ez Share WiFi SD card in ResMed CPAP at home
- Card AP: SSID `Rai CPAP ez Share`, IP `192.168.4.1`
- Card firmware: `LZ1801EDPG:1.0.0` (old), exposes `/dir?dir=A:` + `/download?file=` API
- Data: `STR.EDF` (daily summary) + `DATALOG/<date>/*.edf` (~2.5 MB/night)
- WiFi stick: `wlx9cefd5f62ee0` (MediaTek MT7921, 2.4 GHz), passed through to wyrm2 VM
- Credentials: SOPS at `secrets/shared/cpap-ezshare.yaml`

## Architecture

- `sync.sh` — shell script: WiFi up → wpa_supplicant → DHCP → `python3 -m ezshare -w -d / -t $OUTPUT_DIR -r` → cleanup
- `Dockerfile` — `debian:bookworm-slim` + `wpasupplicant iproute2 isc-dhcp-client iw python3-pip` + `pip install ezshare`
- Image: `ghcr.io/agentydragon/cpap-sync`, built by `container-images.yml`, tagged `devel-*` for Flux
- Cluster: `cluster/k8s/cpap-sync/` — CronJob, PVC (Longhorn 50Gi), SOPS secret, namespace

## Future

- **USB stick placement (declarative)**: The WiFi stick is currently manually plugged into
  wyrm2. Ideally declared in `terraform/main/proxmox-nodes.tf` via USB passthrough device.
- Firmware update for the ez Share card (newer firmware has a cleaner API, no 8.3 short filenames)
- **Data consumption**: where does the data go after sync?
  - Leave on PVC, expose via a small HTTP server or NFS for OSCAR on desktop
  - SleepHQ upload step (future)
