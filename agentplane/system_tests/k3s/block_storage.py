"""Scoped loop-backed static Block PVs for the VM acceptance stack.

The RBE action exposes loop devices but does not carry losetup. The fixture owns sparse backing files
and the loop fds it attaches, so teardown can detach only those devices after k3s removes its Pods.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

STORAGE_CLASS = "agentplane-test-loop-block"
CLAIM_CAPACITY = "10Gi"
_CLAIM_CAPACITY_BYTES = 10 * 1024**3
# The VM suite creates one workspace per harness plus the Codex OOM workspace. Retained static PVs
# stay Released after their claim is deleted and cannot bind another test's fresh claim.
_PV_COUNT = 3

_LOOP_CTL_GET_FREE = 0x4C82
_LOOP_SET_FD = 0x4C00
_LOOP_CLR_FD = 0x4C01
_LOOP_SET_STATUS64 = 0x4C04
_LOOP_INFO64_SIZE = 232
_LO_FLAGS_AUTOCLEAR = 4
_LO_FLAGS_OFFSET = 52
_ATTACH_ATTEMPTS = 8
_DETACH_TIMEOUT_SECONDS = 30.0
_DETACH_POLL_SECONDS = 0.1


@dataclass
class _LoopDevice:
    index: int
    path: Path
    backing_file: Path
    backing_fd: int
    device_fd: int
    attached: bool = True
    detach_requested: bool = False

    @classmethod
    def attach(cls, backing_file: Path) -> _LoopDevice:
        backing_fd = os.open(backing_file, os.O_RDWR | os.O_CLOEXEC)
        control_fd = os.open("/dev/loop-control", os.O_RDWR | os.O_CLOEXEC)
        try:
            for _ in range(_ATTACH_ATTEMPTS):
                index = fcntl.ioctl(control_fd, _LOOP_CTL_GET_FREE)
                path = Path(f"/dev/loop{index}")
                info = path.stat()
                if not stat.S_ISBLK(info.st_mode) or os.major(info.st_rdev) != 7 or os.minor(info.st_rdev) != index:
                    raise RuntimeError(f"loop-control selected an unexpected device node: {path}")
                device_fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
                try:
                    # LOOP_SET_FD atomically claims a free device. If another fixture races us, retry
                    # only EBUSY; every other failure is actionable and must reach the test.
                    fcntl.ioctl(device_fd, _LOOP_SET_FD, backing_fd)
                except OSError as error:
                    os.close(device_fd)
                    if error.errno == errno.EBUSY:
                        continue
                    raise
                return cls(index, path, backing_file, backing_fd, device_fd)
        except BaseException:
            os.close(backing_fd)
            raise
        finally:
            os.close(control_fd)
        os.close(backing_fd)
        raise RuntimeError(f"could not attach {backing_file}: no free loop device after {_ATTACH_ATTEMPTS} attempts")

    def enable_autoclear(self) -> None:
        """Clear the mapping when the fixture process exits if explicit teardown cannot run."""
        info = bytearray(_LOOP_INFO64_SIZE)
        struct.pack_into("=I", info, _LO_FLAGS_OFFSET, _LO_FLAGS_AUTOCLEAR)
        fcntl.ioctl(self.device_fd, _LOOP_SET_STATUS64, info, True)

    def detach(self) -> None:
        if not self.attached:
            return
        if not self.detach_requested:
            try:
                fcntl.ioctl(self.device_fd, _LOOP_CLR_FD)
            except OSError as error:
                if error.errno != errno.ENXIO:
                    raise RuntimeError(
                        f"failed to detach fixture-owned {self.path} backed by {self.backing_file}"
                    ) from error
                # Someone may have detached our loop already. Do not issue another clear: that device number
                # could have been reassigned to another owner between those operations.
            self.detach_requested = True
            device_fd, self.device_fd = self.device_fd, -1
            backing_fd, self.backing_fd = self.backing_fd, -1
            os.close(device_fd)
            os.close(backing_fd)

        # LOOP_CLR_FD honors AUTOCLEAR when a pod still has the block device open. Drop our descriptors
        # before checking sysfs so that only external users can keep the mapping alive.
        sysfs_backing_file = Path(f"/sys/block/loop{self.index}/loop/backing_file")
        deadline = time.monotonic() + _DETACH_TIMEOUT_SECONDS
        while True:
            try:
                backing_file = sysfs_backing_file.read_text().strip()
            except FileNotFoundError:
                backing_file = ""
            if not backing_file or backing_file != str(self.backing_file):
                self.attached = False
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(f"fixture loop remained attached after teardown: {self.path}")
            time.sleep(_DETACH_POLL_SECONDS)


class BlockStorage:
    """A single-node pool for VM workspace claims in one disposable k3s stack."""

    def __init__(self, work: Path) -> None:
        self.work = work / "raw-block"
        self.suffix = uuid4().hex[:10]
        self.devices: list[_LoopDevice] = []
        self.closed = False

    def prepare(self) -> list[dict[str, object]]:
        """Create sparse 10 GiB files, attach only those files, and return static PV objects."""
        if self.devices:
            raise RuntimeError("raw block storage was already prepared")
        self.work.mkdir()
        for index in range(_PV_COUNT):
            backing_file = self.work / f"workspace-{index}.img"
            with backing_file.open("xb") as backing:
                backing.truncate(_CLAIM_CAPACITY_BYTES)
            device = _LoopDevice.attach(backing_file)
            self.devices.append(device)
            device.enable_autoclear()
        return self.objects(node_name="env")

    def objects(self, *, node_name: str) -> list[dict[str, object]]:
        if len(self.devices) != _PV_COUNT:
            raise RuntimeError("raw block storage must be prepared before creating PVs")
        storage_class: dict[str, object] = {
            "apiVersion": "storage.k8s.io/v1",
            "kind": "StorageClass",
            "metadata": {"name": STORAGE_CLASS},
            "provisioner": "kubernetes.io/no-provisioner",
            "volumeBindingMode": "WaitForFirstConsumer",
        }
        persistent_volumes: list[dict[str, object]] = [
            {
                "apiVersion": "v1",
                "kind": "PersistentVolume",
                "metadata": {"name": f"agentplane-{self.suffix}-block-{index}"},
                "spec": {
                    "capacity": {"storage": CLAIM_CAPACITY},
                    "volumeMode": "Block",
                    "accessModes": ["ReadWriteOnce"],
                    "persistentVolumeReclaimPolicy": "Retain",
                    "storageClassName": STORAGE_CLASS,
                    "local": {"path": str(device.path)},
                    "nodeAffinity": {
                        "required": {
                            "nodeSelectorTerms": [
                                {
                                    "matchExpressions": [
                                        {"key": "kubernetes.io/hostname", "operator": "In", "values": [node_name]}
                                    ]
                                }
                            ]
                        }
                    },
                },
            }
            for index, device in enumerate(self.devices)
        ]
        return [storage_class, *persistent_volumes]

    def close(self) -> None:
        if self.closed:
            return
        errors: list[Exception] = []
        for device in reversed(self.devices):
            try:
                device.detach()
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("raw block fixture could not release its loop devices", errors)
        self.closed = True
