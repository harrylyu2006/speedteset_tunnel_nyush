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


def generate_clash_config(server_ip, socks_port):
    """Generate Clash proxy config snippet for use with Clash Verge TUN."""
    return f"""# Add to your Clash Verge config (Settings → Profiles → Edit)

proxies:
  - name: "NYUSH-Tunnel"
    type: socks5
    server: 127.0.0.1
    port: {socks_port}

# Add "NYUSH-Tunnel" to your proxy group, e.g.:
# proxy-groups:
#   - name: "Proxy"
#     type: select
#     proxies:
#       - NYUSH-Tunnel
#       - DIRECT

# IMPORTANT: Add this rule BEFORE other rules to prevent loop:
# rules:
#   - IP-CIDR,{server_ip}/32,DIRECT
#   - MATCH,NYUSH-Tunnel
"""


# ── GUI ──

class TunnelGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SpeedTest Tunnel")
        self.root.geometry("720x420")
        self.root.resizable(False, False)
        self.tunnel_thread = None
        self.stop_event = threading.Event()
        self.loop = None
        self.pac_port = 10801

        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 720) // 2
        y = (self.root.winfo_screenheight() - 420) // 2
        self.root.geometry(f"+{x}+{y}")

        self._build_ui()
        self._load_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def log(self, msg):
        """Append a line to the log panel (thread-safe)."""
        ts = time.strftime("%H:%M:%S")
        def _append():
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"[{ts}] {msg}\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(0, _append)

    def _build_ui(self):
        # Left panel: controls
        left = ttk.Frame(self.root, padding=15)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="SpeedTest Tunnel", font=("", 14, "bold")).pack(pady=(0, 10))

        for label, var_name, default in [
            ("Server IP:", "ip_var", ""),
            ("Port:", "port_var", "8080"),
            ("Password:", "pass_var", ""),
            ("Local port:", "lport_var", "1080"),
        ]:
            row = ttk.Frame(left)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=11).pack(side="left")
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            ttk.Entry(row, textvariable=var, width=20).pack(side="left", fill="x", expand=True)

        mode_frame = ttk.LabelFrame(left, text="Proxy Mode", padding=4)
        mode_frame.pack(fill="x", pady=6)
        self.mode_var = tk.StringVar(value="pac")
        for text, val in [("System Proxy (browser)", "pac"),
                          ("SOCKS5 only (for Clash etc.)", "none")]:
            ttk.Radiobutton(mode_frame, text=text, variable=self.mode_var, value=val).pack(anchor="w")
        self.clash_btn = ttk.Button(mode_frame, text="Copy Clash Config",
                                     command=self._copy_clash_config, width=20)
        self.clash_btn.pack(anchor="w", pady=(4, 0))

        btn_frame = ttk.Frame(left)
        btn_frame.pack(pady=8)
        self.connect_btn = ttk.Button(btn_frame, text="Connect", command=self._connect, width=13)
        self.connect_btn.pack(side="left", padx=3)
        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect", command=self._disconnect,
                                         width=13, state="disabled")
        self.disconnect_btn.pack(side="left", padx=3)

        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(left, textvariable=self.status_var, foreground="gray")
        self.status_label.pack()

        # Right panel: log
        right = ttk.LabelFrame(self.root, text="Log", padding=5)
        right.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=10)

        self.log_text = tk.Text(right, width=38, height=22, font=("Consolas", 9),
                                wrap="word", state="disabled", bg="#1e1e1e", fg="#cccccc",
                                insertbackground="#cccccc")
        scrollbar = ttk.Scrollbar(right, orient="vertical", command=self.log_text.yview)
        self.log_text.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

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

    def _copy_clash_config(self):
        ip = self.ip_var.get().strip()
        lport = self.lport_var.get().strip() or "1080"
        if not ip:
            messagebox.showinfo("Clash Config", "Enter VPS IP first, then connect in SOCKS5 mode.")
            return
        config = generate_clash_config(ip, lport)
        self.root.clipboard_clear()
        self.root.clipboard_append(config)
        self.log("Clash config copied to clipboard!")
        self.log("Paste into Clash Verge profile, then enable TUN mode in Clash.")
        messagebox.showinfo("Copied!",
                            "Clash config copied to clipboard.\n\n"
                            "1. Connect here in 'SOCKS5 only' mode\n"
                            "2. Paste config into Clash Verge profile\n"
                            "3. Enable TUN mode in Clash Verge\n\n"
                            f"IMPORTANT: VPS IP {ip} is set to DIRECT to prevent loop.")

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

        self.log(f"Connecting to {ip}:{port}...")
        self.log(f"Mode: {mode}")

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
                    self.log(f"SOCKS5 proxy up on 127.0.0.1:{lport}")
                    try:
                        if mode == "pac":
                            self.log("Setting system proxy (PAC)...")
                            set_proxy_pac(True, self.pac_port)
                            self.log("System proxy enabled")
                    except Exception as e:
                        self.log(f"ERROR: {e}")
                        self.root.after(0, lambda: self._on_connect_fail(
                            f"Proxy setup failed: {e}"))
                        self.stop_event.set()
                        return
                    self.root.after(0, self._on_connected)

                threading.Thread(target=signal_connected, daemon=True).start()
                self.loop.run_until_complete(main())
            except Exception as e:
                self.log(f"ERROR: {e}")
                if not self.stop_event.is_set():
                    self.root.after(0, lambda: self._on_connect_fail(str(e)))
            finally:
                if self.loop:
                    self.loop.close()

        self.tunnel_thread = threading.Thread(target=run, daemon=True)
        self.tunnel_thread.start()

    def _on_connected(self):
        mode = self.mode_var.get()
        label = {"pac": "Connected (System Proxy)", "none": "Connected (SOCKS5 only)"}
        self.status_var.set(label.get(mode, "Connected"))
        self.status_label.config(foreground="green")
        self.disconnect_btn.config(state="normal")
        self.log("Ready. Go browse!")

    def _on_connect_fail(self, err):
        self.status_var.set("Failed")
        self.status_label.config(foreground="red")
        self.connect_btn.config(state="normal")
        messagebox.showerror("Connection Failed", err or "Unknown error")

    def _disconnect(self):
        self.log("Disconnecting...")
        mode = self.mode_var.get()
        if mode == "pac":
            set_proxy_pac(False, self.pac_port)
            self.log("System proxy disabled")

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
        self.log("Disconnected")

    def _on_close(self):
        mode = self.mode_var.get()
        if mode == "pac":
            set_proxy_pac(False, self.pac_port)
        self.stop_event.set()
        if self.tunnel_thread and self.tunnel_thread.is_alive():
            self.tunnel_thread.join(timeout=2)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def _request_admin():
    """Re-launch as admin on Windows if not already elevated."""
    if sys.platform != "win32":
        return
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    # Re-run self as admin
    if getattr(sys, 'frozen', False):
        # Running as exe
        script = sys.executable
    else:
        script = os.path.abspath(__file__)
        # For .py files, run through python
        params = f'"{script}"'
        script = sys.executable

    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", script,
        f'"{os.path.abspath(__file__)}"' if not getattr(sys, 'frozen', False) else "",
        None, 1)
    sys.exit(0)


if __name__ == "__main__":
    _request_admin()
    TunnelGUI().run()
