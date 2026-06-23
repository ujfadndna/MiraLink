param(
    [int]$LocalPort = 9002,
    [int]$RemotePort = 9002
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root "workspace\run"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

foreach ($name in @("SEETA_SSH_HOST", "SEETA_SSH_PORT", "SEETA_SSH_USER", "SEETA_SSH_PASSWORD")) {
    if (-not [Environment]::GetEnvironmentVariable($name)) {
        throw "$name is required for SeeTaCloud SSH tunnel"
    }
}

$pidFile = Join-Path $RuntimeDir "asr-tunnel.pid"
if (Test-Path $pidFile) {
    $oldPid = [int](Get-Content $pidFile -Raw)
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        Write-Host "ASR tunnel already running pid=$oldPid"
        return
    }
    Remove-Item $pidFile -Force
}

$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "127.0.0.1:$LocalPort is already listening; not starting another tunnel."
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$LocalPort/health" -TimeoutSec 2
        Write-Host "ASR endpoint healthy: $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
        return
    } catch {
        throw "127.0.0.1:$LocalPort is listening, but /health failed."
    }
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "python"
$psi.Arguments = "tools/seetacloud_port_forward.py"
$psi.WorkingDirectory = $Root
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.Environment["TUNNEL_LOCAL_HOST"] = "127.0.0.1"
$psi.Environment["TUNNEL_LOCAL_PORT"] = [string]$LocalPort
$psi.Environment["TUNNEL_REMOTE_HOST"] = "127.0.0.1"
$psi.Environment["TUNNEL_REMOTE_PORT"] = [string]$RemotePort

$stdout = Join-Path $RuntimeDir "asr-tunnel.stdout.log"
$stderr = Join-Path $RuntimeDir "asr-tunnel.stderr.log"
$proc = [System.Diagnostics.Process]::Start($psi)
$proc.Id | Set-Content -Path $pidFile -NoNewline
Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action {
    if ($EventArgs.Data) { Add-Content -Path $Event.MessageData -Value $EventArgs.Data }
} -MessageData $stdout | Out-Null
Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action {
    if ($EventArgs.Data) { Add-Content -Path $Event.MessageData -Value $EventArgs.Data }
} -MessageData $stderr | Out-Null
$proc.BeginOutputReadLine()
$proc.BeginErrorReadLine()

for ($i = 0; $i -lt 60; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$LocalPort/health" -TimeoutSec 2
        Write-Host "ASR tunnel ready pid=$($proc.Id): $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
        return
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

throw "ASR tunnel did not become healthy. See $stderr"
