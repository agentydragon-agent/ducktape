# CPAP ez Share Sync

Nightly sync of ResMed CPAP data from the ez Share WiFi SD card to the cluster.

## Status

Implementation done. Flux applied (as of `d84b32f0`): namespace, CronJob, secret all
live. PVC pending (WaitForFirstConsumer — binds on first pod run). CI building image.
Pending: wyrm2 restart to activate USB hotplug + pick up WiFi stick.

## Next Steps (after wyrm2 restart)

1. **Verify stick visible in wyrm2**: `lsusb | grep 0e8d` and `ip link show | grep wlx`
2. **Wait for CI image**: `gh run watch` — once push-images completes, Flux ImagePolicy
   picks up `ghcr.io/agentydragon/cpap-sync:devel-*` and updates the CronJob
3. **Trigger a manual test run**:
   ```
   kubectl create job -n cpap-sync --from=cronjob/cpap-sync cpap-sync-test
   kubectl logs -n cpap-sync -f job/cpap-sync-test
   ```
4. **Check data landed on PVC**: exec into a debug pod, verify EDF files under
   `/data/cpap/DATALOG/`
5. **Verify no routing damage**: check wyrm2's default route is intact after job
   completes (`ip route show` on wyrm2)

## Background

- ez Share WiFi SD card in ResMed CPAP at home
- Card AP: SSID `Rai CPAP ez Share`, IP `192.168.4.1`
- Card firmware: `LZ1801EDPG:1.0.0` (old), exposes `/dir?dir=A:` + `/download?file=` API
- Data: `STR.EDF` (daily summary) + `DATALOG/<date>/*.edf` (~2.5 MB/night)
- WiFi stick: `wlx9cefd5f62ee0` (Hengbao, 2.4 GHz only), will be on wyrm2
- Credentials: SOPS at `secrets/shared/cpap-ezshare.yaml`

## Plan

### 1. `x/cpap_sync/` — application code

**`sync.py`** — main entrypoint:

1. Bring up `$WIFI_IFACE` (env var, default `wlx9cefd5f62ee0`)
2. Start `wpa_supplicant` against the ez Share AP using `$WIFI_PASSWORD`
3. Run `dhclient $WIFI_IFACE` — with `DEFROUTE=no` / explicit metric so it doesn't
   clobber wyrm2's default route
4. `ezshare("http://ezshare.card/dir?dir=A:").sync("/", local_dir=$OUTPUT_DIR, recursive=True)`
5. Teardown: kill wpa_supplicant, release DHCP, bring interface down

Runs as root (needs `NET_ADMIN` for interface management).

**`bookworm_cpap_sync.yaml`** — apt manifest:

```yaml
packages:
  - wpasupplicant
  - iproute2
  - isc-dhcp-client
```

**`BUILD.bazel`**:

- `py_library` + `aspect py_binary` for the sync script
- `py_image_layer` for the Python layer
- `oci_image` stacking:
  - base: `@python_3_13_slim_linux_amd64`
  - tars: `@bookworm_cpap_sync//:flat` + `:layers`
  - entrypoint: `py_image_entrypoint`

### 2. `MODULE.bazel` additions

```python
apt.install(
    name = "bookworm_cpap_sync",
    lock = "//x/cpap_sync:bookworm_cpap_sync.lock.json",
    manifest = "//x/cpap_sync:bookworm_cpap_sync.yaml",
)
use_repo(apt, ..., "bookworm_cpap_sync")
```

Generate lockfile: `bazel run @bookworm_cpap_sync//:lock`

### 3. `push-images.yml` — new matrix row

```yaml
- image: "//x/cpap_sync:image"
  image_name: "cpap-sync"
  test_target: "//x/cpap_sync/..."
```

### 4. `cluster/k8s/cpap-sync/` — cluster manifests

**`flux-kustomization.yaml`** — Flux `Kustomization` wired from root `kustomization.yaml`

**`kustomization.yaml`** — lists `cronjob.yaml`, `pvc.yaml`, `secret.yaml`

**`cronjob.yaml`**:

```yaml
schedule: "0 10 * * *" # 10:00 UTC = morning after night's sleep
nodeSelector:
  kubernetes.io/hostname: wyrm2
hostNetwork: true
securityContext:
  capabilities:
    add: [NET_ADMIN]
env:
  - name: WIFI_PASSWORD
    valueFrom:
      secretKeyRef: { name: cpap-ezshare, key: wifi_password }
  - name: OUTPUT_DIR
    value: /data/cpap
volumeMounts:
  - name: data
    mountPath: /data/cpap
volumes:
  - name: data
    persistentVolumeClaim:
      claimName: cpap-data
```

**`pvc.yaml`**: Longhorn-backed, `ReadWriteOnce`, ~50Gi (years of data at ~2.5 MB/night)

**`secret.yaml`** (SOPS): decrypt `secrets/shared/cpap-ezshare.yaml` into k8s Secret
`cpap-ezshare` in the cpap-sync namespace.

### 5. `pyproject.toml` — add `ezshare` dep

```toml
"ezshare>=0.0.11",
```

Then regenerate `requirements_bazel.txt` via RBE.

## Future

- **USB stick placement (declarative)**: The WiFi stick is currently manually plugged into
  wyrm2. Ideally this is declared in Proxmox/Terraform — either as a USB passthrough device
  on the wyrm2 VM definition in `terraform/main/proxmox-nodes.tf`, or via a Proxmox USB
  device mapping. Investigate `proxmox_virtual_environment_vm` USB device block in
  `terraform-provider-bpg/proxmox`.
- Firmware update for the ez Share card (newer firmware has a cleaner API, no 8.3 short
  filenames)
- Consolidate `bookworm_cpap_sync.yaml` to trixie once other bookworm apt manifests are
  upgraded
- Pin all trixie apt manifests to the same snapshot URL; enforce this in CI

## Open Questions

- **Namespace**: `cpap-sync` (new) or reuse an existing one?
- **Data consumption**: where does the data go after sync? Options:
  - Leave on PVC, expose via a small HTTP server or NFS for OSCAR on desktop
  - SleepHQ upload step (future)
  - Custom EDF processing pipeline (future)
- **Signal reliability**: card was at -87 dBm from atlas. How far is the CPAP from
  wyrm2? May need a retry loop or a "card not found" graceful exit.
- **DHCP routing**: need to verify `dhclient` doesn't set ez Share as default route.
  Can use `dhclient-script` hook or `ip route del default dev $WIFI_IFACE` after lease.
