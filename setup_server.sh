#!/bin/bash
# SpeedTest Tunnel - Server Setup (run on VPS)
# Usage: bash setup_server.sh

set -e

PORT=8080
SERVICE_NAME="speedtest-tunnel"
INSTALL_DIR="/opt/speedtest-tunnel"

echo "========================================"
echo "  SpeedTest Tunnel - Server Setup"
echo "========================================"
echo ""

# 1. Get password
printf "Set tunnel password: " > /dev/tty
read -s PASSWORD < /dev/tty
echo "" > /dev/tty
if [ -z "$PASSWORD" ]; then
    echo "Error: password cannot be empty"
    exit 1
fi
printf "Confirm password: " > /dev/tty
read -s PASSWORD2 < /dev/tty
echo "" > /dev/tty
if [ "$PASSWORD" != "$PASSWORD2" ]; then
    echo "Error: passwords do not match"
    exit 1
fi

# 2. Check Python
if ! command -v python3 &>/dev/null; then
    echo "Installing Python3..."
    if command -v apt &>/dev/null; then
        sudo apt update && sudo apt install -y python3
    elif command -v yum &>/dev/null; then
        sudo yum install -y python3
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3
    else
        echo "Error: cannot install python3, please install manually"
        exit 1
    fi
fi
echo "[OK] Python3: $(python3 --version)"

# 3. Install server.py
echo "Installing to ${INSTALL_DIR}..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp server.py "$INSTALL_DIR/server.py"

# 4. Open firewall port
echo "Configuring firewall (port ${PORT})..."
if command -v ufw &>/dev/null; then
    sudo ufw allow ${PORT}/tcp 2>/dev/null || true
elif command -v firewall-cmd &>/dev/null; then
    sudo firewall-cmd --permanent --add-port=${PORT}/tcp 2>/dev/null || true
    sudo firewall-cmd --reload 2>/dev/null || true
fi
# Also try iptables directly
sudo iptables -C INPUT -p tcp --dport ${PORT} -j ACCEPT 2>/dev/null || \
    sudo iptables -A INPUT -p tcp --dport ${PORT} -j ACCEPT 2>/dev/null || true
echo "[OK] Firewall configured"

# 5. Save password to file (avoids shell quoting issues in systemd)
sudo tee "${INSTALL_DIR}/password" > /dev/null <<< "$PASSWORD"
sudo chmod 600 "${INSTALL_DIR}/password"

sudo tee "${INSTALL_DIR}/start.sh" > /dev/null <<'WRAPPER'
#!/bin/bash
PASSWORD=$(cat /opt/speedtest-tunnel/password)
exec /usr/bin/python3 /opt/speedtest-tunnel/server.py --port 8080 --password "$PASSWORD"
WRAPPER
sudo chmod 700 "${INSTALL_DIR}/start.sh"

# 6. Create systemd service
echo "Creating systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<'SERVICEFILE'
[Unit]
Description=SpeedTest Tunnel Server
After=network.target

[Service]
Type=simple
ExecStart=/opt/speedtest-tunnel/start.sh
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEFILE

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

# 7. Verify
sleep 2
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo "[OK] Service running"
else
    echo "[FAIL] Service not running, check: journalctl -u ${SERVICE_NAME}"
    exit 1
fi

# 8. Get server IP
SERVER_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "========================================"
echo "  Server ready!"
echo "========================================"
echo ""
echo "  IP:       ${SERVER_IP}"
echo "  Port:     ${PORT}"
echo "  Password: (the one you just set)"
echo ""
echo "  On your local machine, run:"
echo "    python3 client.py --server ${SERVER_IP} --password 'YOUR_PASSWORD'"
echo ""
echo "  Manage service:"
echo "    sudo systemctl status ${SERVICE_NAME}"
echo "    sudo systemctl restart ${SERVICE_NAME}"
echo "    sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
