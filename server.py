"""
SpeedTest Tunnel - Server Component
Deploy on a VPS, listens on port 8080.
Makes tunnel traffic look like Ookla speedtest downloads to bypass DPI.

Usage: python3 server.py [--port 8080] [--password YOUR_SECRET]
"""

import asyncio
import argparse
import hashlib
import logging
import struct
import os

logger = logging.getLogger("tunnel-server")

# Ookla-style HTTP response header
SPEEDTEST_RESPONSE_HEADER = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/octet-stream\r\n"
    b"Content-Disposition: attachment; filename=random4000x4000.jpg\r\n"
    b"Cache-Control: no-cache, no-store\r\n"
    b"Connection: keep-alive\r\n"
    b"Transfer-Encoding: chunked\r\n"
    b"\r\n"
)


def verify_auth(auth_header: str, password: str) -> bool:
    """Verify the auth token from client."""
    expected = hashlib.sha256(password.encode()).hexdigest()[:32]
    return auth_header == expected


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                        password: str):
    """Handle incoming tunnel connection."""
    addr = writer.get_extra_info("peername")
    logger.info(f"Connection from {addr}")

    try:
        # Step 1: Read the HTTP request from client
        request_line = await asyncio.wait_for(reader.readline(), timeout=10)
        if not request_line:
            return

        request_str = request_line.decode("utf-8", errors="ignore").strip()
        logger.debug(f"Request: {request_str}")

        # Verify it looks like a speedtest request
        if "/speedtest/random" not in request_str:
            writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
            await writer.drain()
            return

        # Read remaining headers
        headers = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            if line in (b"\r\n", b"\n", b""):
                break
            if b":" in line:
                key, val = line.decode("utf-8", errors="ignore").split(":", 1)
                headers[key.strip().lower()] = val.strip()

        # Step 2: Verify auth
        auth = headers.get("x-speedtest-token", "")
        if password and not verify_auth(auth, password):
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await writer.drain()
            logger.warning(f"Auth failed from {addr}")
            return

        # Step 3: Read tunnel target from header
        target = headers.get("x-speedtest-target", "")
        if not target or ":" not in target:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            return

        target_host, target_port = target.rsplit(":", 1)
        target_port = int(target_port)
        logger.info(f"Tunnel: {addr} -> {target_host}:{target_port}")

        # Step 4: Connect to target
        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(target_host, target_port),
                timeout=10
            )
        except Exception as e:
            logger.error(f"Failed to connect to {target_host}:{target_port}: {e}")
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            return

        # Step 5: Send speedtest-style HTTP response (this is what DPI sees)
        writer.write(SPEEDTEST_RESPONSE_HEADER)
        await writer.drain()

        # Step 6: Bidirectional relay with proper shutdown
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
                relay(reader, remote_writer, "client->remote"),
                relay(remote_reader, writer, "remote->client"),
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
        logger.error(f"Error handling {addr}: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info(f"Closed {addr}")


async def main(port: int, password: str):
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, password),
        "0.0.0.0", port
    )
    logger.info(f"Tunnel server listening on 0.0.0.0:{port}")
    logger.info(f"Auth: {'enabled' if password else 'DISABLED (not recommended)'}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SpeedTest Tunnel Server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--password", type=str, default="",
                        help="Shared secret for authentication")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    asyncio.run(main(args.port, args.password))
