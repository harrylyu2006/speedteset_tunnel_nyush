# SpeedTest Tunnel — Windows Client Install
# Usage:
#   Interactive:  irm https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main/install_client.ps1 | iex
#   With args:    .\install_client.ps1 -Server IP -Port 8080 -Password PASS

param(
    [string]$Server = "",
    [int]$Port = 0,
    [string]$Password = ""
)

$ErrorActionPreference = "Stop"
$REPO = "https://raw.githubusercontent.com/harrylyu2006/speedteset_tunnel_nyush/main"
$DIR = "$env:USERPROFILE\.speedtest-tunnel"
$LOCAL_PORT = 1080

Write-Host ""
Write-Host "  +======================================+" -ForegroundColor Cyan
Write-Host "  |   SpeedTest Tunnel - Client Setup    |" -ForegroundColor Cyan
Write-Host "  +======================================+" -ForegroundColor Cyan
Write-Host ""

# Check Python
$python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Host "  [FAIL] Python not found. Install from https://python.org" -ForegroundColor Red
    exit 1
}
$pyver = & $python.Source --version 2>&1
Write-Host "  [OK] $pyver"

# Download files
if (-not (Test-Path $DIR)) { New-Item -ItemType Directory -Path $DIR -Force | Out-Null }
Write-Host "  Downloading..."
foreach ($f in @("client.py", "server.py")) {
    Invoke-WebRequest -Uri "$REPO/$f" -OutFile "$DIR\$f" -UseBasicParsing
}
Write-Host "  [OK] Installed to $DIR"

# Prompt for missing params
if ([string]::IsNullOrEmpty($Server)) {
    $Server = Read-Host "  VPS IP address"
    if ([string]::IsNullOrEmpty($Server)) { Write-Host "  Error: IP required"; exit 1 }
}

if ($Port -eq 0) {
    $input_port = Read-Host "  VPS port [8080]"
    if ([string]::IsNullOrEmpty($input_port)) { $Port = 8080 } else { $Port = [int]$input_port }
}

if ([string]::IsNullOrEmpty($Password)) {
    $Password = Read-Host "  Tunnel password"
    if ([string]::IsNullOrEmpty($Password)) { Write-Host "  Error: password required"; exit 1 }
}

# Kill existing
Get-Process python*, python3* -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "client\.py.*--port $LOCAL_PORT" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Start client
Write-Host "  Starting tunnel client..."
$pyexe = $python.Source
$proc = Start-Process -FilePath $pyexe -ArgumentList @(
    "$DIR\client.py",
    "--server", $Server,
    "--server-port", $Port,
    "--port", $LOCAL_PORT,
    "--password", $Password
) -WindowStyle Hidden -PassThru -RedirectStandardOutput "$DIR\client.log" -RedirectStandardError "$DIR\client_err.log"

Start-Sleep -Seconds 2
if ($proc.HasExited) {
    Write-Host "  [FAIL] Client crashed:" -ForegroundColor Red
    Get-Content "$DIR\client_err.log" -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "  [OK] Client running (PID: $($proc.Id))"

# Enable system proxy via registry
Write-Host "  Enabling system proxy..."
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
Set-ItemProperty -Path $regPath -Name ProxyEnable -Value 0
# Windows doesn't natively support SOCKS in system proxy, use ProxyServer with socks= prefix
# For full SOCKS support, we set it as a PAC-style or use the override
Set-ItemProperty -Path $regPath -Name ProxyServer -Value "socks=127.0.0.1:$LOCAL_PORT"
Set-ItemProperty -Path $regPath -Name ProxyEnable -Value 1
Set-ItemProperty -Path $regPath -Name ProxyOverride -Value "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.20.*;172.21.*;172.22.*;172.23.*;172.24.*;172.25.*;172.26.*;172.27.*;172.28.*;172.29.*;172.30.*;172.31.*;192.168.*;<local>"

# Notify Windows of proxy change
$signature = @'
[DllImport("wininet.dll", SetLastError=true)]
public static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int lpdwBufferLength);
'@
$type = Add-Type -MemberDefinition $signature -Name WinInet -Namespace Proxy -PassThru
$INTERNET_OPTION_SETTINGS_CHANGED = 39
$INTERNET_OPTION_REFRESH = 37
$type::InternetSetOption([IntPtr]::Zero, $INTERNET_OPTION_SETTINGS_CHANGED, [IntPtr]::Zero, 0) | Out-Null
$type::InternetSetOption([IntPtr]::Zero, $INTERNET_OPTION_REFRESH, [IntPtr]::Zero, 0) | Out-Null

Write-Host "  [OK] System proxy enabled (socks=127.0.0.1:$LOCAL_PORT)" -ForegroundColor Green

# Create stop script
@"
# Stop SpeedTest Tunnel
Get-Process python*, python3* -ErrorAction SilentlyContinue |
    Where-Object { `$_.CommandLine -match "client\.py.*--server" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "[OK] Client stopped"

# Disable system proxy
Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -Name ProxyEnable -Value 0
`$signature = @'
[DllImport("wininet.dll", SetLastError=true)]
public static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int lpdwBufferLength);
'@
`$type = Add-Type -MemberDefinition `$signature -Name WinInet2 -Namespace Proxy2 -PassThru
`$type::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null
`$type::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null
Write-Host "[OK] System proxy disabled"
"@ | Set-Content "$DIR\stop.ps1"

# Create uninstall script
@"
# Uninstall SpeedTest Tunnel
& "`$PSScriptRoot\stop.ps1"
Remove-Item -Recurse -Force "$DIR" -ErrorAction SilentlyContinue
Write-Host "[OK] Uninstalled"
"@ | Set-Content "$DIR\uninstall.ps1"

Write-Host ""
Write-Host "  +======================================+" -ForegroundColor Green
Write-Host "  |              Ready!                  |" -ForegroundColor Green
Write-Host "  +======================================+" -ForegroundColor Green
Write-Host ""
Write-Host "  System proxy ON — go browse."
Write-Host ""
Write-Host "  Stop:      powershell $DIR\stop.ps1"
Write-Host "  Uninstall: powershell $DIR\uninstall.ps1"
Write-Host ""
