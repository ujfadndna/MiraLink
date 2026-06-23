param(
    [int]$BackendPort = 8100,
    [int]$SignalPort = 8080,
    [int]$GatewayPort = 8443,
    [string]$UnityPath = "D:\Unity Editor\2022.3.62f3c1\Editor\Unity.exe",
    [switch]$SkipUnityCompile,
    [switch]$SkipCloudAsr,
    [switch]$SkipCloudTts
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$UnityLog = Join-Path $Root "workspace\unity-compile.log"

function Write-Step($Text) {
    Write-Host ""
    Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Test-Port($Port) {
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
}

function Test-HttpJson($Url) {
    try {
        Invoke-RestMethod -Uri $Url -TimeoutSec 3
        return $true
    } catch {
        return $false
    }
}

function Get-LanIp() {
    try {
        $socket = [System.Net.Sockets.Socket]::new([System.Net.Sockets.AddressFamily]::InterNetwork, [System.Net.Sockets.SocketType]::Dgram, [System.Net.Sockets.ProtocolType]::Udp)
        $socket.Connect("8.8.8.8", 80)
        $ip = ([System.Net.IPEndPoint]$socket.LocalEndPoint).Address.ToString()
        $socket.Close()
        return $ip
    } catch {
        return "<电脑局域网IP>"
    }
}

Write-Step "Python dependencies"
Push-Location $Root
python -c "import fastapi, uvicorn, websockets, soundfile, numpy, cryptography, paramiko; print('deps-ok')"
Pop-Location

Write-Step "Backend route import"
Push-Location $BackendDir
python -c "from app.main import app; paths=sorted(getattr(r,'path','') for r in app.routes); assert '/ws/call' in paths and '/ws/avatar' in paths and '/ws/sensor' in paths and '/health' in paths; print('routes-ok')"
Pop-Location

Write-Step "Backend tests"
Push-Location $Root
python -m pytest backend\test_call_vad.py backend\test_call_ws_protocol.py backend\test_cloud_asr.py backend\test_runtime_diagnostics.py
Pop-Location

Write-Step "Frontend script parse"
Push-Location $Root
node -e "const fs=require('fs'); const html=fs.readFileSync('frontend/avatar_touch.html','utf8'); const m=html.match(/<script>([\s\S]*)<\/script>/); if(!m) throw new Error('script not found'); new Function(m[1]); console.log('avatar_touch script ok');"
Pop-Location

Write-Step "HTTPS certificate"
Push-Location $Root
python -c "import tools.local_https_gateway as g; g._ensure_cert(); print(g.CERT_FILE); print(g.KEY_FILE)"
Pop-Location

Write-Step "Ports"
$backendListen = Test-Port $BackendPort
$signalListen = Test-Port $SignalPort
$gatewayListen = Test-Port $GatewayPort
Write-Host "Backend :$BackendPort " -NoNewline
Write-Host ($(if ($backendListen) { "LISTEN" } else { "free" }))
Write-Host "Signal  :$SignalPort " -NoNewline
Write-Host ($(if ($signalListen) { "LISTEN" } else { "free" }))
Write-Host "Gateway :$GatewayPort " -NoNewline
Write-Host ($(if ($gatewayListen) { "LISTEN" } else { "free" }))

if ($backendListen -and -not (Test-HttpJson "http://127.0.0.1:$BackendPort/health")) {
    throw "Port $BackendPort is listening, but backend /health is not OK."
}
if ($signalListen -and -not (Test-HttpJson "http://127.0.0.1:$SignalPort/health")) {
    throw "Port $SignalPort is listening, but signalling /health is not OK."
}
if ($gatewayListen) {
    $previousCallback = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
    try {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            & $curl.Source -k -fsS --max-time 3 "https://127.0.0.1:$GatewayPort/health" | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "curl.exe failed with exit code $LASTEXITCODE"
            }
        } elseif ((Get-Command Invoke-WebRequest).Parameters.ContainsKey("SkipCertificateCheck")) {
            Invoke-WebRequest -Uri "https://127.0.0.1:$GatewayPort/health" -SkipCertificateCheck -UseBasicParsing -TimeoutSec 3 | Out-Null
        } else {
            [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
            Invoke-WebRequest -Uri "https://127.0.0.1:$GatewayPort/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
        }
    } catch {
        throw "Port $GatewayPort is listening, but HTTPS gateway /health is not OK."
    } finally {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $previousCallback
    }
}

function Test-SeetaSshEnv() {
    foreach ($name in @("SEETA_SSH_HOST", "SEETA_SSH_PORT", "SEETA_SSH_USER", "SEETA_SSH_PASSWORD")) {
        if (-not [Environment]::GetEnvironmentVariable($name)) {
            throw "$name is required for SeeTaCloud health checks"
        }
    }
}

if (-not $SkipCloudAsr) {
    Write-Step "Cloud Whisper ASR health"
    Test-SeetaSshEnv
    Push-Location $Root
    @'
import os
import paramiko
host=os.environ['SEETA_SSH_HOST']
port=int(os.environ['SEETA_SSH_PORT'])
user=os.environ['SEETA_SSH_USER']
password=os.environ['SEETA_SSH_PASSWORD']
client=paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=host, port=port, username=user, password=password, timeout=15, banner_timeout=15, auth_timeout=15)
stdin, stdout, stderr = client.exec_command('curl -fsS --max-time 5 http://127.0.0.1:9002/health', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
client.close()
if not out or '"loaded":true' not in out.replace(' ', '').lower():
    raise SystemExit(err or out or 'Cloud Whisper ASR health failed')
print(out)
'@ | python -
    Pop-Location
}

if (-not $SkipCloudTts) {
    Write-Step "Cloud IndexTTS2 health"
    Test-SeetaSshEnv
    Push-Location $Root
    @'
import os
import paramiko
host=os.environ['SEETA_SSH_HOST']
port=int(os.environ['SEETA_SSH_PORT'])
user=os.environ['SEETA_SSH_USER']
password=os.environ['SEETA_SSH_PASSWORD']
client=paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=host, port=port, username=user, password=password, timeout=15, banner_timeout=15, auth_timeout=15)
stdin, stdout, stderr = client.exec_command('curl -fsS --max-time 5 http://127.0.0.1:9001/health', timeout=10)
out = stdout.read().decode('utf-8', errors='replace').strip()
err = stderr.read().decode('utf-8', errors='replace').strip()
client.close()
if not out or '"ok":true' not in out.replace(' ', ''):
    raise SystemExit(err or out or 'IndexTTS2 health failed')
print(out)
'@ | python -
    Pop-Location
}

