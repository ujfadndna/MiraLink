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
    [string]$RemoteRoot = "/tmp/MiraLink/unity",
    [string]$TurnPublicIp = "",
    [int]$TurnPort = 3478,
    [string]$TurnUsername = "miralink",
    [string]$IceTransportPolicy = "relay",
    [double]$SampleDuration = 20,
    [switch]$UploadBuild,
    [switch]$TryHighFps
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$profiles = @("baseline", "phone_stable", "clear")
if ($TryHighFps) {
    $profiles += "high_fps"
}

$lastPassedProfile = ""
$baseArgs = @(
    "-SshHost", $SshHost,
    "-SshPort", $SshPort,
    "-SshUser", $SshUser,
    "-BackendPort", $BackendPort,
    "-CloudBackendPort", $CloudBackendPort,
    "-AsrPort", $AsrPort,
    "-TtsPort", $TtsPort,
    "-SignalPort", $SignalPort,
    "-GatewayPort", $GatewayPort,
    "-RemoteRoot", $RemoteRoot,
    "-TurnPublicIp", $TurnPublicIp,
    "-TurnPort", $TurnPort,
    "-TurnUsername", $TurnUsername,
    "-IceTransportPolicy", $IceTransportPolicy
)
if ($SshPassword) {
    $baseArgs += @("-SshPassword", $SshPassword)
}

foreach ($profile in $profiles) {
    Write-Host ""
    Write-Host "=== Testing video profile: $profile ===" -ForegroundColor Cyan
    $argsList = $baseArgs + @("-VideoProfile", $profile)
    if ($UploadBuild) {
        $argsList += "-UploadBuild"
        $UploadBuild = $false
    }
    & (Join-Path $PSScriptRoot "start_cloud_unity_demo.ps1") @argsList

    $turnUrls = "turn:$($TurnPublicIp):$($TurnPort)?transport=udp,turn:$($TurnPublicIp):$($TurnPort)?transport=tcp"
    $phoneUrl = "https://127.0.0.1`:$GatewayPort/frontend/avatar_touch.html"
    python tools/avatar_touch_webrtc_stats.py `
        --url $phoneUrl `
        --label $profile `
        --profile $profile `
        --duration $SampleDuration `
        --ice-policy $IceTransportPolicy `
        --turn-urls $turnUrls `
        --turn-username $TurnUsername
    if ($LASTEXITCODE -ne 0) {
        if ($lastPassedProfile) {
            Write-Host "Profile '$profile' failed; restarting last passed profile '$lastPassedProfile'." -ForegroundColor Yellow
            & (Join-Path $PSScriptRoot "start_cloud_unity_demo.ps1") @($baseArgs + @("-VideoProfile", $lastPassedProfile))
        }
        throw "Video profile '$profile' failed WebRTC stats validation."
    }
    $lastPassedProfile = $profile
}

Write-Host ""
Write-Host "All tested video profiles passed. Use the highest tested profile above for the final demo." -ForegroundColor Green
