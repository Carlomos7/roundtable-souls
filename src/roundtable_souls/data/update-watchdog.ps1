# Roundtable Souls update watchdog (Windows). The launcher copies this script to its data folder and starts it,
# hidden, just before Velopack applies an update; it outlives the launcher, which exits so the update can happen.
#
#   1. wait until Velopack has applied $Version (current\sq.version names it), at most $WaitApply seconds;
#   2. give that version $WaitReady seconds to write $State\ready-$Version (its window is up, or a Play from a
#      Steam shortcut is under way);
#   3. otherwise: stop what is left of it, delete its packages (Velopack would apply them again at the next
#      start), write $State\rollback.json and re-apply $Package, the kept full package of the previous version.
#      Update.exe then starts that version, which reports the rollback and stops offering $Version.
param(
    [Parameter(Mandatory)] [string] $Root,
    [Parameter(Mandatory)] [string] $Version,
    [Parameter(Mandatory)] [string] $Package,
    [Parameter(Mandatory)] [string] $State,
    [int] $WaitApply = 600,
    [int] $WaitReady = 90
)
$ErrorActionPreference = 'Continue'
$log = Join-Path $State 'watchdog.log'

function Say([string] $message) {
    Add-Content -Path $log -Value ('{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message)
}

function Installed-Version {
    $file = Join-Path $Root 'current\sq.version'
    if (Test-Path $file) {
        $text = Get-Content -Raw -Path $file -ErrorAction SilentlyContinue
        if ($text -match '<version>([^<]+)</version>') { return $Matches[1] }
    }
    return ''
}

Say "waiting for Velopack to apply $Version in $Root"
$deadline = (Get-Date).AddSeconds($WaitApply)
while ((Installed-Version) -ne $Version) {
    if ((Get-Date) -gt $deadline) {
        Say "$Version was not applied within $WaitApply s; nothing to undo"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

Say "$Version applied; waiting up to $WaitReady s for it to report ready"
$ready = Join-Path $State "ready-$Version"
$deadline = (Get-Date).AddSeconds($WaitReady)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $ready) {
        Say "$Version is ready"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

Say "$Version did not report ready; putting the previous version back from $Package"
$current = Join-Path $Root 'current'
Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($current, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path (Join-Path $Root 'packages') -Filter "*-$Version-*.nupkg" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
$record = [ordered]@{
    version = $Version
    reason  = "it did not finish starting within $WaitReady seconds"
    when    = (Get-Date).ToString('o')
}
Set-Content -Path (Join-Path $State 'rollback.json') -Value ($record | ConvertTo-Json) -Encoding UTF8
& (Join-Path $Root 'Update.exe') apply --silent --package $Package
Say "Update.exe apply exited $LASTEXITCODE"
