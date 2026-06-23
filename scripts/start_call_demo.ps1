param(
    [int]$BackendPort = 8100,
    [int]$SignalPort = 8080,
    [int]$GatewayPort = 8443,
    [ValidateSet("mock", "faster_whisper", "cloud_whisper")]
    [string]$AsrBackend = "cloud_whisper",
    [string]$CloudAsrApiUrl = "http://127.0.0.1:9002",
    [ValidateSet("mock", "indextts")]
    [string]$TtsBackend = "indextts",
    [string]$IndexTtsApiUrl = "http://127.0.0.1:9001",
    [double]$IndexTtsHttpTimeoutSec = 240,
    [bool]$CallBargeInEnabled = $false,
    [switch]$SkipSignalling,
    [switch]$SkipGateway
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root "workspace\run"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Get-ManagedProcess($Name) {
    $pidFile = Join-Path $RuntimeDir "$Name.pid"
    if (Test-Path $pidFile) {
        $oldPid = [int](Get-Content $pidFile -Raw)
        return Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    }
    return $null
}

function Stop-ManagedProcess($Name) {
    $pidFile = Join-Path $RuntimeDir "$Name.pid"
    if (-not (Test-Path $pidFile)) {
        return
    }

    $oldPid = [int](Get-Content $pidFile -Raw)
    $old = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if ($old) {
        Stop-Process -Id $oldPid -Force
        Write-Host "stopped $Name pid=$oldPid"
    }
    Remove-Item $pidFile -Force
}

function Start-ManagedProcess($Name, $FilePath, $Arguments, $WorkingDirectory, $EnvVars, [switch]$Restart) {
    $pidFile = Join-Path $RuntimeDir "$Name.pid"
    if (Test-Path $pidFile) {
        $oldPid = [int](Get-Content $pidFile -Raw)
        $old = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if ($old) {
            if ($Restart) {
                Stop-ManagedProcess $Name
            } else {
                Write-Host "$Name already running pid=$oldPid"
                return
            }
        } else {
            Remove-Item $pidFile -Force
        }
    }

    if (Test-Path $pidFile) {
        Remove-Item $pidFile -Force
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    foreach ($key in $EnvVars.Keys) {
        $psi.Environment[$key] = [string]$EnvVars[$key]
    }

    $stdout = Join-Path $RuntimeDir "$Name.stdout.log"
    $stderr = Join-Path $RuntimeDir "$Name.stderr.log"
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
    Write-Host "started $Name pid=$($proc.Id)"
}

function Test-Http($Url, [switch]$SkipCertificateCheck) {
    try {
        Invoke-HttpRequestCompat $Url 2 -SkipCertificateCheck:$SkipCertificateCheck | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Invoke-HttpRequestCompat($Url, [int]$TimeoutSec, [switch]$SkipCertificateCheck) {
    if ($SkipCertificateCheck -and [string]$Url -like "https://*") {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            $output = & $curl.Source -k -fsS --max-time $TimeoutSec $Url
            if ($LASTEXITCODE -ne 0) {
                throw "curl.exe failed with exit code $LASTEXITCODE"
            }
            return $output
        }
    }

    $params = @{
        Uri = $Url
        TimeoutSec = $TimeoutSec
        UseBasicParsing = $true
    }
    $supportsSkipCert = (Get-Command Invoke-WebRequest).Parameters.ContainsKey("SkipCertificateCheck")
    if ($SkipCertificateCheck -and $supportsSkipCert) {
        $params["SkipCertificateCheck"] = $true
        return Invoke-WebRequest @params
    }
    if (-not $SkipCertificateCheck) {
        return Invoke-WebRequest @params
    }

    $previousCallback = [System.Net.ServicePointManager]::ServerCertificateValidationCallback
    try {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        return Invoke-WebRequest @params
    } finally {
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = $previousCallback
    }
}

function Wait-Http($Url, [switch]$SkipCertificateCheck) {
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-HttpRequestCompat $Url 2 -SkipCertificateCheck:$SkipCertificateCheck | Out-Null
            return
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Service did not become healthy: $Url"
}

function Get-BackendDiagnostics() {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/v1/diagnostics/runtime" -TimeoutSec 2
    } catch {
        return $null
    }
}

function Test-BackendMatches($Diagnostics) {
    if (-not $Diagnostics) {
        return $false
    }
    if ([string]$Diagnostics.asr_backend -ne $AsrBackend) {
        return $false
    }
    if ($AsrBackend -eq "cloud_whisper" -and -not [bool]$Diagnostics.cloud_asr_configured) {
        return $false
    }
    if ([string]$Diagnostics.tts_backend -ne $TtsBackend) {
        return $false
    }
    if ($TtsBackend -eq "indextts" -and -not [bool]$Diagnostics.indextts_api_configured) {
        return $false
    }
    if ($TtsBackend -eq "indextts" -and -not ($Diagnostics.PSObject.Properties.Name -contains "indextts_http_timeout_sec")) {
        return $false
    }
    if ($TtsBackend -eq "indextts") {
        if ([double]$Diagnostics.indextts_http_timeout_sec -lt $IndexTtsHttpTimeoutSec) {
            return $false
        }
    }
    if (-not ($Diagnostics.PSObject.Properties.Name -contains "call_barge_in_enabled")) {
        return $false
    }
    if ([bool]$Diagnostics.call_barge_in_enabled -ne $CallBargeInEnabled) {
        return $false
    }
    return $true
}

function Assert-BackendMatches() {
    $diag = Get-BackendDiagnostics
    if (-not $diag) {
        throw "Backend is healthy but diagnostics endpoint is unavailable. Restart the backend with this script."
    }
    if (-not (Test-BackendMatches $diag)) {
        throw "Backend runtime mismatch: expected ASR '$AsrBackend' / TTS '$TtsBackend' / call_barge_in_enabled '$CallBargeInEnabled', got ASR '$($diag.asr_backend)' cloud_asr_configured=$($diag.cloud_asr_configured), TTS '$($diag.tts_backend)' indextts_api_configured=$($diag.indextts_api_configured), call_barge_in_enabled=$($diag.call_barge_in_enabled)."
    }
    Write-Host "backend diagnostics: asr_backend=$($diag.asr_backend), cloud_asr_configured=$($diag.cloud_asr_configured), tts_backend=$($diag.tts_backend), indextts_api_configured=$($diag.indextts_api_configured), call_barge_in_enabled=$($diag.call_barge_in_enabled)"
}

function Start-BackendProcess() {
    $envVars = @{
        ASR_BACKEND = $AsrBackend
        TTS_BACKEND = $TtsBackend
        CALL_BARGE_IN_ENABLED = $CallBargeInEnabled.ToString().ToLowerInvariant()
    }
    if ($AsrBackend -eq "cloud_whisper") {
        $envVars["CLOUD_ASR_API_URL"] = $CloudAsrApiUrl
    }
    if ($TtsBackend -eq "indextts") {
        $envVars["INDEXTTS_API_URL"] = $IndexTtsApiUrl
        $envVars["INDEXTTS_HTTP_TIMEOUT_SEC"] = $IndexTtsHttpTimeoutSec
    }
    Start-ManagedProcess "backend" "python" "-m uvicorn app.main:app --host 0.0.0.0 --port $BackendPort" (Join-Path $Root "backend") $envVars -Restart
}

$CloudAsrApiUrl = $CloudAsrApiUrl.TrimEnd("/")
$IndexTtsApiUrl = $IndexTtsApiUrl.TrimEnd("/")
if ($AsrBackend -eq "cloud_whisper") {
    if (-not $CloudAsrApiUrl) {
        throw "-CloudAsrApiUrl is required when -AsrBackend cloud_whisper"
    }
    if (-not (Test-Http "$CloudAsrApiUrl/health")) {
        throw "Cloud Whisper ASR health check failed: $CloudAsrApiUrl/health"
    }
    Write-Host "Cloud Whisper ASR healthy: $CloudAsrApiUrl"
}

if ($TtsBackend -eq "indextts") {
    if (-not $IndexTtsApiUrl) {
        throw "-IndexTtsApiUrl is required when -TtsBackend indextts"
    }
    if (-not (Test-Http "$IndexTtsApiUrl/health")) {
        throw "IndexTTS2 health check failed: $IndexTtsApiUrl/health. Start the tunnel first: .\scripts\start_indextts_tunnel.ps1"
    }
    Write-Host "IndexTTS2 healthy: $IndexTtsApiUrl"
}

if (Test-Http "http://127.0.0.1:$BackendPort/health") {
    $diag = Get-BackendDiagnostics
    if (Test-BackendMatches $diag) {
        Write-Host "backend already healthy on :$BackendPort"
        Assert-BackendMatches
    } else {
        $managed = Get-ManagedProcess "backend"
        if ($managed) {
            $actual = if ($diag) { "ASR '$($diag.asr_backend)' / TTS '$($diag.tts_backend)'" } else { "unknown (diagnostics unavailable)" }
            Write-Host "backend on :$BackendPort uses $actual; restarting managed backend for ASR '$AsrBackend' / TTS '$TtsBackend'"
            Stop-ManagedProcess "backend"
            Start-BackendProcess
            Wait-Http "http://127.0.0.1:$BackendPort/health"
            Assert-BackendMatches
        } else {
            $actual = if ($diag) { "ASR '$($diag.asr_backend)' / TTS '$($diag.tts_backend)' / call_barge_in_enabled '$($diag.call_barge_in_enabled)'" } else { "unknown (diagnostics unavailable)" }
            throw "Backend already healthy on :$BackendPort but target runtime is ASR '$AsrBackend' / TTS '$TtsBackend' / call_barge_in_enabled '$CallBargeInEnabled' and actual is $actual. Stop that backend or run scripts/stop_call_demo.ps1 if it is managed."
        }
    }
} else {
    Start-BackendProcess
    Wait-Http "http://127.0.0.1:$BackendPort/health"
    Assert-BackendMatches
}

if ($SkipSignalling) {
    Write-Host "signalling skipped"
} else {
    if (Test-Http "http://127.0.0.1:$SignalPort/health") {
        Write-Host "signalling already healthy on :$SignalPort"
    } else {
        Start-ManagedProcess "signalling" "python" "-u tools/server_v3.py" $Root @{
            PORT = $SignalPort
            BACKEND_WS = "ws://127.0.0.1:$BackendPort/ws/avatar"
            ICE_TRANSPORT_POLICY = "all"
        }
        Wait-Http "http://127.0.0.1:$SignalPort/health"
    }
}

if ($SkipGateway) {
    Write-Host "gateway skipped"
} else {
    if (Test-Http "https://127.0.0.1:$GatewayPort/health" -SkipCertificateCheck) {
        Write-Host "gateway already healthy on :$GatewayPort"
    } else {
        Start-ManagedProcess "gateway" "python" "tools/local_https_gateway.py" $Root @{
            HTTPS_GATEWAY_PORT = $GatewayPort
            BACKEND_WS_BASE = "ws://127.0.0.1:$BackendPort"
            SIGNAL_WS_BASE = "ws://127.0.0.1:$SignalPort"
        }
        Wait-Http "https://127.0.0.1:$GatewayPort/health" -SkipCertificateCheck
    }
}

try {
    $socket = [System.Net.Sockets.Socket]::new([System.Net.Sockets.AddressFamily]::InterNetwork, [System.Net.Sockets.SocketType]::Dgram, [System.Net.Sockets.ProtocolType]::Udp)
    $socket.Connect("8.8.8.8", 80)
    $lanIp = ([System.Net.IPEndPoint]$socket.LocalEndPoint).Address.ToString()
    $socket.Close()
} catch {
    $lanIp = "<电脑局域网IP>"
}

Write-Host ""
Write-Host "Services ready." -ForegroundColor Green
Write-Host "Phone URL: https://$lanIp`:$GatewayPort/frontend/avatar_touch.html" -ForegroundColor Green
Write-Host "Logs: $RuntimeDir"
