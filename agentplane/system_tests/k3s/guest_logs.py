"""Retain guest console CRI logs before kubelet removes a VM launcher's log directory."""

import os
import shutil
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import BinaryIO


def _copy(log_root: Path, namespace: str, destination: Path, stop: threading.Event) -> None:
    # Open descriptors keep the last bytes readable after suspend/delete unlinks the source.
    opened: set[tuple[int, int]] = set()
    streams: list[tuple[BinaryIO, BinaryIO]] = []
    with ExitStack() as files:
        while True:
            for path in log_root.glob(f"{namespace}_virt-launcher-*/guest-console-log/*.log*"):
                try:
                    source = path.open("rb")
                except FileNotFoundError:
                    # kubelet may remove a launcher between directory enumeration and open.
                    continue
                with source:
                    stat = os.fstat(source.fileno())
                    identity = (stat.st_dev, stat.st_ino)
                    if identity in opened:
                        continue
                    target = destination / path.parent.parent.name / f"{path.name}-{identity[1]}.cri.log"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # dup the open descriptor, retaining the inode even if its pathname disappears.
                    retained = files.enter_context(os.fdopen(os.dup(source.fileno()), "rb"))
                    streams.append((retained, files.enter_context(target.open("wb"))))
                    opened.add(identity)
            for source, target in streams:
                shutil.copyfileobj(source, target)
                target.flush()
            if stop.is_set():
                return
            stop.wait(0.1)


@contextmanager
def capture(*, log_root: Path, namespace: str, destination: Path) -> Iterator[None]:
    stop = threading.Event()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="vm-guest-logs") as executor:
        copying = executor.submit(_copy, log_root, namespace, destination, stop)
        try:
            yield
        finally:
            stop.set()
            copying.result()
