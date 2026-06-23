param(
    [string]$SshHost = "",
    [int]$SshPort = 16821,
    [string]$SshUser = "root",
    [string]$SshPassword = "",
    [int]$BackendPort = 8100,
    [int]$CloudBackendPort = 18100,
    [int]$AsrPort = 9002,
    [int]$TtsPort = 9001,
    [int]$SignalPort = 8080,
    [int]$GatewayPort = 8443,
    [string]$RemoteRoot = "/tmp/herunity/unity",
    [string]$TurnPublicIp = "",
    [int]$TurnPort = 3478,
    [string]$TurnUsername = "herunity",
    [string]$TurnCredential = "",
    [string]$IceTransportPolicy = "relay",
    [ValidateSet("baseline", "phone_stable", "clear", "high_fps")]
    [string]$VideoProfile = "phone_stable",
    [int]$StreamWidth = 0,
    [int]$StreamHeight = 0,
    [double]$StreamFps = 0,
    [int]$StreamBitrateMin = 0,
    [int]$StreamBitrateMax = 0,
    [ValidateSet("xvfb", "nvidia-xorg")]
    [string]$DisplayServer = "nvidia-xorg",
    [switch]$UploadBuild,
    [switch]$SkipCloudUnityStart
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root "workspace\run"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
$TurnCredentialFile = Join-Path $RuntimeDir "turn_credential.txt"

$VideoProfiles = @{
    baseline = @{
        Width = 240
        Height = 426
        Fps = 8.0
        BitrateMin = 80
        BitrateMax = 300
    }
    phone_stable = @{
        Width = 360
        Height = 640
        Fps = 12.0
        BitrateMin = 250
        BitrateMax = 900
    }
    clear = @{
        Width = 540
        Height = 960
        Fps = 12.0
        BitrateMin = 500
        BitrateMax = 1400
    }
    high_fps = @{
        Width = 540
        Height = 960
        Fps = 15.0
        BitrateMin = 800
        BitrateMax = 1800
    }
}

$SelectedVideo = $VideoProfiles[$VideoProfile].Clone()
if ($StreamWidth -gt 0) { $SelectedVideo.Width = $StreamWidth }
if ($StreamHeight -gt 0) { $SelectedVideo.Height = $StreamHeight }
if ($StreamFps -gt 0) { $SelectedVideo.Fps = $StreamFps }
if ($StreamBitrateMin -gt 0) { $SelectedVideo.BitrateMin = $StreamBitrateMin }
if ($StreamBitrateMax -gt 0) { $SelectedVideo.BitrateMax = $StreamBitrateMax }
if ([int]$SelectedVideo.Width -le 0 -or [int]$SelectedVideo.Height -le 0 -or [double]$SelectedVideo.Fps -le 0) {
    throw "Invalid video stream settings: $($SelectedVideo | ConvertTo-Json -Compress)"
}
if ([int]$SelectedVideo.BitrateMax -lt [int]$SelectedVideo.BitrateMin) {
    throw "StreamBitrateMax must be greater than or equal to StreamBitrateMin"
}
$StreamFpsText = ([double]$SelectedVideo.Fps).ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture)

