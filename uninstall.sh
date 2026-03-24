#!/bin/bash
# SpeedTest Tunnel — Uninstall (client + server)
# Usage: curl -fsSL https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main/uninstall.sh | bash
#   or:  ~/.speedtest-tunnel/uninstall.sh

OS="$(uname)"
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  SpeedTest Tunnel — Uninstall        ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ──────────────────────────────────────
# 1. Stop client
# ──────────────────────────────────────
if pkill -f "client.py.*--server" 2>/dev/null; then
    echo "  [OK] Client stopped"
fi

# ──────────────────────────────────────
# 2. Disable system proxy
# ──────────────────────────────────────
if [[ "$OS" == "Darwin" ]]; then
    for IFACE in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN" "Thunderbolt Ethernet"; do
        STATE=$(networksetup -getsocksfirewallproxy "$IFACE" 2>/dev/null | grep "^Enabled" | awk '{print $2}')
        if [ "$STATE" = "Yes" ]; then
            networksetup -setsocksfirewallproxystate "$IFACE" off
            echo "  [OK] Proxy disabled on ${IFACE}"
        fi
    done
elif [[ "$OS" == "Linux" ]]; then
    # GNOME
    if command -v gsettings &>/dev/null && gsettings get org.gnome.system.proxy mode &>/dev/null 2>&1; then
        CURRENT=$(gsettings get org.gnome.system.proxy mode 2>/dev/null)
        if [ "$CURRENT" = "'manual'" ]; then
            gsettings set org.gnome.system.proxy mode 'none'
            echo "  [OK] GNOME proxy disabled"
        fi
    fi
    # KDE
    if command -v kwriteconfig5 &>/dev/null; then
        TYPE=$(kwriteconfig5 --file kioslaverc --group "Proxy Settings" --key ProxyType 2>/dev/null)
        if [ "$TYPE" = "1" ]; then
            kwriteconfig5 --file kioslaverc --group "Proxy Settings" --key ProxyType 0
            dbus-send --type=signal /KIO/Scheduler org.kde.KIO.Scheduler.reparseSlaveConfiguration string:'' 2>/dev/null || true
            echo "  [OK] KDE proxy disabled"
        fi
    fi
    # Env vars
    if grep -q "# speedtest-tunnel proxy" "$HOME/.profile" 2>/dev/null; then
        sed -i '/# speedtest-tunnel proxy/d' "$HOME/.profile"
        echo "  [OK] Env proxy removed from ~/.profile"
    fi
fi

# ──────────────────────────────────────
# 3. Remove client files
# ──────────────────────────────────────
if [ -d "$HOME/.speedtest-tunnel" ]; then
    rm -rf "$HOME/.speedtest-tunnel"
    echo "  [OK] Removed ~/.speedtest-tunnel"
fi

# ──────────────────────────────────────
# 4. Remove server (if installed)
# ──────────────────────────────────────
if [ -f "/etc/systemd/system/speedtest-tunnel.service" ]; then
    echo "  Server installation detected, removing..."
    sudo systemctl stop speedtest-tunnel 2>/dev/null || true
    sudo systemctl disable speedtest-tunnel 2>/dev/null || true
    sudo rm -f /etc/systemd/system/speedtest-tunnel.service
    sudo systemctl daemon-reload 2>/dev/null || true
    echo "  [OK] Systemd service removed"
fi

if [ -d "/opt/speedtest-tunnel" ]; then
    sudo rm -rf /opt/speedtest-tunnel
    echo "  [OK] Removed /opt/speedtest-tunnel"
fi

# ──────────────────────────────────────
# 5. Clean up temp files
# ──────────────────────────────────────
rm -f /tmp/speedtest-tunnel-client.log

echo ""
echo "  Uninstall complete."
echo ""
