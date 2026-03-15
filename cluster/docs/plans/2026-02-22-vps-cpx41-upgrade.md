# Upgrade VPS Nodes from cpx31 to cpx41

## Context

The cluster runs 2x Hetzner CPX31 (4 vCPU, 8GB) as control-plane nodes in Hillsboro.
Upgrading to CPX41 (8 vCPU, 16GB, 240GB) for better performance. Cost: ~$36/mo → ~$67/mo.

The hcloud Terraform provider supports in-place `server_type` changes (not ForceNew). It
powers off the server, calls Hetzner ChangeType API, and powers it back on. Disk and IPs
are preserved.

To maintain etcd quorum (2/3 CP nodes), we upgrade one node at a time by changing Terraform
config for one node, applying, verifying, then repeating for the second.

## Files to Modify

- `terraform/bootstrap/infrastructure/main.tf` (lines 31-32) — server_type values
- `terraform/bootstrap/infrastructure/hetzner-nodes.tf` (line 2) — comment

## Plan: Rolling Terraform Apply

### Step 1: Upgrade vps1 first

Edit `main.tf` to change only vps1:

```python
vps0 = { name = "talos-vps-cp-0", server_type = "cpx31" }  # unchanged
vps1 = { name = "talos-vps-cp-1", server_type = "cpx41" }  # changed
```

Then:

1. `kubectl drain talos-vps-cp-1 --ignore-daemonsets --delete-emptydir-data`
2. `tofu apply` in `terraform/bootstrap/infrastructure/` (powers off, rescales, powers on)
3. Wait for node Ready: `kubectl get node talos-vps-cp-1 --watch`
4. `kubectl uncordon talos-vps-cp-1`
5. Verify: `talosctl -n 5.78.43.147 service etcd status`

### Step 2: Upgrade vps0

Edit `main.tf` to change vps0:

```python
vps0 = { name = "talos-vps-cp-0", server_type = "cpx41" }  # changed
vps1 = { name = "talos-vps-cp-1", server_type = "cpx41" }  # already done
```

Update comment in `hetzner-nodes.tf` line 2:

```diff
-# 2x CPX31 controlplane+worker nodes in Hillsboro, OR
+# 2x CPX41 controlplane+worker nodes in Hillsboro, OR
```

Same drain → apply → wait → uncordon → verify procedure.

### Safety

- **etcd quorum**: Only 1 node down at a time → 2/3 quorum maintained.
- **Data preserved**: In-place rescale keeps local disk, IPs, volumes.
- **Terraform handles sequencing**: Provider powers off, changes type, powers on.

### Verification

After each node:

- `kubectl get nodes -o wide` — node Ready, same IP
- `talosctl -n <ip> service etcd status` — healthy
- `hcloud server describe <id>` — shows cpx41

After both:

- `kubectl get pods -A | grep -v Running | grep -v Completed` — no stuck pods
- Talos may auto-grow partition on reboot (160→240GB); if not, a reboot will trigger it
