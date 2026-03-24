@echo off
REM SpeedTest Tunnel — Build Windows EXE
REM Run this on a Windows machine with Python installed
REM Output: dist\SpeedTestTunnel.exe

echo.
echo  Building SpeedTest Tunnel EXE...
echo.

REM Install PyInstaller if needed
pip install pyinstaller >nul 2>&1

REM Build
pyinstaller ^
    --onefile ^
    --windowed ^
    --name SpeedTestTunnel ^
    client_gui.py

echo.
if exist dist\SpeedTestTunnel.exe (
    echo  [OK] Built: dist\SpeedTestTunnel.exe
    echo  Double-click to run. No terminal needed.
) else (
    echo  [FAIL] Build failed. Check output above.
)
echo.
pause
