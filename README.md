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

## One-Click Setup

### Step 0: Verify DPI bypass works on your network
```bash
python3 test_local.py
```

### Step 1: Deploy server on VPS
```bash
# Copy files to VPS
scp server.py setup_server.sh user@your-vps:~/

# SSH into VPS and run setup
ssh user@your-vps
bash setup_server.sh
```

This will:
- Install as systemd service (auto-start on boot)
- Open firewall port 8080
- Prompt for tunnel password

### Step 2: Run client on your Mac
```bash
bash setup_client.sh
```

This will:
- Test VPS connectivity
- Verify DPI bypass works
- Start SOCKS5 proxy (background)
- Optionally enable system-wide proxy

### Stop tunnel
```bash
bash stop_client.sh
```

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
| `setup_server.sh` | VPS | One-click server install + systemd service |
| `setup_client.sh` | Local | One-click client start + proxy config |
| `stop_client.sh` | Local | Stop client + disable system proxy |
| `test_local.py` | Local | Verify DPI bypass exists on your network |
| `test_e2e.py` | Local | End-to-end functional test |

## Important Notes

- **VPS required**: You need a VPS as the tunnel endpoint
- **Port 8080**: The DPI rule matches traffic on port 8080 — server must use this port
- **Zero dependencies**: Pure Python 3, no pip install needed
- **HTTPS safe**: Tunnel carries raw TCP, HTTPS encryption is preserved end-to-end
- **No payload encryption**: The tunnel itself is not encrypted (campus DPI can see it's a tunnel if they inspect deeply). For extra security, wrap with TLS.

## Manage server

```bash
sudo systemctl status speedtest-tunnel    # Check status
sudo systemctl restart speedtest-tunnel   # Restart
sudo journalctl -u speedtest-tunnel -f    # View logs
```
