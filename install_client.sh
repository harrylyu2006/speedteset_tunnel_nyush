#!/bin/bash
# SpeedTest Tunnel — One-line client deploy
# Usage:
#   Interactive:   curl -fsSL .../install_client.sh | bash
#   With args:     bash install_client.sh -s IP -p PORT -k PASSWORD
set -e

REPO="https://github.com/harrylyu2006/speedteset_tunnel_nyush.git"
DIR="$HOME/.speedtest-tunnel"
LOCAL_PORT=1080
OS="$(uname)"
SERVER_IP=""
SERVER_PORT=""
PASSWORD=""

# Parse optional arguments
while getopts "s:p:k:" opt 2>/dev/null; do
    case $opt in
        s) SERVER_IP="$OPTARG" ;;
        p) SERVER_PORT="$OPTARG" ;;
        k) PASSWORD="$OPTARG" ;;
    esac
done

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

# Prompt only for missing parameters
if [ -z "$SERVER_IP" ]; then
    printf "  VPS IP address: " > /dev/tty
    read SERVER_IP < /dev/tty
    if [ -z "$SERVER_IP" ]; then echo "  Error: IP required"; exit 1; fi
fi

if [ -z "$SERVER_PORT" ]; then
    printf "  VPS port [8080]: " > /dev/tty
    read SERVER_PORT < /dev/tty
fi
SERVER_PORT=${SERVER_PORT:-8080}

if [ -z "$PASSWORD" ]; then
    printf "  Tunnel password: " > /dev/tty
    read PASSWORD < /dev/tty
    if [ -z "$PASSWORD" ]; then echo "  Error: password required"; exit 1; fi
fi

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
echo "  [OK] SOCKS5 proxy running on 127.0.0.1:${LOCAL_PORT}"

# ──────────────────────────────────────
# Enable system proxy (OS-specific)
# ──────────────────────────────────────
PROXY_ENABLED=""

enable_proxy_macos() {
    local IFACE=""
    for candidate in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN" "Thunderbolt Ethernet"; do
        local STATUS
        STATUS=$(networksetup -getinfo "$candidate" 2>/dev/null | grep "^IP address:" | awk '{print $3}')
        if [ -n "$STATUS" ] && [ "$STATUS" != "none" ]; then
            IFACE="$candidate"
            break
        fi
    done
    if [ -z "$IFACE" ]; then return 1; fi

    networksetup -setsocksfirewallproxy "$IFACE" 127.0.0.1 ${LOCAL_PORT}
    networksetup -setsocksfirewallproxystate "$IFACE" on
    networksetup -setproxybypassdomains "$IFACE" \
        "*.local" "169.254/16" "127.0.0.1" "localhost" "10.0.0.0/8" "172.16.0.0/12" "192.168.0.0/16" \
        2>/dev/null || true
    PROXY_ENABLED="macOS: ${IFACE}"
}

enable_proxy_linux_gnome() {
    # GNOME (Ubuntu, Fedora GNOME, Pop!_OS, etc.)
    gsettings set org.gnome.system.proxy mode 'manual'
    gsettings set org.gnome.system.proxy.socks host '127.0.0.1'
    gsettings set org.gnome.system.proxy.socks port ${LOCAL_PORT}
    gsettings set org.gnome.system.proxy ignore-hosts "['localhost', '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '::1']"
    PROXY_ENABLED="GNOME"
}

enable_proxy_linux_kde() {
    # KDE Plasma
    kwriteconfig5 --file kioslaverc --group "Proxy Settings" --key ProxyType 1
    kwriteconfig5 --file kioslaverc --group "Proxy Settings" --key socksProxy "socks://127.0.0.1:${LOCAL_PORT}"
    kwriteconfig5 --file kioslaverc --group "Proxy Settings" --key NoProxyFor "localhost,127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    # Notify KDE to reload
    dbus-send --type=signal /KIO/Scheduler org.kde.KIO.Scheduler.reparseSlaveConfiguration string:'' 2>/dev/null || true
    PROXY_ENABLED="KDE"
}

