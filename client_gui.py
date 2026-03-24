"""
SpeedTest Tunnel — Windows GUI Client
Double-click to run. No terminal needed.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import subprocess
import sys
import os
import signal


class TunnelGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SpeedTest Tunnel")
        self.root.geometry("380x320")
        self.root.resizable(False, False)
        self.proc = None

        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 380) // 2
        y = (self.root.winfo_screenheight() - 320) // 2
        self.root.geometry(f"+{x}+{y}")

        self._build_ui()
        self._load_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="SpeedTest Tunnel", font=("", 16, "bold")).pack(pady=(0, 15))

        # Server IP
        row1 = ttk.Frame(frame)
        row1.pack(fill="x", pady=3)
        ttk.Label(row1, text="Server IP:", width=12).pack(side="left")
        self.ip_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.ip_var, width=25).pack(side="left", fill="x", expand=True)

        # Port
        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=3)
        ttk.Label(row2, text="Port:", width=12).pack(side="left")
        self.port_var = tk.StringVar(value="8080")
        ttk.Entry(row2, textvariable=self.port_var, width=25).pack(side="left", fill="x", expand=True)

        # Password
        row3 = ttk.Frame(frame)
        row3.pack(fill="x", pady=3)
        ttk.Label(row3, text="Password:", width=12).pack(side="left")
        self.pass_var = tk.StringVar()
        ttk.Entry(row3, textvariable=self.pass_var, width=25).pack(side="left", fill="x", expand=True)

        # Local port
        row4 = ttk.Frame(frame)
        row4.pack(fill="x", pady=3)
        ttk.Label(row4, text="Local port:", width=12).pack(side="left")
        self.lport_var = tk.StringVar(value="1080")
        ttk.Entry(row4, textvariable=self.lport_var, width=25).pack(side="left", fill="x", expand=True)

        # System proxy checkbox
        self.proxy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Enable system proxy", variable=self.proxy_var).pack(pady=5)

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)
        self.connect_btn = ttk.Button(btn_frame, text="Connect", command=self._connect, width=15)
        self.connect_btn.pack(side="left", padx=5)
        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect", command=self._disconnect, width=15, state="disabled")
        self.disconnect_btn.pack(side="left", padx=5)

        # Status
        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(frame, textvariable=self.status_var, foreground="gray")
        self.status_label.pack()

    def _config_path(self):
        return os.path.join(os.path.expanduser("~"), ".speedtest-tunnel", "gui_config.txt")

    def _save_config(self):
        path = self._config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(f"{self.ip_var.get()}\n{self.port_var.get()}\n{self.pass_var.get()}\n{self.lport_var.get()}\n")

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

    def _set_proxy(self, enable: bool):
        """Set Windows system SOCKS proxy via registry."""
        if sys.platform != "win32":
            return
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                                0, winreg.KEY_WRITE)
            if enable:
                local_port = self.lport_var.get()
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"socks=127.0.0.1:{local_port}")
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                                  "localhost;127.*;10.*;192.168.*;<local>")
            else:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)

            # Notify Windows
            import ctypes
            internet = ctypes.windll.wininet
            internet.InternetSetOptionW(0, 39, 0, 0)
            internet.InternetSetOptionW(0, 37, 0, 0)
        except Exception:
            pass

    def _connect(self):
        ip = self.ip_var.get().strip()
        port = self.port_var.get().strip()
        password = self.pass_var.get().strip()
        lport = self.lport_var.get().strip()

        if not ip:
            messagebox.showerror("Error", "Server IP is required")
            return
        if not password:
            messagebox.showerror("Error", "Password is required")
            return

        self._save_config()
        self.connect_btn.config(state="disabled")
        self.status_var.set("Connecting...")
        self.status_label.config(foreground="orange")

        def run():
            try:
                # Find client.py
                if getattr(sys, 'frozen', False):
                    # Running as exe: client.py is bundled
                    base = sys._MEIPASS
                else:
                    base = os.path.dirname(os.path.abspath(__file__))
                client_py = os.path.join(base, "client.py")

                self.proc = subprocess.Popen(
                    [sys.executable, client_py,
                     "--server", ip,
                     "--server-port", port,
                     "--port", lport,
                     "--password", password],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )

                # Wait a moment to check if it crashes
                import time
                time.sleep(2)
                if self.proc.poll() is not None:
                    stderr = self.proc.stderr.read().decode()
                    self.root.after(0, lambda: self._on_connect_fail(stderr))
                    return

                # Enable proxy
                if self.proxy_var.get():
                    self._set_proxy(True)

                self.root.after(0, self._on_connected)
            except Exception as e:
                self.root.after(0, lambda: self._on_connect_fail(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _on_connected(self):
        self.status_var.set("Connected")
        self.status_label.config(foreground="green")
        self.disconnect_btn.config(state="normal")

    def _on_connect_fail(self, err):
        self.status_var.set("Failed")
        self.status_label.config(foreground="red")
        self.connect_btn.config(state="normal")
        messagebox.showerror("Connection Failed", err or "Unknown error")

    def _disconnect(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None

        if self.proxy_var.get():
            self._set_proxy(False)

        self.status_var.set("Disconnected")
        self.status_label.config(foreground="gray")
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")

    def _on_close(self):
        self._disconnect()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    TunnelGUI().run()
