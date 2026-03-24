"""
End-to-end local test for the tunnel.
Starts server + client locally and tests connectivity.

Usage: python3 test_e2e.py
"""

import asyncio
import subprocess
import time
import sys
import os
import signal


async def run_test():
    password = "test-secret-123"

    print("=" * 60)
    print("End-to-End Tunnel Test (local)")
    print("=" * 60)
    print()

    # Start server on port 18080 (local test port)
    print("[1/4] Starting tunnel server on port 18080...")
    server_proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", "18080", "--password", password],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    await asyncio.sleep(1)

    if server_proc.poll() is not None:
        print(f"  Server failed to start!")
        _, stderr = server_proc.communicate()
        print(f"  Error: {stderr.decode()}")
        return False

    print("  Server started OK")

    # Start client on port 11080
    print("[2/4] Starting tunnel client (SOCKS5) on port 11080...")
    client_proc = subprocess.Popen(
        [sys.executable, "client.py",
         "--server", "127.0.0.1", "--server-port", "18080",
         "--port", "11080", "--password", password],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    await asyncio.sleep(1)

    if client_proc.poll() is not None:
        print(f"  Client failed to start!")
        _, stderr = client_proc.communicate()
        print(f"  Error: {stderr.decode()}")
        server_proc.terminate()
        return False

    print("  Client started OK")

    # Test connectivity through tunnel
    print("[3/4] Testing connectivity through tunnel...")
    try:
        result = subprocess.run(
            ["curl", "--socks5-hostname", "127.0.0.1:11080",
             "-o", "/dev/null", "-w", "%{http_code} %{size_download} %{time_total}",
             "-s", "-m", "10",
             "http://httpbin.org/get"],
            capture_output=True, text=True, timeout=15
        )
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            http_code, size = parts[0], parts[1]
            print(f"  HTTP {http_code}, {size} bytes downloaded")
            if http_code == "200":
                print("  Connectivity: OK")
            else:
                print(f"  Connectivity: FAILED (HTTP {http_code})")
        else:
            print(f"  Connectivity: FAILED ({result.stdout})")
            if result.stderr:
                print(f"  stderr: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("  Connectivity: TIMEOUT")
    except Exception as e:
        print(f"  Connectivity: ERROR ({e})")

    # Test speed through tunnel
    print("[4/4] Speed test through tunnel...")
    try:
        result = subprocess.run(
            ["curl", "--socks5-hostname", "127.0.0.1:11080",
             "-o", "/dev/null",
             "-w", "%{speed_download} %{size_download} %{time_total}",
             "-s", "-m", "10",
             "https://github.com/jgm/pandoc/releases/download/3.6.4/pandoc-3.6.4-arm64-macOS.pkg"],
            capture_output=True, text=True, timeout=15
        )
        parts = result.stdout.strip().split()
        if len(parts) >= 3:
            speed, size, elapsed = float(parts[0]), int(parts[1]), float(parts[2])
            mbps = speed * 8 / 1e6
            print(f"  Speed: {speed/1e6:.1f} MB/s ({mbps:.1f} Mbps)")
            print(f"  Downloaded: {size/1e6:.1f} MB in {elapsed:.1f}s")
        else:
            print(f"  Speed test: no data ({result.stdout})")
    except subprocess.TimeoutExpired:
        print("  Speed test: TIMEOUT")
    except Exception as e:
        print(f"  Speed test: ERROR ({e})")

    # Cleanup
    print()
    print("Cleaning up...")
    server_proc.terminate()
    client_proc.terminate()
    try:
        server_proc.wait(timeout=3)
        client_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        client_proc.kill()

    print("Done.")
    return True


if __name__ == "__main__":
    asyncio.run(run_test())
