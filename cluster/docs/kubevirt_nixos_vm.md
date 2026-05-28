# KubeVirt NixOS VM Runbook

KubeVirt and CDI are installed from `cluster/k8s/kubevirt/`. For a NixOS VM,
the repo already has the same bootstrap pattern used for Proxmox hosts such as
`wyrm2`:

```bash
nix build .#bootstrap-image
```

That package comes from `self.nixosConfigurations.bootstrap.config.system.build.images.qemu-efi`.
The full `#wyrm2` config is not a good small KubeVirt test VM because it carries
workstation, GPU, storage, and Kubernetes-worker assumptions.

## Low-Bandwidth Bootstrap Path

When on a slow uplink, avoid `virtctl image-upload` of the 5.6 GiB qcow2.
Use the experimental helper saved under:

```bash
x/kubevirt_nixos_bootstrap/
```

Apply the in-cluster image builder:

```bash
kubectl apply -f x/kubevirt_nixos_bootstrap/nixos-bootstrap-image-job.yaml
kubectl -n nixos-vm-smoke wait --for=condition=complete job/nixos-bootstrap-smoke-image --timeout=30m
```

Then create the VM and optional SSH Service:

```bash
kubectl apply -f x/kubevirt_nixos_bootstrap/nixos-bootstrap-vm.yaml
kubectl apply -f x/kubevirt_nixos_bootstrap/nixos-bootstrap-ssh-service.yaml
kubectl -n nixos-vm-smoke get vm,vmi,pod -o wide
```

The builder creates a privileged `nixos-vm-smoke` namespace, builds
`github:agentydragon/ducktape/devel#bootstrap-image` in-cluster, converts the
qcow2 to raw, and writes it to the PVC as `/disk.img`. The raw conversion is
required: KubeVirt filesystem PVC disks are attached as raw `disk.img` files.

## Verification

Guest-agent status is the cleanest boot check:

```bash
kubectl -n nixos-vm-smoke get vmi nixos-bootstrap-smoke \
  -o jsonpath='{.status.guestOSInfo}{"\n"}'
```

For SSH:

```bash
kubectl -n nixos-vm-smoke port-forward svc/nixos-bootstrap-smoke-ssh 2222:22
ssh -p 2222 agentydragon@127.0.0.1
```

The current bootstrap config only authorizes the keys listed in
`nix/nixos/hosts/bootstrap/default.nix`. This session could verify boot via the
guest agent, but SSH login was denied because the local key was not one of those
bootstrap keys.

## Caveats

The smoke VM uses `local-path-ovh`, so it is tied to one node and is not
live-migratable. It will not satisfy the original durable-VM goal by itself:
node loss can still lose availability. For durable VMs, use a CSI backend with
RWX/block support and `VolumeSnapshotClass` support before relying on
KubeVirt migration, snapshots, or node-failure recovery.

Cleanup:

```bash
kubectl delete namespace/nixos-vm-smoke --ignore-not-found=true
```
