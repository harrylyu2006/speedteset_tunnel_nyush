# SpeedTest Tunnel

[中文文档 / Chinese Documentation](https://www.notion.so/NYU-Shanghai-Speedtest-Tunnel-32d05cf0990b809da0bdd2add1159509?source=copy_link)

**Designed for NYU Shanghai campus network.** Bypass QoS throttling by disguising traffic as Ookla speedtest downloads.

> NYUSH campus network throttles regular traffic to ~30 Mbps while whitelisting Ookla speedtest requests at full speed (~200+ Mbps). This tool exploits that DPI rule to tunnel all your traffic through the speedtest whitelist.

## Important Notes

- **VPS required**: You need a VPS as the tunnel endpoint
- **Port 8080**: The DPI rule matches traffic on port 8080 — server must use this port
- **Zero dependencies**: Pure Python 3, no pip install needed
- **HTTPS safe**: Tunnel carries raw TCP, HTTPS encryption is preserved end-to-end

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

### Client — macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main/install_client.sh | bash
```

### Client — Windows

Download `SpeedTestTunnel.exe` from [Releases](https://github.com/harrylyu2006/speedteset_tunnel_nyush/releases/latest), double-click to run. No Python needed.

Two proxy modes:
- **System Proxy** — auto-configures Windows proxy, works for browsers
- **SOCKS5 only** — use with [SocksCap64](https://www.sockscap64.com) for any app (see below)

---

## Using SocksCap64 for all apps (Windows)

System Proxy mode only covers browsers. To route **any app** (games, Steam, Discord, etc.) through the tunnel, use [SocksCap64](https://www.sockscap64.com):

### Setup

1. Download and install [SocksCap64](https://www.sockscap64.com/sockscap-64-free-download/)
2. Open SocksCap64, click the **gear icon** (settings) in the top right
3. Set the proxy:
   - **Proxy address**: `127.0.0.1`
   - **Proxy port**: `1080`
   - **Proxy type**: `SOCKS5`
4. Click **Save**

### Add apps

1. Click the **"+"** button to add a program
2. Browse to the `.exe` of the app you want to proxy (e.g. `steam.exe`, `Discord.exe`)
3. **Right-click** the added app → **Run** (or double-click) to launch it through the tunnel

### Tips

- Apps launched through SocksCap64 will use the tunnel; apps launched normally won't
- You can drag-and-drop `.exe` files into SocksCap64
- Create a "Games" group to organize multiple apps
- For **Steam**: add `steam.exe`, then all games launched from Steam will also use the tunnel
- First connect the tunnel (GUI or CLI), **then** launch apps through SocksCap64

---

### Stop tunnel

```bash
# macOS / Linux
~/.speedtest-tunnel/stop.sh

# Windows: click Disconnect in GUI, or:
~\.speedtest-tunnel\stop.ps1
```

### Uninstall

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main/uninstall.sh | bash

# Windows
~\.speedtest-tunnel\uninstall.ps1
```

---

## What the one-click scripts do

**Server (`install_server.sh`)**:
1. Downloads `server.py` to `/opt/speedtest-tunnel/`
2. Prompts for port and password
3. Creates systemd service (auto-start on reboot)
4. Opens firewall port

**Client (`install_client.sh`)**:
1. Clones repo to `~/.speedtest-tunnel/`
2. Prompts for VPS IP, port, and password
3. Starts SOCKS5 proxy in background
4. Enables system-wide proxy

**Windows GUI (`SpeedTestTunnel.exe`)**:
1. Enter server info, click Connect
2. System Proxy mode: auto-configures Windows proxy via PAC
3. SOCKS5 mode: pair with SocksCap64 for per-app proxying

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
| `client.py` | Local | SOCKS5 proxy client (CLI) |
| `client_gui.py` | Local | Windows GUI client |
| `install_server.sh` | VPS | One-line server deploy |
| `install_client.sh` | Local | One-line client deploy (macOS/Linux) |
| `install_client.ps1` | Local | One-line client deploy (Windows PowerShell) |
| `uninstall.sh` | Both | Remove everything (client, server, proxy settings) |

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
