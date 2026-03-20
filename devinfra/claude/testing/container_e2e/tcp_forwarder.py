"""Minimal TCP forwarder for the proxy sidecar container.

Accepts TCP connections on a local port and forwards them to a destination
host:port. Used by the container E2E test to bridge traffic from the
isolated internal Docker network to the host-side MockEgressProxy.

Usage: python tcp_forwarder.py <listen_port> <dest_host> <dest_port>
"""

import asyncio
import sys


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while data := await src.read(65536):
            dst.write(data)
            await dst.drain()
    except (OSError, ConnectionError):
        pass


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, dest_host: str, dest_port: int) -> None:
    try:
        dest_reader, dest_writer = await asyncio.open_connection(dest_host, dest_port)
    except OSError:
        writer.close()
        return
    try:
        await asyncio.gather(_pipe(reader, dest_writer), _pipe(dest_reader, writer))
    finally:
        writer.close()
        dest_writer.close()


async def main(listen_port: int, dest_host: str, dest_port: int) -> None:
    server = await asyncio.start_server(lambda r, w: _handle(r, w, dest_host, dest_port), "0.0.0.0", listen_port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <listen_port> <dest_host> <dest_port>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(int(sys.argv[1]), sys.argv[2], int(sys.argv[3])))
