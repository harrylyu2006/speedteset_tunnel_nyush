# SpeedTest Tunnel

Bypass campus network QoS by disguising traffic as Ookla speedtest downloads.

## How it works

Campus DPI (Deep Packet Inspection) whitelists HTTP requests matching:
```
GET /speedtest/random{N}x{N}.jpg HTTP/1.1
```
on port 8080. This tool wraps all traffic in this pattern.

## Architecture

```
Browser/App
    ↓ (SOCKS5)
[client.py] local:1080
    ↓ (HTTP disguised as Ookla speedtest)
    ↓ GET /speedtest/random4000x4000.jpg
Campus DPI → sees "speedtest" → no throttle
    ↓
[server.py] vps:8080
    ↓ (raw TCP)
Target website
```

## One-Click Deploy

### Server (run on VPS)

SSH into your VPS, paste this single line:

```bash
curl -fsSL https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main/install_server.sh | bash
```

### Client (run on your Mac / Linux)

Open terminal, paste this single line:

```bash
curl -fsSL https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main/install_client.sh | bash
```

### Stop tunnel

```bash
~/.speedtest-tunnel/stop.sh
```

---

## What the one-click scripts do

**Server (`install_server.sh`)**:
1. Downloads `server.py` to `/opt/speedtest-tunnel/`
2. Prompts for tunnel password
3. Creates systemd service (auto-start on reboot)
4. Opens firewall port 8080

**Client (`install_client.sh`)**:
1. Clones repo to `~/.speedtest-tunnel/`
2. Runs DPI bypass verification test
3. Prompts for VPS IP and password
4. Starts SOCKS5 proxy in background
5. Optionally enables macOS system-wide proxy

## Manual Usage

```bash
# Server (VPS)
python3 server.py --port 8080 --password "your-secret"

# Client (local)
python3 client.py --server YOUR_VPS_IP --password "your-secret"

# Then set SOCKS5 proxy to 127.0.0.1:1080
```

## Files

| File | Where | What |
|------|-------|------|
| `server.py` | VPS | Tunnel server (disguised as Ookla speedtest) |
| `client.py` | Local | SOCKS5 proxy client |
| `install_server.sh` | VPS | One-line server deploy |
| `install_client.sh` | Local | One-line client deploy |
| `test_local.py` | Local | Verify DPI bypass exists on your network |
| `test_e2e.py` | Local | End-to-end functional test |

## Important Notes

- **VPS required**: You need a VPS as the tunnel endpoint
- **Port 8080**: The DPI rule matches traffic on port 8080 — server must use this port
- **Zero dependencies**: Pure Python 3, no pip install needed
- **HTTPS safe**: Tunnel carries raw TCP, HTTPS encryption is preserved end-to-end

## Manage

```bash
# Server (VPS)
sudo systemctl status speedtest-tunnel
sudo systemctl restart speedtest-tunnel
sudo journalctl -u speedtest-tunnel -f

# Client (local)
~/.speedtest-tunnel/stop.sh          # Stop and disable proxy
cat /tmp/speedtest-tunnel-client.log  # View client log
```