if (-not $SkipUnityCompile) {
    Write-Step "Unity script compile"
    if (-not (Test-Path $UnityPath)) {
        throw "Unity executable not found: $UnityPath"
    }
    & $UnityPath -batchmode -quit -projectPath $Root -logFile $UnityLog
    if ($LASTEXITCODE -ne 0) {
        throw "Unity batchmode failed with exit code $LASTEXITCODE. See $UnityLog"
    }
    $errors = Select-String -Path $UnityLog -Pattern "error CS|Scripts have compiler errors|Compiler errors" -ErrorAction SilentlyContinue
    if ($errors) {
        $errors | Select-Object -First 20 | ForEach-Object { Write-Host $_.Line -ForegroundColor Red }
        throw "Unity compile has C# errors. See $UnityLog"
    }
    Write-Host "unity-compile-ok"
}

$lanIp = Get-LanIp
Write-Step "Ready for real-device test"
Write-Host "Phone URL: https://$lanIp`:$GatewayPort/frontend/avatar_touch.html" -ForegroundColor Green
Write-Host "Unity RenderStreaming URL must be ws://127.0.0.1:$SignalPort"
Write-Host "Unity NetworkClient serverUrl must be ws://127.0.0.1:$BackendPort/ws/avatar"
Write-Host "For real ASR/TTS, set SEETA_SSH_* env vars, then run:"
Write-Host ".\scripts\start_asr_tunnel.ps1"
Write-Host ".\scripts\start_indextts_tunnel.ps1"