function New-TurnCredential() {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return ([Convert]::ToBase64String($bytes)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function UrlEncode($Value) {
    return [System.Uri]::EscapeDataString([string]$Value)
}

if (-not $SshPassword) {
    $SshPassword = [Environment]::GetEnvironmentVariable("SEETA_SSH_PASSWORD")
}
if (-not $SshPassword) {
    throw "SshPassword or SEETA_SSH_PASSWORD is required"
}

$env:SEETA_SSH_HOST = $SshHost
$env:SEETA_SSH_PORT = [string]$SshPort
$env:SEETA_SSH_USER = $SshUser
$env:SEETA_SSH_PASSWORD = $SshPassword

if (-not $TurnCredential) {
    $TurnCredential = [Environment]::GetEnvironmentVariable("TURN_CREDENTIAL")
}
if (-not $TurnCredential) {
    if (Test-Path $TurnCredentialFile) {
        $TurnCredential = (Get-Content $TurnCredentialFile -Raw).Trim()
    }
}
if (-not $TurnCredential) {
    $TurnCredential = New-TurnCredential
}
$TurnCredential = $TurnCredential.Trim()
if (-not $TurnCredential) {
    throw "TURN credential is empty"
}
$TurnCredential | Set-Content -Path $TurnCredentialFile -Encoding ascii -NoNewline
$TurnUrls = "turn:$($TurnPublicIp):$($TurnPort)?transport=udp,turn:$($TurnPublicIp):$($TurnPort)?transport=tcp"
$env:TURN_URLS = $TurnUrls
$env:TURN_USERNAME = $TurnUsername
$env:TURN_CREDENTIAL = $TurnCredential

function Assert-LocalTurnCredential() {
    if (-not (Test-Path $TurnCredentialFile)) {
        throw "TURN credential file missing: $TurnCredentialFile"
    }
    $fileCredential = (Get-Content $TurnCredentialFile -Raw).Trim()
    if ($fileCredential -cne $TurnCredential) {
        throw "TURN credential mismatch between runtime variable and $TurnCredentialFile"
    }
    Write-Host "TURN credential source: $TurnCredentialFile len=$($fileCredential.Length)"
}

function Assert-CloudTurnCredential() {
    Write-Host "Checking cloud TURN credential consistency..."
    python tools/cloud_unity_manager.py check-turn --remote-root $RemoteRoot --signal-port $SignalPort --expected-turn-credential $TurnCredential
    if ($LASTEXITCODE -ne 0) {
        if (-not $SkipCloudUnityStart) {
            python tools/cloud_unity_manager.py stop --remote-root $RemoteRoot --signal-port $SignalPort | Out-Host
        }
        throw "TURN credential mismatch. Restart the cloud runtime with scripts/start_cloud_unity_demo.ps1 so URL, signalling, and Unity share the same credential."
    }
}

function Start-CloudUnityRuntime($Server, $ProfileName, $Video, [switch]$AllowPrepareNvidia) {
    $fpsText = ([double]$Video.Fps).ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture)
    if ($Server -eq "nvidia-xorg") {
        Write-Host "Running cloud GPU preflight..."
        python tools/cloud_unity_manager.py gpu-preflight --remote-root $RemoteRoot
        if ($LASTEXITCODE -ne 0) {
            if ($AllowPrepareNvidia) {
                Write-Warning "cloud GPU preflight reported issues; continuing to prepare NVIDIA Xorg userland"
            } else {
                throw "cloud GPU preflight failed"
            }
        }
        if ($AllowPrepareNvidia) {
            Write-Host "Preparing isolated NVIDIA Xorg userland..."
            python tools/cloud_unity_manager.py prepare-nvidia-xorg --remote-root $RemoteRoot --stream-width $($Video.Width) --stream-height $($Video.Height)
            if ($LASTEXITCODE -ne 0) {
                throw "NVIDIA Xorg preparation failed"
            }
        }
    }

    Write-Host "Starting westb signalling + $Server + Unity VP8 ($ProfileName)..."
    python tools/cloud_unity_manager.py start --remote-root $RemoteRoot --signal-port $SignalPort --backend-ws-url "ws://127.0.0.1:$CloudBackendPort/ws/avatar" --ice-transport-policy $IceTransportPolicy --turn-urls $TurnUrls --turn-username $TurnUsername --turn-credential $TurnCredential --display-server $Server --video-codec vp8 --stream-width $($Video.Width) --stream-height $($Video.Height) --stream-fps $fpsText --stream-bitrate-min $($Video.BitrateMin) --stream-bitrate-max $($Video.BitrateMax) --unity-cuda-visible-devices -1
    if ($LASTEXITCODE -ne 0) {
        throw "cloud Unity runtime start failed for display=$Server profile=$ProfileName"
    }
}

function Start-XvfbBaselineRollback($Reason) {
    Write-Warning "NVIDIA cloud start failed: $Reason"
    Write-Warning "Rolling back to Xvfb baseline 240x426 / 8 fps so the public entry keeps a video path."
    $baseline = $VideoProfiles["baseline"].Clone()
    try {
        python tools/cloud_unity_manager.py stop --remote-root $RemoteRoot --signal-port $SignalPort | Out-Host
    } catch {
        Write-Warning "stop before rollback failed: $($_.Exception.Message)"
    }
    Start-CloudUnityRuntime "xvfb" "baseline" $baseline
}

Assert-LocalTurnCredential
Write-Host "Video profile: $VideoProfile $($SelectedVideo.Width)x$($SelectedVideo.Height) / $StreamFpsText fps / $($SelectedVideo.BitrateMin)-$($SelectedVideo.BitrateMax) kbps / VP8"

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
                return $old
            }
        } else {
            Remove-Item $pidFile -Force
        }
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
    return $proc
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

