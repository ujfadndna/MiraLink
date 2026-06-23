$unityHubReleases = Join-Path $env:APPDATA "UnityHub\releases.json"
$j = Get-Content $unityHubReleases -Raw | ConvertFrom-Json
foreach ($r in $j.official) {
    if ($r.version -like '*6000.3.18*' -or $r.version -like '*6000.4.11*') {
        Write-Host "$($r.version) | $($r.changeset)"
    }
}
