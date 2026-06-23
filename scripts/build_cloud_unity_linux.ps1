param(
    [string]$UnityPath = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root "workspace\run"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

if (-not $UnityPath) {
    $UnityPath = Join-Path $env:ProgramFiles "Unity\Hub\Editor\2022.3.62f3c1\Editor\Unity.exe"
}

if (-not $OutputDir) {
    $OutputDir = Join-Path (Split-Path -Parent $Root) "HerUnity-Build-GL"
}

if (-not (Test-Path $UnityPath)) {
    throw "Unity executable not found: $UnityPath"
}

$logPath = Join-Path $RuntimeDir "unity-linux-build.log"
$expectedOutput = Join-Path $OutputDir "HerUnity.x86_64"

Write-Host "Building Linux x86_64 Unity player..."
Write-Host "Log: $logPath"

$unityArgs = @(
    "-batchmode",
    "-quit",
    "-projectPath", $Root,
    "-executeMethod", "BuildOpenGLCoreScript.Build",
    "-buildOutputPath", $expectedOutput,
    "-logFile", $logPath
)

$proc = Start-Process -FilePath $UnityPath -ArgumentList $unityArgs -WorkingDirectory $Root -Wait -PassThru -WindowStyle Hidden
if ($proc.ExitCode -ne 0) {
    throw "Unity build failed with exit code $($proc.ExitCode). See $logPath"
}

$errors = Select-String -Path $logPath -Pattern "error CS|Scripts have compiler errors|Compiler errors|BUILD GL FAILED" -ErrorAction SilentlyContinue
if ($errors) {
    $first = $errors | Select-Object -First 1
    throw "Unity build log contains compile/build errors: $($first.Line). See $logPath"
}

foreach ($path in @(
    $expectedOutput,
    (Join-Path $OutputDir "HerUnity_Data"),
    (Join-Path $OutputDir "UnityPlayer.so")
)) {
    if (-not (Test-Path $path)) {
        throw "Expected build artifact missing: $path"
    }
}

Write-Host "Unity Linux build ready: $expectedOutput" -ForegroundColor Green
