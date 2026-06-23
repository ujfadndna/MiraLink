$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root "workspace\run"

if (-not (Test-Path $RuntimeDir)) {
    Write-Host "No runtime directory: $RuntimeDir"
    return
}

Get-ChildItem -Path $RuntimeDir -Filter "*.pid" | ForEach-Object {
    $name = $_.BaseName
    $pidValue = [int](Get-Content $_.FullName -Raw)
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $pidValue -Force
        Write-Host "stopped $name pid=$pidValue"
    } else {
        Write-Host "$name pid=$pidValue not running"
    }
    Remove-Item $_.FullName -Force
}