enable_proxy_linux_env() {
    # Fallback: set environment variables via profile
    local PROFILE="$HOME/.profile"
    local MARKER="# speedtest-tunnel proxy"
    # Remove old entries
    sed -i "/${MARKER}/d" "$PROFILE" 2>/dev/null || true
    # Add new
    echo "export all_proxy=socks5://127.0.0.1:${LOCAL_PORT} ${MARKER}" >> "$PROFILE"
    echo "export ALL_PROXY=socks5://127.0.0.1:${LOCAL_PORT} ${MARKER}" >> "$PROFILE"
    echo "export http_proxy=socks5://127.0.0.1:${LOCAL_PORT} ${MARKER}" >> "$PROFILE"
    echo "export https_proxy=socks5://127.0.0.1:${LOCAL_PORT} ${MARKER}" >> "$PROFILE"
    echo "export no_proxy=localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 ${MARKER}" >> "$PROFILE"
    # Apply to current shell
    export all_proxy="socks5://127.0.0.1:${LOCAL_PORT}"
    export ALL_PROXY="socks5://127.0.0.1:${LOCAL_PORT}"
    export http_proxy="socks5://127.0.0.1:${LOCAL_PORT}"
    export https_proxy="socks5://127.0.0.1:${LOCAL_PORT}"
    PROXY_ENABLED="env vars (~/.profile)"
}

if [[ "$OS" == "Darwin" ]]; then
    enable_proxy_macos || echo "  [WARN] Could not detect active network interface"
elif [[ "$OS" == "Linux" ]]; then
    if command -v gsettings &>/dev/null && gsettings get org.gnome.system.proxy mode &>/dev/null; then
        enable_proxy_linux_gnome
    elif command -v kwriteconfig5 &>/dev/null; then
        enable_proxy_linux_kde
    else
        enable_proxy_linux_env
    fi
fi

# ──────────────────────────────────────
# Create stop script (OS-aware)
# ──────────────────────────────────────
cat > "${DIR}/stop.sh" <<'STOPSCRIPT'
#!/bin/bash
pkill -f "client.py.*--server" 2>/dev/null && echo "[OK] Client stopped" || echo "Not running"

OS="$(uname)"
if [[ "$OS" == "Darwin" ]]; then
    for IFACE in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN" "Thunderbolt Ethernet"; do
        STATE=$(networksetup -getsocksfirewallproxy "$IFACE" 2>/dev/null | grep "^Enabled" | awk '{print $2}')
        if [ "$STATE" = "Yes" ]; then
            networksetup -setsocksfirewallproxystate "$IFACE" off
            echo "[OK] Proxy disabled on ${IFACE}"
        fi
    done
elif [[ "$OS" == "Linux" ]]; then
    # GNOME
    if command -v gsettings &>/dev/null && gsettings get org.gnome.system.proxy mode &>/dev/null 2>&1; then
        gsettings set org.gnome.system.proxy mode 'none'
        echo "[OK] GNOME proxy disabled"
    fi
    # KDE
    if command -v kwriteconfig5 &>/dev/null; then
        kwriteconfig5 --file kioslaverc --group "Proxy Settings" --key ProxyType 0
        dbus-send --type=signal /KIO/Scheduler org.kde.KIO.Scheduler.reparseSlaveConfiguration string:'' 2>/dev/null || true
        echo "[OK] KDE proxy disabled"
    fi
    # Environment variables
    PROFILE="$HOME/.profile"
    if grep -q "speedtest-tunnel proxy" "$PROFILE" 2>/dev/null; then
        sed -i '/# speedtest-tunnel proxy/d' "$PROFILE"
        unset all_proxy ALL_PROXY http_proxy https_proxy no_proxy
        echo "[OK] Env proxy removed from ~/.profile (restart shell to take effect)"
    fi
fi
STOPSCRIPT
chmod +x "${DIR}/stop.sh"

# ──────────────────────────────────────
# Done
# ──────────────────────────────────────
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
