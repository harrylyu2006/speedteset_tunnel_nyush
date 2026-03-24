"""
SpeedTest Tunnel — Windows GUI Client
Double-click to run. No terminal needed.
Runs the SOCKS5 proxy in-process (no subprocess, no separate Python needed).
Supports: System Proxy (PAC) and TUN mode (via tun2socks).
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import asyncio
import hashlib
import struct
import random
import time
import sys
import os
import subprocess
import platform
import urllib.request
import zipfile
import shutil


# ── Tunnel client logic (imported inline to work in exe) ──

SPEEDTEST_REQUEST_TEMPLATE = (
    "GET /speedtest/random{size}x{size}.jpg?x={timestamp}.{bump} HTTP/1.1\r\n"
    "Host: {host}\r\n"
    "User-Agent: Mozilla/5.0 (compatible; speedtest-cli)\r\n"
    "Cache-Control: no-cache\r\n"
    "Connection: keep-alive\r\n"
    "Accept: */*\r\n"
    "X-Speedtest-Token: {auth}\r\n"
    "X-Speedtest-Target: {target}\r\n"
    "\r\n"
)
SIZES = [3000, 3500, 4000]


def make_auth_token(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()[:32]


async def _relay(src, dst, done: asyncio.Event):
    try:
        while not done.is_set():
            try:
                data = await asyncio.wait_for(src.read(131072), timeout=600)
            except asyncio.TimeoutError:
                break
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionResetError, ConnectionAbortedError,
            BrokenPipeError, asyncio.CancelledError, OSError):
        pass
    finally:
        done.set()
        try:
            if dst.can_write_eof():
                dst.write_eof()
        except (OSError, AttributeError):
            pass


async def _handle_socks5(reader, writer, server_host, server_port, password, sem):
    remote_writer = None
    async with sem:
        try:
            header = await asyncio.wait_for(reader.readexactly(2), timeout=10)
            ver, nmethods = struct.unpack("!BB", header)
            if ver != 5:
                return
            await reader.readexactly(nmethods)
            writer.write(struct.pack("!BB", 5, 0))
            await writer.drain()

            req_header = await asyncio.wait_for(reader.readexactly(4), timeout=10)
            ver, cmd, _, atyp = struct.unpack("!BBBB", req_header)
            if cmd != 1:
                writer.write(struct.pack("!BBBBIH", 5, 7, 0, 1, 0, 0))
                await writer.drain()
                return

            if atyp == 1:
                raw = await reader.readexactly(4)
                host = ".".join(str(b) for b in raw)
            elif atyp == 3:
                dlen = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(dlen)).decode()
            elif atyp == 4:
                raw = await reader.readexactly(16)
                host = ":".join(f"{raw[i]:02x}{raw[i+1]:02x}" for i in range(0, 16, 2))
            else:
                writer.write(struct.pack("!BBBBIH", 5, 8, 0, 1, 0, 0))
                await writer.drain()
                return

            port = struct.unpack("!H", await reader.readexactly(2))[0]

            for attempt in range(2):
                try:
                    rr, remote_writer = await asyncio.wait_for(
                        asyncio.open_connection(server_host, server_port), timeout=10)
                    break
                except Exception:
                    if attempt == 1:
                        writer.write(struct.pack("!BBBBIH", 5, 5, 0, 1, 0, 0))
                        await writer.drain()
                        return
                    await asyncio.sleep(0.5)

            req = SPEEDTEST_REQUEST_TEMPLATE.format(
                size=random.choice(SIZES), timestamp=int(time.time() * 1000),
                bump=random.randint(0, 99), host=server_host,
                auth=make_auth_token(password), target=f"{host}:{port}")
            remote_writer.write(req.encode())
            await remote_writer.drain()

            while True:
                line = await asyncio.wait_for(rr.readline(), timeout=10)
                if line in (b"\r\n", b"\n", b""):
                    break
                resp = line.decode("utf-8", errors="ignore").strip()
                if resp.startswith("HTTP/") and "200" not in resp:
                    writer.write(struct.pack("!BBBBIH", 5, 5, 0, 1, 0, 0))
                    await writer.drain()
                    return

            writer.write(struct.pack("!BBBBIH", 5, 0, 0, 1, 0, 0))
            await writer.drain()

            done = asyncio.Event()
            await asyncio.gather(_relay(reader, remote_writer, done),
                                 _relay(rr, writer, done))
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, Exception):
            pass
        finally:
            for w in (remote_writer, writer):
                if w:
                    try:
                        w.close()
                    except Exception:
                        pass


async def run_tunnel(server_host, server_port, password, local_port, stop_event):
    sem = asyncio.Semaphore(256)
    srv = await asyncio.start_server(
        lambda r, w: _handle_socks5(r, w, server_host, server_port, password, sem),
        "127.0.0.1", local_port)
    try:
        while not stop_event.is_set():
            await asyncio.sleep(0.3)
    finally:
        srv.close()
        await srv.wait_closed()


# ── PAC file server ──

def _build_pac(socks_port):
    return f"""function FindProxyForURL(url, host) {{
    if (isPlainHostName(host) ||
        shExpMatch(host, "*.local") ||
        isInNet(host, "127.0.0.0", "255.0.0.0") ||
        isInNet(host, "10.0.0.0", "255.0.0.0") ||
        isInNet(host, "172.16.0.0", "255.240.0.0") ||
        isInNet(host, "192.168.0.0", "255.255.0.0")) {{
        return "DIRECT";
    }}
    return "SOCKS5 127.0.0.1:{socks_port}; SOCKS 127.0.0.1:{socks_port}; DIRECT";
}}"""


async def run_pac_server(socks_port, pac_port, stop_event):
    pac_content = _build_pac(socks_port)

    async def handle(reader, writer):
        try:
            await asyncio.wait_for(reader.read(4096), timeout=5)
            resp = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: application/x-ns-proxy-autoconfig\r\n"
                f"Content-Length: {len(pac_content)}\r\n"
                f"Connection: close\r\n\r\n"
                f"{pac_content}"
            )
            writer.write(resp.encode())
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    srv = await asyncio.start_server(handle, "127.0.0.1", pac_port)
    try:
        while not stop_event.is_set():
            await asyncio.sleep(0.3)
    finally:
        srv.close()
        await srv.wait_closed()


# ── Windows proxy via PAC ──

def set_proxy_pac(enable: bool, pac_port: int = 10801):
    if sys.platform != "win32":
        return
    try:
        import winreg
        import ctypes
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                             0, winreg.KEY_WRITE)
        if enable:
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ,
                              f"http://127.0.0.1:{pac_port}/proxy.pac")
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        else:
            try:
                winreg.DeleteValue(key, "AutoConfigURL")
            except FileNotFoundError:
                pass
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        internet = ctypes.windll.wininet
        internet.InternetSetOptionW(0, 39, 0, 0)
        internet.InternetSetOptionW(0, 37, 0, 0)
    except Exception:
        pass


# ── TUN mode via tun2socks ──

TUN2SOCKS_VERSION = "v2.5.2"
TUN_GATEWAY = "198.18.0.1"
TUN_ADDR = "198.18.0.2"
TUN_DNS = "8.8.8.8"


def _tun2socks_dir():
    return os.path.join(os.path.expanduser("~"), ".speedtest-tunnel", "tun2socks")


def _tun2socks_exe():
    d = _tun2socks_dir()
    if sys.platform == "win32":
        return os.path.join(d, "tun2socks.exe")
    return os.path.join(d, "tun2socks")


def _download_tun2socks(status_cb=None, socks_port=None):
    """Download tun2socks binary. Uses local SOCKS5 proxy if available."""
    exe = _tun2socks_exe()
    if os.path.exists(exe):
        return exe

    d = _tun2socks_dir()
    os.makedirs(d, exist_ok=True)

    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        arch = "amd64" if "64" in machine or machine == "amd64" else "386"
        filename = f"tun2socks-windows-{arch}.zip"
    elif system == "darwin":
        arch = "arm64" if machine == "arm64" else "amd64"
        filename = f"tun2socks-darwin-{arch}.zip"
    else:
        arch = "amd64" if "x86_64" in machine or "amd64" in machine else "arm64"
        filename = f"tun2socks-linux-{arch}.zip"

    url = f"https://github.com/xjasonlyu/tun2socks/releases/download/{TUN2SOCKS_VERSION}/{filename}"

    if status_cb:
        status_cb("Downloading tun2socks (via tunnel)...")

    zip_path = os.path.join(d, filename)

    # Download through our own SOCKS5 tunnel for speed
    if socks_port:
        import socks as _socks
        import socket
        try:
            # Try using PySocks if available
            orig = socket.socket
            _socks.set_default_proxy(_socks.SOCKS5, "127.0.0.1", socks_port)
            socket.socket = _socks.socksocket
            urllib.request.urlretrieve(url, zip_path)
            socket.socket = orig
        except ImportError:
            # PySocks not available, use curl fallback
            result = subprocess.run(
                ["curl", "-L", "-o", zip_path, "--socks5-hostname",
                 f"127.0.0.1:{socks_port}", "-m", "60", url],
                capture_output=True)
            if result.returncode != 0:
                # Last resort: direct download
                urllib.request.urlretrieve(url, zip_path)
    else:
        urllib.request.urlretrieve(url, zip_path)

    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            if "tun2socks" in member.lower():
                extracted = zf.extract(member, d)
                # Move to standard path
                if extracted != exe:
                    shutil.move(extracted, exe)
                break

    os.remove(zip_path)

    if sys.platform != "win32":
        os.chmod(exe, 0o755)

    return exe


class TunManager:
    """Manage tun2socks process and system routes."""

    def __init__(self):
        self.proc = None
        self.original_gateway = None
        self.server_ip = None

    def start(self, socks_port: int, server_ip: str, status_cb=None):
        exe = _download_tun2socks(status_cb, socks_port=socks_port)
        self.server_ip = server_ip

        if sys.platform == "win32":
            self._start_windows(exe, socks_port)
        else:
            raise RuntimeError("TUN mode currently supports Windows only in GUI")

    def _start_windows(self, exe, socks_port):
        # Get default gateway before we change routes
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1).NextHop"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self.original_gateway = result.stdout.strip()
        except Exception:
            self.original_gateway = None

        # Start tun2socks
        self.proc = subprocess.Popen(
            [exe, "-device", "tun://tun0", "-proxy", f"socks5://127.0.0.1:{socks_port}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW)

        time.sleep(3)  # Wait for TUN adapter to come up

        if self.proc.poll() is not None:
            stderr = self.proc.stderr.read().decode()
            raise RuntimeError(f"tun2socks failed: {stderr}")

        # Configure TUN adapter IP
        subprocess.run(
            ["netsh", "interface", "ip", "set", "address",
             "tun0", "static", TUN_ADDR, "255.255.255.0", TUN_GATEWAY],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

        # Route VPS IP through original gateway (prevent loop)
        if self.original_gateway and self.server_ip:
            subprocess.run(
                ["route", "add", self.server_ip, "mask", "255.255.255.255", self.original_gateway],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

        # Route all traffic through TUN
        subprocess.run(
            ["route", "add", "0.0.0.0", "mask", "128.0.0.0", TUN_GATEWAY, "metric", "5"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(
            ["route", "add", "128.0.0.0", "mask", "128.0.0.0", TUN_GATEWAY, "metric", "5"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

        # Set DNS
        subprocess.run(
            ["netsh", "interface", "ip", "set", "dns", "tun0", "static", TUN_DNS],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

    def stop(self):
        if sys.platform == "win32":
            self._stop_windows()

    def _stop_windows(self):
        # Remove routes
        subprocess.run(["route", "delete", "0.0.0.0", "mask", "128.0.0.0"],
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run(["route", "delete", "128.0.0.0", "mask", "128.0.0.0"],
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if self.server_ip:
            subprocess.run(["route", "delete", self.server_ip],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

        # Kill tun2socks
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


# ── GUI ──

class TunnelGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SpeedTest Tunnel")
        self.root.geometry("380x380")
        self.root.resizable(False, False)
        self.tunnel_thread = None
        self.stop_event = threading.Event()
        self.loop = None
        self.pac_port = 10801
        self.tun_manager = TunManager()

        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 380) // 2
        y = (self.root.winfo_screenheight() - 380) // 2
        self.root.geometry(f"+{x}+{y}")

        self._build_ui()
        self._load_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="SpeedTest Tunnel", font=("", 16, "bold")).pack(pady=(0, 15))

        for label, var_name, default in [
            ("Server IP:", "ip_var", ""),
            ("Port:", "port_var", "8080"),
            ("Password:", "pass_var", ""),
            ("Local port:", "lport_var", "1080"),
        ]:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=12).pack(side="left")
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            ttk.Entry(row, textvariable=var, width=25).pack(side="left", fill="x", expand=True)

        # Proxy mode selection
        mode_frame = ttk.LabelFrame(frame, text="Proxy Mode", padding=5)
        mode_frame.pack(fill="x", pady=8)

        self.mode_var = tk.StringVar(value="pac")
        ttk.Radiobutton(mode_frame, text="System Proxy (browser only)",
                        variable=self.mode_var, value="pac").pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="TUN Mode (all apps, requires admin)",
                        variable=self.mode_var, value="tun").pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="No proxy (SOCKS5 only)",
                        variable=self.mode_var, value="none").pack(anchor="w")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=8)
        self.connect_btn = ttk.Button(btn_frame, text="Connect", command=self._connect, width=15)
        self.connect_btn.pack(side="left", padx=5)
        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect", command=self._disconnect,
                                         width=15, state="disabled")
        self.disconnect_btn.pack(side="left", padx=5)

        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(frame, textvariable=self.status_var, foreground="gray")
        self.status_label.pack()

    def _config_path(self):
        return os.path.join(os.path.expanduser("~"), ".speedtest-tunnel", "gui_config.txt")

    def _save_config(self):
        path = self._config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(f"{self.ip_var.get()}\n{self.port_var.get()}\n"
                    f"{self.pass_var.get()}\n{self.lport_var.get()}\n"
                    f"{self.mode_var.get()}\n")

    def _load_config(self):
        path = self._config_path()
        if os.path.exists(path):
            with open(path) as f:
                lines = f.read().strip().split("\n")
            if len(lines) >= 4:
                self.ip_var.set(lines[0])
                self.port_var.set(lines[1])
                self.pass_var.set(lines[2])
                self.lport_var.set(lines[3])
            if len(lines) >= 5:
                self.mode_var.set(lines[4])

    def _connect(self):
        ip = self.ip_var.get().strip()
        port = self.port_var.get().strip()
        password = self.pass_var.get().strip()
        lport = self.lport_var.get().strip()
        mode = self.mode_var.get()

        if not ip:
            messagebox.showerror("Error", "Server IP is required")
            return
        if not password:
            messagebox.showerror("Error", "Password is required")
            return

        if self.tunnel_thread and self.tunnel_thread.is_alive():
            self.stop_event.set()
            self.tunnel_thread.join(timeout=3)
            self.tunnel_thread = None

        self._save_config()
        self.connect_btn.config(state="disabled")
        self.status_var.set("Connecting...")
        self.status_label.config(foreground="orange")
        self.stop_event.clear()

        def run():
            try:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)

                stop_async = asyncio.Event()

                async def watch_stop():
                    while not self.stop_event.is_set():
                        await asyncio.sleep(0.3)
                    stop_async.set()

                async def main():
                    tasks = [
                        run_tunnel(ip, int(port), password, int(lport), stop_async),
                        watch_stop(),
                    ]
                    if mode == "pac":
                        tasks.append(run_pac_server(int(lport), self.pac_port, stop_async))
                    await asyncio.gather(*tasks)

                def signal_connected():
                    time.sleep(1.5)
                    if self.stop_event.is_set():
                        return
                    try:
                        if mode == "pac":
                            set_proxy_pac(True, self.pac_port)
                        elif mode == "tun":
                            self.tun_manager.start(int(lport), ip,
                                                   status_cb=lambda s: self.root.after(
                                                       0, lambda: self.status_var.set(s)))
                    except Exception as e:
                        self.root.after(0, lambda: self._on_connect_fail(
                            f"Proxy setup failed: {e}\n\nTUN mode requires running as Administrator."))
                        self.stop_event.set()
                        return
                    self.root.after(0, self._on_connected)

                threading.Thread(target=signal_connected, daemon=True).start()
                self.loop.run_until_complete(main())
            except Exception as e:
                if not self.stop_event.is_set():
                    self.root.after(0, lambda: self._on_connect_fail(str(e)))
            finally:
                if self.loop:
                    self.loop.close()

        self.tunnel_thread = threading.Thread(target=run, daemon=True)
        self.tunnel_thread.start()

    def _on_connected(self):
        mode = self.mode_var.get()
        label = {"pac": "Connected (System Proxy)", "tun": "Connected (TUN)",
                 "none": "Connected (SOCKS5 only)"}
        self.status_var.set(label.get(mode, "Connected"))
        self.status_label.config(foreground="green")
        self.disconnect_btn.config(state="normal")

    def _on_connect_fail(self, err):
        self.status_var.set("Failed")
        self.status_label.config(foreground="red")
        self.connect_btn.config(state="normal")
        messagebox.showerror("Connection Failed", err or "Unknown error")

    def _disconnect(self):
        mode = self.mode_var.get()
        if mode == "pac":
            set_proxy_pac(False, self.pac_port)
        elif mode == "tun":
            self.tun_manager.stop()

        self.stop_event.set()

        def wait_and_update():
            if self.tunnel_thread and self.tunnel_thread.is_alive():
                self.tunnel_thread.join(timeout=3)
            self.tunnel_thread = None
            self.loop = None

        threading.Thread(target=wait_and_update, daemon=True).start()

        self.status_var.set("Disconnected")
        self.status_label.config(foreground="gray")
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")

    def _on_close(self):
        mode = self.mode_var.get()
        if mode == "pac":
            set_proxy_pac(False, self.pac_port)
        elif mode == "tun":
            self.tun_manager.stop()
        self.stop_event.set()
        if self.tunnel_thread and self.tunnel_thread.is_alive():
            self.tunnel_thread.join(timeout=2)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    TunnelGUI().run()
