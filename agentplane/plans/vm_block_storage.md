# Remaining VM storage work

Fresh VM workspace provisioning and basic live readiness are complete; see
[VM storage and acceptance](../docs/vm_sandboxes.md#fresh-vm-trial-readiness). The broader
[Piraeus qualification](../../cluster/docs/plans/piraeus_production.md) remains open, without
blocking the operator-authorized fresh VM trial.

## Retained legacy VM

Operator decision, 2026-10-25 PDT: preserve the existing legacy VM Sandbox selected for
retention and its state/workspace claims and PVs. Keep `spec.running: false` and
`spec.wakeOnSend: false`; never resume it against the changed template. Exclude it from both
Sandbox deletion and later retained-PV cleanup. Its identity is in the private cutover inventory.
A fresh replacement uses a different name and new claims. Retention does not convert its storage
or relax the controller's layout-compatibility checks. Do not edit its creation records or clear
its recorded volume identities.

## Deferred endpoint

Eventually both Pod and VM Sandboxes should use Piraeus-backed block storage for state and
workspace, removing the VM state virtiofs attachment. Define the Pod mount/format ownership
and supported PVC modes before selecting an implementation. Virtio remains the VM's block
device transport; the filesystem-sharing transport being retired is virtiofs. Preserve
journal and native-harness persistence, ordinary suspend/resume, UID/permission behavior,
resource accounting and explicit compatibility checks for kind changes. This broader
change is deferred and does not gate fresh VM trials.
