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

## Quick Start

### Step 0: Verify DPI bypass works on your network
```bash
python3 test_local.py
```

### Step 1: Deploy server on VPS
```bash
# On your VPS (any provider, any region)
scp server.py user@your-vps:/opt/tunnel/
ssh user@your-vps
python3 /opt/tunnel/server.py --port 8080 --password "your-secret"
```

### Step 2: Run client locally
```bash
python3 client.py --server YOUR_VPS_IP --password "your-secret"
```

### Step 3: Configure system proxy
Set SOCKS5 proxy to `127.0.0.1:1080` in:
- System Preferences → Network → Proxies → SOCKS Proxy
- Or browser extension (SwitchyOmega, FoxyProxy)

### Step 4: Verify speed
```bash
# Should now show higher speed through the tunnel
curl --socks5 127.0.0.1:1080 -o /dev/null -w "%{speed_download}" \
  https://speed.cloudflare.com/__down?bytes=10000000
```

## Important Notes

- **VPS required**: You need a VPS as the tunnel endpoint
- **Port 8080**: The DPI rule matches traffic on port 8080
- **No encryption**: Traffic is NOT encrypted (use with HTTPS sites)
- For encrypted tunnel, consider wrapping with TLS or using this in combination with a VPN
