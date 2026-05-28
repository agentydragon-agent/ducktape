# KubeVirt NixOS Bootstrap VM

Experimental manifests for creating a KubeVirt VM root disk from this repo's
NixOS `bootstrap-image` package.

This is intentionally kept under `x/` and is not referenced by Flux. It is a
one-off bootstrap helper for testing or for creating a small NixOS VM that can
later be switched to a real host config, similar to the Proxmox `wyrm2` flow.

The bootstrap image is defined in `flake.nix`:

```bash
nix build .#bootstrap-image
```

The saved Kubernetes Job builds the same package inside the cluster, converts
the resulting qcow2 to raw, and writes it to a PVC as `/disk.img`, which
KubeVirt can then boot from. This avoids uploading a multi-GiB qcow2 from a
local machine. The manifest only trusts `cache.nixos.org`; add private Attic
cache credentials separately if the build should use `cache.allegedly.works`.

Apply the builder:

```bash
kubectl apply -f x/kubevirt_nixos_bootstrap/nixos-bootstrap-image-job.yaml
kubectl -n nixos-vm-smoke logs -f job/nixos-bootstrap-smoke-image
```

The manifest uses `hostNetwork: true` because the initial smoke-test pod could
not resolve normal pod DNS or reach the injected proxy service from
`claude-sandbox`. It also runs the builder privileged and mounts `/dev/kvm`
because the repo's `qemu-efi` image builder requires Nix's `kvm` system feature.
It creates a dedicated `nixos-vm-smoke` namespace labeled for privileged
PodSecurity admission. Revisit this before promoting it outside `x/`.

After the Job succeeds, create the KubeVirt VM:

```bash
kubectl apply -f x/kubevirt_nixos_bootstrap/nixos-bootstrap-vm.yaml
kubectl -n nixos-vm-smoke get vm,vmi,pod -o wide
```

The VM mounts the `nixos-bootstrap-smoke-root` PVC. For filesystem PVCs,
KubeVirt expects the bootable raw image at `/disk.img`; that is where the
builder writes the converted image. The VM uses UEFI firmware with Secure Boot
disabled because the repo image is built with `qemu-efi`.

Expose SSH for provisioning:

```bash
kubectl apply -f x/kubevirt_nixos_bootstrap/nixos-bootstrap-ssh-service.yaml
kubectl -n nixos-vm-smoke port-forward svc/nixos-bootstrap-smoke-ssh 2222:22
ssh -p 2222 agentydragon@127.0.0.1
```

The bootstrap host config only authorizes the SSH keys in
`nix/nixos/hosts/bootstrap/default.nix`. Add the current workstation key there
before rebuilding if SSH should work from that machine.

After first boot, switch to a real host config over SSH:

```bash
nixos-rebuild switch --flake github:agentydragon/ducktape?ref=devel#<host>
```

Do not use `#wyrm2` as the default for a small KubeVirt VM. `wyrm2` carries
workstation, GPU, storage, and Kubernetes-worker assumptions. Start with
`#bootstrap`, then add a dedicated host config for a KubeVirt VM if this becomes
durable.

Cleanup:

```bash
kubectl delete namespace/nixos-vm-smoke --ignore-not-found=true
```
