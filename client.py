"""
SpeedTest Tunnel - Client Component (Local SOCKS5 Proxy)
Runs locally, disguises all traffic as Ookla speedtest downloads.

Usage: python3 client.py --server YOUR_VPS_IP --password YOUR_SECRET [--port 1080]

Then configure your system/browser to use SOCKS5 proxy at 127.0.0.1:1080
"""

import asyncio
import argparse
import hashlib
import logging
import struct
import random

logger = logging.getLogger("tunnel-client")

# Ookla-style HTTP request template
SPEEDTEST_REQUEST_TEMPLATE = (
    "GET /speedtest/random{size}x{size}.jpg?x={timestamp}.{bump} HTTP/1.1\r\n"
    "Host: {host}\r\n"
    "User-Agent: Mozilla/5.0 (compatible; speedtest-cli)\r\n"
    "Cache-Control: no-cache\r\n"
    "Connection: keep-alive\r\n"
    "Accept: */*\r\n"
    "X-Speedtest-Token: {auth}\r\n"
    "X-Speedtest-Target: {target}\r\n"
    "\r\n"
)

SIZES = [3000, 3500, 4000]


def make_auth_token(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()[:32]


async def handle_socks5(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                        server_host: str, server_port: int, password: str):
    """Handle a SOCKS5 client connection."""
    addr = writer.get_extra_info("peername")

    try:
        # SOCKS5 handshake
        header = await asyncio.wait_for(reader.readexactly(2), timeout=10)
        ver, nmethods = struct.unpack("!BB", header)
        if ver != 5:
            writer.close()
            return

        methods = await reader.readexactly(nmethods)
        # No auth required for local proxy
        writer.write(struct.pack("!BB", 5, 0))
        await writer.drain()

        # SOCKS5 request
        req_header = await asyncio.wait_for(reader.readexactly(4), timeout=10)
        ver, cmd, _, atyp = struct.unpack("!BBBB", req_header)

        if cmd != 1:  # Only CONNECT supported
            writer.write(struct.pack("!BBBBIH", 5, 7, 0, 1, 0, 0))
            await writer.drain()
            writer.close()
            return

        # Read target address
        if atyp == 1:  # IPv4
            raw_addr = await reader.readexactly(4)
            target_host = ".".join(str(b) for b in raw_addr)
        elif atyp == 3:  # Domain
            domain_len = (await reader.readexactly(1))[0]
            target_host = (await reader.readexactly(domain_len)).decode()
        elif atyp == 4:  # IPv6
            raw_addr = await reader.readexactly(16)
            target_host = ":".join(f"{raw_addr[i]:02x}{raw_addr[i+1]:02x}"
                                   for i in range(0, 16, 2))
        else:
            writer.write(struct.pack("!BBBBIH", 5, 8, 0, 1, 0, 0))
            await writer.drain()
            writer.close()
            return

        target_port = struct.unpack("!H", await reader.readexactly(2))[0]

        logger.info(f"{addr} -> {target_host}:{target_port}")

        # Connect to tunnel server
        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(server_host, server_port),
                timeout=10
            )
        except Exception as e:
            logger.error(f"Cannot connect to tunnel server: {e}")
            writer.write(struct.pack("!BBBBIH", 5, 5, 0, 1, 0, 0))
            await writer.drain()
            writer.close()
            return

        # Send Ookla-disguised HTTP request
        import time
        size = random.choice(SIZES)
        request = SPEEDTEST_REQUEST_TEMPLATE.format(
            size=size,
            timestamp=int(time.time() * 1000),
            bump=random.randint(0, 99),
            host=server_host,
            auth=make_auth_token(password),
            target=f"{target_host}:{target_port}"
        )
        remote_writer.write(request.encode())
        await remote_writer.drain()

        # Read server's HTTP response header
        while True:
            line = await asyncio.wait_for(remote_reader.readline(), timeout=10)
            if line in (b"\r\n", b"\n", b""):
                break
            response_line = line.decode("utf-8", errors="ignore").strip()
            if response_line.startswith("HTTP/") and "200" not in response_line:
                logger.error(f"Tunnel server rejected: {response_line}")
                writer.write(struct.pack("!BBBBIH", 5, 5, 0, 1, 0, 0))
                await writer.drain()
                remote_writer.close()
                writer.close()
                return

        # SOCKS5 success response
        writer.write(struct.pack("!BBBBIH", 5, 0, 0, 1, 0, 0))
        await writer.drain()

        # Bidirectional relay with proper shutdown
        done = asyncio.Event()

        async def relay(src, dst, label):
            try:
                while not done.is_set():
                    data = await asyncio.wait_for(src.read(65536), timeout=300)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except (ConnectionResetError, BrokenPipeError,
                    asyncio.CancelledError, asyncio.TimeoutError, OSError):
                pass
            finally:
                done.set()

        try:
            await asyncio.gather(
                relay(reader, remote_writer, "app->tunnel"),
                relay(remote_reader, writer, "tunnel->app"),
            )
        finally:
            for w in (remote_writer, writer):
                try:
                    w.close()
                except Exception:
                    pass

    except asyncio.TimeoutError:
        logger.warning(f"Timeout from {addr}")
    except Exception as e:
        logger.debug(f"Connection error {addr}: {e}")
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main(local_port: int, server_host: str, server_port: int, password: str):
    server = await asyncio.start_server(
        lambda r, w: handle_socks5(r, w, server_host, server_port, password),
        "127.0.0.1", local_port
    )
    logger.info(f"SOCKS5 proxy listening on 127.0.0.1:{local_port}")
    logger.info(f"Tunnel server: {server_host}:{server_port}")
    logger.info(f"Configure your system proxy to SOCKS5 127.0.0.1:{local_port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SpeedTest Tunnel Client (SOCKS5)")
    parser.add_argument("--server", required=True, help="VPS IP address")
    parser.add_argument("--server-port", type=int, default=8080)
    parser.add_argument("--port", type=int, default=1080,
                        help="Local SOCKS5 proxy port")
    parser.add_argument("--password", type=str, default="",
                        help="Shared secret (must match server)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    asyncio.run(main(args.port, args.server, args.server_port, args.password))
