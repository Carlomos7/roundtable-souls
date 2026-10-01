# Release check on a clean Windows runner: the new Velopack setup over what users have now.
#
#   1. the latest published release installs silently (up to 3.13.2: the Inno Setup install)
#   2. a settings file and a backup are put in the data folder (%LOCALAPPDATA%\RoundtableSouls)
#   3. this build's setup installs silently; the launcher is started (offscreen) and, finding the Inno install,
#      removes it: no Inno uninstall entry or program left, the data untouched, the Start menu shortcut pointing at
#      the new copy's stub
#   4. the Velopack uninstaller removes the program and its uninstall entry, and leaves the data folder alone
#
# Updates, failed-start rollback and portable copies are covered by the isolated end-to-end runs the maintainer
# does before a release (they need several builds and a test signing key); this checks what only a clean machine
# with the real app ID can.
#
# Run from the repository root after scripts/build.py:  pwsh scripts/ci/velopack-install-test.ps1
$ErrorActionPreference = 'Stop'

$pack = 'Carlomos7.RoundtableSouls'
$title = 'Roundtable Souls'
$innoKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B8463238-E9B5-4FD4-AEB5-A537E4B53D8E}_is1'
$vpKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$pack"
$work = Join-Path $env:RUNNER_TEMP 'install-test'
$install = Join-Path $work 'install'
$data = Join-Path $env:LOCALAPPDATA 'RoundtableSouls'
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) "$title.lnk"
New-Item -ItemType Directory -Force $work | Out-Null

function Fail([string] $message) {
    Write-Host "::error::$message"
    exit 1
}

function Wait-Until([scriptblock] $condition, [int] $seconds) {
    foreach ($i in 1..($seconds * 2)) {
        if (& $condition) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Shortcut-Target([string] $lnk) {
    if (-not (Test-Path $lnk)) { return '' }
    return (New-Object -ComObject WScript.Shell).CreateShortcut($lnk).TargetPath
}

# 1. what users have now
gh release download --repo $env:GITHUB_REPOSITORY --pattern 'RoundtableSouls-Setup.exe' --dir (Join-Path $work 'prev') --clobber
$prevSetup = Join-Path $work 'prev\RoundtableSouls-Setup.exe'
$wasInno = $false
$p = Start-Process $prevSetup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$work\prev.log" -Wait -PassThru
if (Test-Path $innoKey) {
    $wasInno = $true
    $oldDir = (Get-ItemProperty $innoKey).InstallLocation
    Write-Host "previous release: Inno install $((Get-ItemProperty $innoKey).DisplayVersion) in $oldDir"
} else {
    Write-Host 'previous release is not an Inno install (exit code ' $p.ExitCode '); migration not exercised'
    Get-Process | Where-Object { $_.Path -and $_.Path -like "$env:LOCALAPPDATA\$pack\*" } | Stop-Process -Force
}

# 2. data that must survive
New-Item -ItemType Directory -Force (Join-Path $data 'backups') | Out-Null
Set-Content -Path (Join-Path $data 'launcher_settings.json') -Value '{"install_test_marker": "kept"}' -Encoding utf8NoBOM
Set-Content -Path (Join-Path $data 'backups\backup.txt') -Value 'a backup'

# 3. this build
$p = Start-Process 'dist/share/RoundtableSouls-Setup.exe' -ArgumentList '--silent', '--installto', $install -Wait -PassThru
if ($p.ExitCode -ne 0) { Fail "the setup exited with $($p.ExitCode)" }
$stub = Join-Path $install "$title.exe"
if (-not (Test-Path $stub) -or -not (Test-Path $vpKey)) { Fail 'the setup did not install the stub or its uninstall entry' }
Start-Sleep -Seconds 3
Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($install, 'OrdinalIgnoreCase') } | Stop-Process -Force
$app = Start-Process $stub -PassThru
if ($wasInno) {
    $migrated = Wait-Until { (Get-Content -Raw (Join-Path $data 'launcher_settings.json') | ConvertFrom-Json).inno_migration.done } 180
    $record = (Get-Content -Raw (Join-Path $data 'launcher_settings.json') | ConvertFrom-Json).inno_migration
    Write-Host "migration record: $($record | ConvertTo-Json -Compress)"
    if (-not $migrated) { Fail 'the launcher did not finish moving from the Inno install' }
    if (Test-Path $innoKey) { Fail 'the Inno uninstall entry is still there' }
    if (Test-Path (Join-Path $oldDir 'RoundtableSouls.exe')) { Fail 'the old program is still there' }
    if ((Shortcut-Target $startMenu) -ine $stub) { Fail "the Start menu shortcut points at '$(Shortcut-Target $startMenu)'" }
} else {
    Start-Sleep -Seconds 15
}
Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($install, 'OrdinalIgnoreCase') } | Stop-Process -Force
$settings = Get-Content -Raw (Join-Path $data 'launcher_settings.json') | ConvertFrom-Json
if ($settings.install_test_marker -ne 'kept') { Fail 'the settings file lost its contents' }
if (-not (Test-Path (Join-Path $data 'backups\backup.txt'))) { Fail 'a backup was lost' }
Write-Host 'installed; data kept'

# 4. uninstall keeps the data
$p = Start-Process (Join-Path $install 'Update.exe') -ArgumentList 'uninstall', '--silent' -Wait -PassThru
if (-not (Wait-Until { -not (Test-Path $stub) } 60)) { Fail 'the uninstaller left the program' }
if (Test-Path $vpKey) { Fail 'the uninstall entry is still there' }
if (-not (Test-Path (Join-Path $data 'backups\backup.txt'))) { Fail 'the uninstaller removed the data folder' }
Write-Host 'uninstalled; data kept'
