# Replicated VM workspace storage

Operator-selected, 2026-10-25 PDT. Provision fresh VM workspaces as raw block volumes and
put both VM workspace and state claims on replicated Piraeus storage. The operator accepts
deleting selected pre-existing Sandboxes for this cutover instead of implementing a converter.
An operator-retained legacy VM may instead remain permanently suspended, with its volumes intact.

## Provisioning contract

| Volume    | Layout                  | PVC mode     | Guest attachment                                  |
| --------- | ----------------------- | ------------ | ------------------------------------------------- |
| Workspace | `BlockFilesystem`, ext4 | `Block`      | Virtio disk at `/dev/disk/by-id/virtio-workspace` |
| State     | `DirectoryTree`         | `Filesystem` | Virtiofs at `/state`                              |

Staging selects `piraeus-ssd-2-autodiskful` for both VM claims. The class maintains two
synchronous copies within `hil-ovh`, permits remote attachment within that zone, and can
establish a local copy after a move. Moving only the workspace would leave the state claim
pinning the VM. Pod templates retain their current storage in this change.

Node movement means stopping the VM, detaching its volumes, and starting it on another
eligible node. It does not enable KubeVirt live migration, concurrent ext4 writers, or
cross-site replication. The [Piraeus production plan](../../cluster/docs/plans/piraeus_production.md)
owns replication, quorum, node-loss, resync and expansion qualification; a VM test using a
local block device establishes the attachment contract, not those storage-service properties.

## Cutover

Operator scope update, 2026-10-25 PDT: a fresh VM trial may proceed after basic live checks of
deployed configuration, storage health/headroom, and disposable VM boot with state/workspace
write/read. Skip node-loss, quorum/fencing, expansion, cross-node movement and recovery drills
for this trial. The broader Piraeus qualification remains outstanding; this exception does
not declare its recovery or movement properties qualified.

The implementation changes the existing `runner-vm` template in place. Existing workspace
claims record `RawDiskImage` on `Filesystem` storage; the controller must continue rejecting
their use with a `BlockFilesystem` template. Do not edit their creation records, clear their
recorded identities, or assume a StorageClass edit converts data.

1. Raw-block VM boot, write/read, suspend/resume and retained-identity acceptance passed on RBE.
   Complete the basic live checks above before the next fresh VM trial. Full replicated-class
   qualification stays in the Piraeus plan and does not gate this operator-authorized trial.
2. Inventory the affected VM Sandboxes and their claim/PV identities. Save desired Sandbox
   manifests, policy selections and bootstrap configuration needed to recreate them. The
   reset applies only to selected VM Sandboxes affected by this template change; Pod Sandboxes,
   backend service databases and explicitly retained legacy VMs are outside its scope.
3. Disable wake-on-send and suspend each selected Sandbox. Wait for its runner to quiesce and
   for its VMI and launcher to disappear before deleting the Sandbox through the ordinary
   controller lifecycle. Let the controller and Kubernetes remove its owned claims; wait
   for deletion to finish before recreating the same name.
4. Activate the new template and recreate the selected Sandboxes. Check new Sandbox/PVC UIDs,
   the replicated StorageClass on both claims, `Block` workspace mode, `Filesystem` state
   mode, the guest ext4 mount, and runner connectivity. Write and read markers in state and
   workspace. Suspend/resume and retained identities have RBE coverage; a live cross-node move
   is deferred to the broader storage qualification and does not gate this trial.

Operator decision, 2026-10-25 PDT: preserve the existing legacy VM Sandbox selected for
retention and its state/workspace claims and PVs. Keep `spec.running: false` and
`spec.wakeOnSend: false`; never resume it against the changed template. Exclude it from both
Sandbox deletion and later retained-PV cleanup. Record its identity in the private cutover
inventory. A fresh replacement uses a different name and new claims. Retention does not
convert its storage or relax the controller's layout-compatibility checks.

The accepted reset loses the removed Sandboxes' runner/native Session persistence and their
workspace files, including repositories and harness homes. Recreated Sandboxes have new
identities; continuation of their old Sessions is not promised. This acceptance does not
authorize deleting backend History records or unrelated volumes. `Retain` PVs may remain
after claim deletion; inventory them separately and release their capacity only through an
explicit cleanup operation.

No automatic deletion or live reset is part of the provisioning code. If the rollout fails,
stop the fresh VM Sandboxes and revert the template/configuration change. A raw-block claim
cannot be reused as a legacy image-file workspace; recreate disposable test Sandboxes with
matching claims, or retain any newly authored data for a separately chosen recovery. Reverting
code cannot recover data discarded by the accepted reset.

## Deferred endpoint

Eventually both Pod and VM Sandboxes should use Piraeus-backed block storage for state and
workspace, removing the VM state virtiofs attachment. Define the Pod mount/format ownership
and supported PVC modes before selecting an implementation. Virtio remains the VM's block
device transport; the filesystem-sharing transport being retired is virtiofs. Preserve
journal and native-harness persistence, ordinary suspend/resume, UID/permission behavior,
resource accounting and explicit compatibility checks for kind changes. This broader
change is deferred and does not gate the workspace cutover.
