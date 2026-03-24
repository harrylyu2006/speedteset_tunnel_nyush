#!/bin/bash
# SpeedTest Tunnel — One-line client deploy
# Usage: curl -fsSL https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main/install_client.sh | bash
set -e

REPO="https://github.com/harrylyu2006/speedteset_tunnel_nyush.git"
DIR="$HOME/.speedtest-tunnel"
LOCAL_PORT=1080

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   SpeedTest Tunnel — Client Setup    ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Check python3
command -v python3 &>/dev/null || { echo "  Error: python3 not found"; exit 1; }

# Clone or update repo
if [ -d "$DIR/.git" ]; then
    echo "  Updating existing install..."
    git -C "$DIR" pull --quiet 2>/dev/null || true
else
    echo "  Downloading..."
    rm -rf "$DIR"
    git clone --quiet "$REPO" "$DIR" 2>/dev/null || {
        # Fallback: download files directly if git not available
        mkdir -p "$DIR"
        RAWURL="https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main"
        for f in client.py server.py test_local.py test_e2e.py; do
            curl -fsSL "${RAWURL}/${f}" -o "${DIR}/${f}"
        done
    }
fi
echo "  [OK] Installed to ${DIR}"

# DPI bypass test
echo ""
echo "  Testing DPI bypass on your network..."
echo "  ─────────────────────────────────────"
python3 "${DIR}/test_local.py" 2>/dev/null || true
echo "  ─────────────────────────────────────"

# Get server info (all reads from /dev/tty for curl|bash compatibility)
echo ""
printf "  VPS IP address: " > /dev/tty
read SERVER_IP < /dev/tty
if [ -z "$SERVER_IP" ]; then echo "  Error: IP required"; exit 1; fi

printf "  VPS port [8080]: " > /dev/tty
read SERVER_PORT < /dev/tty
SERVER_PORT=${SERVER_PORT:-8080}

printf "  Tunnel password: " > /dev/tty
read -s PASSWORD < /dev/tty
echo "" > /dev/tty
if [ -z "$PASSWORD" ]; then echo "  Error: password required"; exit 1; fi

# Test connectivity
echo ""
echo "  Testing connection to ${SERVER_IP}:${SERVER_PORT}..."
python3 -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(('${SERVER_IP}', ${SERVER_PORT}))
    s.close()
    print('  [OK] VPS reachable')
except Exception as e:
    print(f'  [FAIL] {e}')
    print('  Check: server running? firewall open? IP correct?')
    sys.exit(1)
" || exit 1

# Kill existing
pkill -f "client.py.*--port ${LOCAL_PORT}" 2>/dev/null || true
sleep 0.5

# Start client
echo "  Starting SOCKS5 proxy on 127.0.0.1:${LOCAL_PORT}..."
nohup python3 "${DIR}/client.py" \
    --server "${SERVER_IP}" \
    --server-port "${SERVER_PORT}" \
    --port "${LOCAL_PORT}" \
    --password "${PASSWORD}" \
    > /tmp/speedtest-tunnel-client.log 2>&1 &

CLIENT_PID=$!
sleep 1.5

if ! kill -0 $CLIENT_PID 2>/dev/null; then
    echo "  [FAIL] Client crashed:"
    cat /tmp/speedtest-tunnel-client.log
    exit 1
fi

# Verify
echo "  Testing tunnel..."
RESULT=$(curl --socks5-hostname 127.0.0.1:${LOCAL_PORT} \
    -o /dev/null -w "%{http_code}" -s -m 10 \
    "https://httpbin.org/get" 2>/dev/null || echo "000")

if [ "$RESULT" = "200" ]; then
    echo "  [OK] Tunnel working!"
else
    echo "  [WARN] Test returned HTTP ${RESULT} (tunnel may still work)"
fi

# Enable system proxy automatically on macOS
PROXY_ENABLED=""
if [[ "$(uname)" == "Darwin" ]]; then
    # Find active network interface
    IFACE=""
    for candidate in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN"; do
        STATUS=$(networksetup -getinfo "$candidate" 2>/dev/null | grep "^IP address:" | awk '{print $3}')
        if [ -n "$STATUS" ] && [ "$STATUS" != "none" ]; then
            IFACE="$candidate"
            break
        fi
    done

    if [ -n "$IFACE" ]; then
        echo "  Enabling system proxy on ${IFACE}..."
        networksetup -setsocksfirewallproxy "$IFACE" 127.0.0.1 ${LOCAL_PORT}
        networksetup -setsocksfirewallproxystate "$IFACE" on
        # Bypass proxy for local addresses
        networksetup -setproxybypassdomains "$IFACE" \
            "*.local" "169.254/16" "127.0.0.1" "localhost" "10.0.0.0/8" "172.16.0.0/12" "192.168.0.0/16" \
            2>/dev/null || true
        PROXY_ENABLED="$IFACE"
        echo "  [OK] System proxy enabled — all traffic now goes through tunnel"
    else
        echo "  [WARN] Could not detect active network interface"
        echo "  Set SOCKS5 proxy manually: 127.0.0.1:${LOCAL_PORT}"
    fi
fi

# Create stop script (also disables system proxy)
cat > "${DIR}/stop.sh" <<'STOPSCRIPT'
#!/bin/bash
echo "Stopping SpeedTest Tunnel..."
pkill -f "client.py.*--server" 2>/dev/null && echo "[OK] Client stopped" || echo "Not running"
if [[ "$(uname)" == "Darwin" ]]; then
    for IFACE in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN"; do
        STATE=$(networksetup -getsocksfirewallproxy "$IFACE" 2>/dev/null | grep "^Enabled" | awk '{print $2}')
        if [ "$STATE" = "Yes" ]; then
            networksetup -setsocksfirewallproxystate "$IFACE" off
            echo "[OK] Proxy disabled on ${IFACE}"
        fi
    done
fi
echo "Done."
STOPSCRIPT
chmod +x "${DIR}/stop.sh"

# Done
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║         Tunnel is ready!             ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  SOCKS5 proxy:  127.0.0.1:${LOCAL_PORT}"
if [ -n "$PROXY_ENABLED" ]; then
echo "  System proxy:  ON (${PROXY_ENABLED})"
echo ""
echo "  All apps now use the tunnel. Open a browser and enjoy!"
fi
echo ""
echo "  Stop tunnel & restore proxy:"
echo "    ~/.speedtest-tunnel/stop.sh"
echo ""