function Wait-Http($Url, [int]$Seconds = 30, [switch]$SkipCertificateCheck) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $lastError = ""
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-HttpRequestCompat $Url 5 -SkipCertificateCheck:$SkipCertificateCheck | Out-Null
            return
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Service did not become healthy after $Seconds seconds: $Url. Last error: $lastError"
}

function Start-ForwardTunnel($Name, $LocalPort, $RemotePort, [bool]$AllowExisting = $true, [string]$HealthUrl = "", [switch]$Restart) {
    $pidFile = Join-Path $RuntimeDir "$Name.pid"
    if (Test-Path $pidFile) {
        $oldPid = [int](Get-Content $pidFile -Raw)
        if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
            if ($Restart) {
                Stop-ManagedProcess $Name
            } elseif ($HealthUrl -and -not (Test-Http $HealthUrl)) {
                Write-Host "$Name pid=$oldPid is running but health check failed; restarting"
                Stop-ManagedProcess $Name
            } else {
                Write-Host "$Name already running pid=$oldPid"
                return
            }
        } else {
            Remove-Item $pidFile -Force
        }
    }

    $existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
    if ($existing) {
        if ($HealthUrl -and -not (Test-Http $HealthUrl)) {
            $owners = ($existing | Select-Object -ExpandProperty OwningProcess -Unique) -join ","
            throw "127.0.0.1:$LocalPort is listening by pid(s) $owners, but health check failed: $HealthUrl"
        }
        if (-not $AllowExisting) {
            throw "127.0.0.1:$LocalPort is already listening; stop the existing process before starting $Name."
        }
        Write-Host "127.0.0.1:$LocalPort is already listening; reuse for $Name"
        return
    }

    Start-ManagedProcess $Name "python" "tools/seetacloud_port_forward.py" $Root @{
        TUNNEL_MODE = "forward"
        TUNNEL_LOCAL_HOST = "127.0.0.1"
        TUNNEL_LOCAL_PORT = $LocalPort
        TUNNEL_REMOTE_HOST = "127.0.0.1"
        TUNNEL_REMOTE_PORT = $RemotePort
        SEETA_SSH_HOST = $SshHost
        SEETA_SSH_PORT = $SshPort
        SEETA_SSH_USER = $SshUser
        SEETA_SSH_PASSWORD = $SshPassword
    } | Out-Null
}

function Start-ReverseBackendTunnel() {
    Start-ManagedProcess "backend-reverse-tunnel" "python" "tools/seetacloud_port_forward.py" $Root @{
        TUNNEL_MODE = "reverse"
        TUNNEL_LOCAL_HOST = "127.0.0.1"
        TUNNEL_LOCAL_PORT = $BackendPort
        TUNNEL_REMOTE_HOST = "127.0.0.1"
        TUNNEL_REMOTE_PORT = $CloudBackendPort
        SEETA_SSH_HOST = $SshHost
        SEETA_SSH_PORT = $SshPort
        SEETA_SSH_USER = $SshUser
        SEETA_SSH_PASSWORD = $SshPassword
    } -Restart | Out-Null
}

function Get-BackendDiagnostics() {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/v1/diagnostics/runtime" -TimeoutSec 2
    } catch {
        return $null
    }
}

Write-Host "[1/8] Checking westb ASR/TTS health..."
python tools/cloud_unity_manager.py health --remote-root $RemoteRoot --signal-port $SignalPort --asr-port $AsrPort --tts-port $TtsPort
if ($LASTEXITCODE -ne 0) {
    throw "westb ASR/TTS health failed"
}

Write-Host "[2/8] Starting ASR/TTS forward tunnels..."
Start-ForwardTunnel "asr-tunnel" $AsrPort $AsrPort $true "http://127.0.0.1:$AsrPort/health"
Wait-Http "http://127.0.0.1:$AsrPort/health" 120
Start-ForwardTunnel "indextts-tunnel" $TtsPort $TtsPort $true "http://127.0.0.1:$TtsPort/health"
Wait-Http "http://127.0.0.1:$TtsPort/health" 120

Write-Host "[3/8] Starting local backend..."
& "$PSScriptRoot\start_call_demo.ps1" `
    -BackendPort $BackendPort `
    -SignalPort $SignalPort `
    -GatewayPort $GatewayPort `
    -AsrBackend cloud_whisper `
    -CloudAsrApiUrl "http://127.0.0.1:$AsrPort" `
    -TtsBackend indextts `
    -IndexTtsApiUrl "http://127.0.0.1:$TtsPort" `
    -CallBargeInEnabled $false `
    -SkipSignalling `
    -SkipGateway

