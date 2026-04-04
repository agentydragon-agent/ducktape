"""Testcontainers subclass that persists container logs to undeclared test outputs."""

from types import TracebackType

from testcontainers.core.container import DockerContainer

from util.testing.undeclared_outputs import undeclared_outputs_dir


class LoggedContainer(DockerContainer):
    """DockerContainer that persists stdout/stderr to undeclared test outputs on exit.

    Drop-in replacement for DockerContainer. Collects logs before the container
    is removed — including on test failure or timeout.
    """

    def __init__(self, *args, test_name: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._test_name = test_name

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        out_dir = undeclared_outputs_dir() / self._test_name
        out_dir.mkdir(parents=True, exist_ok=True)
        stdout, stderr = self.get_logs()
        for name, data in [("stdout.log", stdout), ("stderr.log", stderr)]:
            (out_dir / name).write_bytes(data)
        super().__exit__(exc_type, exc_val, exc_tb)
