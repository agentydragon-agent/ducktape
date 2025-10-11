from __future__ import annotations

import anyio


async def await_tcp_ready(
    host: str, port: int, *, attempts: int = 50, sleep_s: float = 0.05
) -> None:
    """Await until a TCP connect to (host, port) succeeds.

    Raises TimeoutError after the configured number of attempts.
    """
    for _ in range(int(attempts)):
        try:
            stream = await anyio.connect_tcp(host, port)
            await stream.aclose()
            return
        except OSError:
            await anyio.sleep(sleep_s)
    raise TimeoutError(f"TCP not ready on {host}:{port} after {attempts} probes")