$diag = Get-BackendDiagnostics
if (-not $diag) {
    throw "backend diagnostics unavailable"
}
if ([string]$diag.asr_backend -ne "cloud_whisper" -or -not [bool]$diag.cloud_asr_configured -or [string]$diag.tts_backend -ne "indextts" -or -not [bool]$diag.indextts_api_configured -or [bool]$diag.call_barge_in_enabled) {
    throw "backend runtime mismatch: $($diag | ConvertTo-Json -Compress)"
}

Write-Host "[4/8] Starting westb reverse tunnel for backend..."
Start-ReverseBackendTunnel
Start-Sleep -Seconds 2

if ($UploadBuild) {
    Write-Host "[5/8] Uploading Unity Linux build..."
    python tools/cloud_unity_manager.py upload-build --remote-root $RemoteRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Unity build upload failed"
    }
} else {
    Write-Host "[5/8] Skipping Unity build upload"
}

if (-not $SkipCloudUnityStart) {
    Write-Host "[6/8] Starting westb cloud Unity..."
    try {
        Start-CloudUnityRuntime $DisplayServer $VideoProfile $SelectedVideo -AllowPrepareNvidia:($DisplayServer -eq "nvidia-xorg")
    } catch {
        if ($DisplayServer -eq "nvidia-xorg") {
            Start-XvfbBaselineRollback $_.Exception.Message
            $DisplayServer = "xvfb"
            $VideoProfile = "baseline"
            $SelectedVideo = $VideoProfiles["baseline"].Clone()
            $StreamFpsText = ([double]$SelectedVideo.Fps).ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture)
        } else {
            throw
        }
    }
    Assert-CloudTurnCredential
} else {
    Write-Host "[6/8] Skipping westb Unity start"
    Assert-CloudTurnCredential
}

Write-Host "[7/8] Starting signalling forward tunnel..."
Stop-ManagedProcess "signalling"
Start-ForwardTunnel "cloud-signalling-tunnel" $SignalPort $SignalPort $false "http://127.0.0.1:$SignalPort/health" -Restart
Wait-Http "http://127.0.0.1:$SignalPort/health" 30

Write-Host "[8/8] Starting HTTPS gateway..."
Stop-ManagedProcess "gateway"
Start-ManagedProcess "gateway" "python" "tools/local_https_gateway.py" $Root @{
    HTTPS_GATEWAY_PORT = $GatewayPort
    BACKEND_WS_BASE = "ws://127.0.0.1:$BackendPort"
    SIGNAL_WS_BASE = "ws://127.0.0.1:$SignalPort"
    ICE_TRANSPORT_POLICY = $IceTransportPolicy
    TURN_URLS = $TurnUrls
    TURN_USERNAME = $TurnUsername
    TURN_CREDENTIAL = $TurnCredential
} | Out-Null
Wait-Http "https://127.0.0.1:$GatewayPort/health" 30 -SkipCertificateCheck

try {
    $socket = [System.Net.Sockets.Socket]::new([System.Net.Sockets.AddressFamily]::InterNetwork, [System.Net.Sockets.SocketType]::Dgram, [System.Net.Sockets.ProtocolType]::Udp)
    $socket.Connect("8.8.8.8", 80)
    $lanIp = ([System.Net.IPEndPoint]$socket.LocalEndPoint).Address.ToString()
    $socket.Close()
} catch {
    $lanIp = "<电脑局域网IP>"
}

Write-Host ""
Write-Host "Cloud Unity demo ready." -ForegroundColor Green
$phoneUrl = "https://$lanIp`:$GatewayPort/frontend/avatar_touch.html?autostart=1&session=auto"
$sampleUrl = "https://$lanIp`:$GatewayPort/frontend/avatar_touch.html"
Write-Host "Phone URL: $phoneUrl" -ForegroundColor Green
Write-Host "Video profile: $VideoProfile $($SelectedVideo.Width)x$($SelectedVideo.Height) / $StreamFpsText fps / $($SelectedVideo.BitrateMin)-$($SelectedVideo.BitrateMax) kbps / VP8"
Write-Host "Runtime logs: $RuntimeDir"
Write-Host "TURN credential file: $TurnCredentialFile"
Write-Host "Sample command: python tools/avatar_touch_webrtc_stats.py --url `"$sampleUrl`" --label $VideoProfile --profile $VideoProfile --duration 20 --no-turn"
Write-Host "Cloud status: python tools/cloud_unity_manager.py status --remote-root $RemoteRoot --signal-port $SignalPort --asr-port $AsrPort --tts-port $TtsPort"
