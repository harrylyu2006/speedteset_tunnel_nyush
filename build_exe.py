"""
SpeedTest Tunnel — Build EXE (cross-platform build script)
Run: python build_exe.py
"""

import subprocess
import sys
import os

def main():
    # Install PyInstaller
    print("Installing PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "-q"])

    # Build
    print("Building EXE...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "SpeedTestTunnel",
        "client_gui.py"
    ]
    subprocess.check_call(cmd)

    exe = os.path.join("dist", "SpeedTestTunnel.exe")
    if os.path.exists(exe):
        print(f"\n[OK] Built: {exe}")
        print("Double-click to run. No terminal needed.")
    else:
        print("\n[FAIL] Build failed")

if __name__ == "__main__":
    main()
