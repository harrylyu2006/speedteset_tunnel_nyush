#!/bin/bash
# SpeedTest Tunnel - Client Setup (run on your Mac)
# Usage: bash setup_client.sh

set -e

LOCAL_PORT=1080
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "  SpeedTest Tunnel - Client Setup"
echo "========================================"
echo ""

# 1. Get server info
read -p "VPS IP address: " SERVER_IP
if [ -z "$SERVER_IP" ]; then
    echo "Error: server IP required"
    exit 1
fi

read -p "VPS port [8080]: " SERVER_PORT
SERVER_PORT=${SERVER_PORT:-8080}

read -sp "Tunnel password: " PASSWORD
echo ""
if [ -z "$PASSWORD" ]; then
    echo "Error: password required"
    exit 1
fi

# 2. Check Python
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

# 3. Test connectivity to VPS
echo ""
echo "[1/4] Testing connectivity to ${SERVER_IP}:${SERVER_PORT}..."
if python3 -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(('${SERVER_IP}', ${SERVER_PORT}))
    s.close()
    print('  Connected OK')
except Exception as e:
    print(f'  FAILED: {e}')
    sys.exit(1)
"; then
    echo "[OK] VPS reachable"
else
    echo ""
    echo "Cannot connect to VPS. Check:"
    echo "  1. server.py is running on VPS"
    echo "  2. Firewall allows port ${SERVER_PORT}"
    echo "  3. IP address is correct"
    exit 1
fi

# 4. Run DPI bypass verification
echo ""
echo "[2/4] Verifying DPI bypass on your network..."
python3 "${SCRIPT_DIR}/test_local.py" 2>/dev/null || echo "  (test_local.py not available, skipping)"

# 5. Start tunnel client
echo ""
echo "[3/4] Starting tunnel client..."

# Kill any existing tunnel
pkill -f "client.py.*--server.*--port ${LOCAL_PORT}" 2>/dev/null || true
sleep 0.5

# Start in background
nohup python3 "${SCRIPT_DIR}/client.py" \
    --server "${SERVER_IP}" \
    --server-port "${SERVER_PORT}" \
    --port "${LOCAL_PORT}" \
    --password "${PASSWORD}" \
    > /tmp/speedtest-tunnel-client.log 2>&1 &

CLIENT_PID=$!
sleep 1.5

if kill -0 $CLIENT_PID 2>/dev/null; then
    echo "[OK] Client running (PID: ${CLIENT_PID})"
else
    echo "[FAIL] Client crashed. Log:"
    cat /tmp/speedtest-tunnel-client.log
    exit 1
fi

# 6. Quick connectivity test through tunnel
echo ""
echo "[4/4] Testing tunnel connectivity..."
RESULT=$(curl --socks5-hostname 127.0.0.1:${LOCAL_PORT} \
    -o /dev/null -w "%{http_code}" -s -m 10 \
    "https://httpbin.org/get" 2>/dev/null)

if [ "$RESULT" = "200" ]; then
    echo "[OK] Tunnel working! HTTPS connectivity verified."
else
    echo "[WARN] Tunnel test returned HTTP ${RESULT}"
    echo "  Check log: cat /tmp/speedtest-tunnel-client.log"
fi

# 7. Configure system proxy
echo ""
echo "========================================"
echo "  Tunnel ready!"
echo "========================================"
echo ""
echo "  SOCKS5 proxy: 127.0.0.1:${LOCAL_PORT}"
echo ""
echo "  Option A: Set system-wide proxy (macOS):"
echo "    networksetup -setsocksfirewallproxy Wi-Fi 127.0.0.1 ${LOCAL_PORT}"
echo "    networksetup -setsocksfirewallproxystate Wi-Fi on"
echo ""
echo "  Option B: Browser only (install SwitchyOmega/FoxyProxy)"
echo "    SOCKS5 → 127.0.0.1:${LOCAL_PORT}"
echo ""

read -p "Enable system-wide proxy now? [y/N]: " ENABLE_PROXY
if [[ "$ENABLE_PROXY" =~ ^[Yy]$ ]]; then
    # Detect active network interface
    IFACE=$(networksetup -listallnetworkservices | grep -E "Wi-Fi|Ethernet" | head -1)
    if [ -n "$IFACE" ]; then
        networksetup -setsocksfirewallproxy "$IFACE" 127.0.0.1 ${LOCAL_PORT}
        networksetup -setsocksfirewallproxystate "$IFACE" on
        echo "[OK] System proxy enabled on ${IFACE}"
        echo ""
        echo "  To disable later:"
        echo "    networksetup -setsocksfirewallproxystate '${IFACE}' off"
    else
        echo "Could not detect network interface. Set proxy manually."
    fi
fi

echo ""
echo "  Quick speed test:"
echo "    curl --socks5-hostname 127.0.0.1:${LOCAL_PORT} -o /dev/null -w '%{speed_download}' https://speed.cloudflare.com/__down?bytes=10000000"
echo ""
echo "  Manage:"
echo "    Stop:    kill ${CLIENT_PID}"
echo "    Log:     tail -f /tmp/speedtest-tunnel-client.log"
echo "    Restart: bash ${SCRIPT_DIR}/setup_client.sh"
echo ""
