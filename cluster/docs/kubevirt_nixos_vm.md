# KubeVirt NixOS VM Runbook

KubeVirt and CDI are installed from <k8s/kubevirt/>. The paved end-to-end flow
for a new NixOS VM is:

1. Publish the bootstrap qcow2 to SeaweedFS — `cluster/k8s/vm-images-publisher/`.
2. Define the VM under `cluster/k8s/<name>/` with a CDI `DataVolume` sourcing
   that qcow2 — see <k8s/gecko/> as the canonical example.
3. Boot, SSH in with a key in `nix/nixos/hosts/bootstrap/default.nix`, then
   `nixos-rebuild switch --flake github:agentydragon/ducktape?ref=devel#<name>`
   to take on a real host config.

## Publishing The Bootstrap Image

Trigger an in-cluster build + upload from the suspended CronJob:

```bash
kubectl create job --from=cronjob/vm-images-publisher \
  "publish-$(date +%s)" -n vm-images-publisher
```

See <k8s/vm-images-publisher/README.md> for environment overrides (publish a
non-default ref, alternate flake output, etc.). The resulting object key is
`bootstrap/<commit-sha>.qcow2`.

## Wiring A VM

Crib from <k8s/gecko/>:

- `namespace/` — dedicated namespace.
- `app/vm-images-s3-reader.yaml` — `ExternalSecret` pulling `cdiReader*` keys
  from `seaweedfs/vm-images-s3-credentials` via cross-namespace `SecretStore`.
- `app/datavolume.yaml` — points at the published qcow2 via the public
  `vm-images-s3.allegedly.works` endpoint (reads work over that path; only
  writes were ever slow).
- `app/virtualmachine.yaml` — `VirtualMachine` with UEFI (`secureBoot: false`),
  virtio rootdisk + NIC, `runStrategy: Always`.
- `app/service.yaml` — ClusterIP exposing SSH at :22.

Both `namespace` and `app` are wired as separate Flux Kustomizations with
`wait: true` health checks on the DataVolume + VirtualMachine, so the chain
won't report Ready until CDI finishes the import and the VM is up.

## Verification

```bash
# Guest agent boot check (also exposes IP, hostname, kernel)
kubectl -n <ns> get vmi <name> -o jsonpath='{.status.guestOSInfo}{"\n"}'

# SSH via port-forward (use before public exposure is wired)
kubectl -n <ns> port-forward svc/<name>-ssh 2222:22
ssh -p 2222 agentydragon@127.0.0.1
```

The bootstrap NixOS config (`nix/nixos/hosts/bootstrap/default.nix`) authorises
SSH keys for `wyrm2`, `atlas`, `rugged`. To SSH from a workstation whose key
isn't in that list, add the public key to that file and re-publish the image.

## Exposing SSH Publicly

Gecko's SSH is reachable from anywhere at `gecko.allegedly.works:22` via a
Cilium Gateway API `TCPRoute`. The path is:

- A new `ssh-gecko` TCP listener on `cluster-gateway` (port 22) — see
  <k8s/gateway/gateway.yaml>. The hil hostNetwork Envoy DaemonSet keeps the
  `NET_BIND_SERVICE` cap, so binding :22 directly on the host works.
- A `TCPRoute` in the VM's namespace whose `parentRefs.sectionName` matches
  that listener — see <k8s/gecko/app/tcproute.yaml>.
- Wildcard `*.allegedly.works` already points at the hil gateway IPs, so no
  extra Route 53 record is needed.

To expose a second VM, add another listener on a different port (e.g.
`ssh-frog` on 2222), then a TCPRoute referencing that `sectionName`. SSH has
no SNI, so one listener-per-backend.

Security model: SSH key-only auth on the VM (NixOS base config disables
`PasswordAuthentication`). Bruteforce attempts against the public :22 are
expected noise against a key-only sshd.

## Caveats

VMs that use `local-path-ovh` (or any local-path class) are tied to one node
and are not live-migratable; node loss = availability loss. For durable VMs,
use a CSI backend with RWX/block support and `VolumeSnapshotClass` before
relying on KubeVirt migration, snapshots, or node-failure recovery.
