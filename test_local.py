"""
Local DPI bypass test - verify the approach works WITHOUT a VPS.
Tests if disguising HTTP requests as Ookla speedtest triggers DPI bypass.

Usage: python3 test_local.py
"""

import subprocess
import time
import threading


def curl_test(label: str, url: str, count: int = 8) -> float:
    """Run parallel curl downloads and return Mbps."""
    results = [0] * count

    def worker(idx):
        r = subprocess.run(
            ["curl", "-o", "/dev/null", "-w", "%{size_download}", "-s", "-m", "12", url],
            capture_output=True, text=True
        )
        results[idx] = int(r.stdout.strip() or 0)

    start = time.time()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start
    total = sum(results)
    mbps = total * 8 / elapsed / 1e6 if elapsed > 0 else 0
    status = "BYPASS" if mbps > 40 else "THROTTLED"
    print(f"  [{status:9s}] {mbps:6.1f} Mbps | {label}")
    return mbps


def main():
    host = "sp3.atcc-gns.net:8080"  # ATCC - NOT IP-whitelisted
    ts = int(time.time() * 1000)

    print("=" * 70)
    print("DPI Bypass Verification Test")
    print("Target: ATCC Ookla server (NOT IP-whitelisted)")
    print("If /speedtest/ path gets >40 Mbps, DPI bypass works.")
    print("=" * 70)
    print()

    print("[Baseline - should be throttled]")
    baseline = curl_test(
        "/download?size=10M (normal HTTP)",
        f"http://{host}/download?size=10000000"
    )
    print()

    print("[DPI bypass - should be fast]")
    bypass = curl_test(
        "/speedtest/random4000x4000.jpg (Ookla pattern)",
        f"http://{host}/speedtest/random4000x4000.jpg?x={ts}.0"
    )
    print()

    print("[Results]")
    if bypass > baseline * 1.5:
        ratio = bypass / baseline if baseline > 0 else float("inf")
        print(f"  DPI bypass confirmed! {ratio:.1f}x speedup")
        print(f"  Baseline: {baseline:.1f} Mbps -> Bypass: {bypass:.1f} Mbps")
        print()
        print("  Next steps:")
        print("  1. Get a VPS (any provider, any region)")
        print("  2. Deploy server.py on port 8080")
        print("  3. Run client.py locally with your VPS IP")
        print("  4. Set system SOCKS5 proxy to 127.0.0.1:1080")
    else:
        print(f"  DPI bypass NOT effective (baseline={baseline:.1f}, test={bypass:.1f})")
        print("  The DPI rules may have changed.")


if __name__ == "__main__":
    main()
