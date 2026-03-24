#!/bin/bash
# Stop tunnel client and disable system proxy

echo "Stopping SpeedTest Tunnel client..."

# Kill client process
pkill -f "client.py.*--server" 2>/dev/null && echo "[OK] Client stopped" || echo "Client not running"

# Disable system proxy
for IFACE in "Wi-Fi" "Ethernet"; do
    STATE=$(networksetup -getsocksfirewallproxy "$IFACE" 2>/dev/null | grep "^Enabled" | awk '{print $2}')
    if [ "$STATE" = "Yes" ]; then
        networksetup -setsocksfirewallproxystate "$IFACE" off
        echo "[OK] System proxy disabled on ${IFACE}"
    fi
done

echo "Done."
