#!/bin/bash
# SpeedTest Tunnel — One-line server deploy
# Usage: curl -fsSL https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main/install_server.sh | bash
set -e

REPO="https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main"
INSTALL_DIR="/opt/speedtest-tunnel"
SERVICE="speedtest-tunnel"
PORT=8080

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   SpeedTest Tunnel — Server Setup    ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Password
printf "  Set tunnel password: "
read -s PASSWORD
echo ""
if [ -z "$PASSWORD" ]; then echo "  Error: password cannot be empty"; exit 1; fi

# Python check
command -v python3 &>/dev/null || {
    echo "  Installing Python3..."
    (apt-get update && apt-get install -y python3) 2>/dev/null || \
    (yum install -y python3) 2>/dev/null || \
    (dnf install -y python3) 2>/dev/null || \
    { echo "  Error: install python3 manually"; exit 1; }
}
echo "  [OK] Python3 $(python3 --version 2>&1 | awk '{print $2}')"

# Download server.py
echo "  Downloading server.py..."
sudo mkdir -p "$INSTALL_DIR"
sudo curl -fsSL "${REPO}/server.py" -o "${INSTALL_DIR}/server.py"
echo "  [OK] Installed to ${INSTALL_DIR}"

# Firewall
echo "  Opening port ${PORT}..."
if command -v ufw &>/dev/null; then
    sudo ufw allow ${PORT}/tcp 2>/dev/null || true
elif command -v firewall-cmd &>/dev/null; then
    sudo firewall-cmd --permanent --add-port=${PORT}/tcp 2>/dev/null && \
    sudo firewall-cmd --reload 2>/dev/null || true
fi
sudo iptables -C INPUT -p tcp --dport ${PORT} -j ACCEPT 2>/dev/null || \
    sudo iptables -A INPUT -p tcp --dport ${PORT} -j ACCEPT 2>/dev/null || true
echo "  [OK] Firewall configured"

# systemd
echo "  Creating systemd service..."
sudo tee /etc/systemd/system/${SERVICE}.service > /dev/null <<EOF
[Unit]
Description=SpeedTest Tunnel Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/server.py --port ${PORT} --password "${PASSWORD}"
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE} --quiet
sudo systemctl restart ${SERVICE}
sleep 1

if systemctl is-active --quiet ${SERVICE}; then
    echo "  [OK] Service running"
else
    echo "  [FAIL] Check: journalctl -u ${SERVICE}"
    exit 1
fi

SERVER_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║          Server is ready!            ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  IP:   ${SERVER_IP}"
echo "  Port: ${PORT}"
echo ""
echo "  On your local machine, run:"
echo ""
echo "    curl -fsSL ${REPO}/install_client.sh | bash"
echo ""
echo "  Management:"
echo "    sudo systemctl status ${SERVICE}"
echo "    sudo journalctl -u ${SERVICE} -f"
echo ""
