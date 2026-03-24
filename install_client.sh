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
    git -C "$DIR" pull --quiet 2>/dev/null || true
else
    rm -rf "$DIR"
    git clone --quiet "$REPO" "$DIR" 2>/dev/null || {
        mkdir -p "$DIR"
        RAWURL="https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main"
        for f in client.py server.py; do
            curl -fsSL "${RAWURL}/${f}" -o "${DIR}/${f}"
        done
    }
fi

# Get server info
printf "  VPS IP address: " > /dev/tty
read SERVER_IP < /dev/tty
if [ -z "$SERVER_IP" ]; then echo "  Error: IP required"; exit 1; fi

printf "  VPS port [8080]: " > /dev/tty
read SERVER_PORT < /dev/tty
SERVER_PORT=${SERVER_PORT:-8080}

printf "  Tunnel password: " > /dev/tty
read PASSWORD < /dev/tty
if [ -z "$PASSWORD" ]; then echo "  Error: password required"; exit 1; fi

# Kill existing
pkill -f "client.py.*--port ${LOCAL_PORT}" 2>/dev/null || true
sleep 0.5

# Start client
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

# Enable system proxy on macOS
PROXY_ENABLED=""
if [[ "$(uname)" == "Darwin" ]]; then
    IFACE=""
    for candidate in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN"; do
        STATUS=$(networksetup -getinfo "$candidate" 2>/dev/null | grep "^IP address:" | awk '{print $3}')
        if [ -n "$STATUS" ] && [ "$STATUS" != "none" ]; then
            IFACE="$candidate"
            break
        fi
    done

    if [ -n "$IFACE" ]; then
        networksetup -setsocksfirewallproxy "$IFACE" 127.0.0.1 ${LOCAL_PORT}
        networksetup -setsocksfirewallproxystate "$IFACE" on
        networksetup -setproxybypassdomains "$IFACE" \
            "*.local" "169.254/16" "127.0.0.1" "localhost" "10.0.0.0/8" "172.16.0.0/12" "192.168.0.0/16" \
            2>/dev/null || true
        PROXY_ENABLED="$IFACE"
    fi
fi

# Create stop script
cat > "${DIR}/stop.sh" <<'STOPSCRIPT'
#!/bin/bash
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
STOPSCRIPT
chmod +x "${DIR}/stop.sh"

# Done
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║              Ready!                  ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
if [ -n "$PROXY_ENABLED" ]; then
echo "  System proxy ON (${PROXY_ENABLED}) — go browse."
else
echo "  Set SOCKS5 proxy to 127.0.0.1:${LOCAL_PORT}"
fi
echo "  Stop: ~/.speedtest-tunnel/stop.sh"
echo ""
