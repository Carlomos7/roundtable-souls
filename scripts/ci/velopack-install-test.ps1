# Release check on a clean Windows runner: the new Velopack setup over what users have now.
#
#   1. the latest published release installs silently: up to 3.13.2 the Inno Setup install, from 3.14.0 a
#      Velopack install (with --silent into the folder this build then installs over, as an update by setup would)
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
# Every program it starts is waited for on its own (not its child processes: a setup starts the launcher) and for a
# bounded time; one that does not finish fails the test, after the processes, window titles and installer logs are
# printed. Nothing is skipped and a timeout is never a pass.
#
# Run from the repository root after scripts/build.py:  pwsh scripts/ci/velopack-install-test.ps1
$ErrorActionPreference = 'Stop'

$pack = 'Carlomos7.RoundtableSouls'
$title = 'Roundtable Souls'
$innoKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B8463238-E9B5-4FD4-AEB5-A537E4B53D8E}_is1'
$vpKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$pack"
$started = Get-Date
$work = Join-Path $env:RUNNER_TEMP 'install-test'
$install = Join-Path $work 'install'
$data = Join-Path $env:LOCALAPPDATA 'RoundtableSouls'
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) "$title.lnk"
New-Item -ItemType Directory -Force $work | Out-Null

function Say([string] $message) {
    Write-Host "$(Get-Date -Format 'HH:mm:ss') $message"
}

function Show-Diagnostics {
    Say 'diagnostics: processes started by this test, and their parents'
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -match 'Roundtable|Setup|Update|unins|velopack' -or $_.CommandLine -match [regex]::Escape($work) } |
        ForEach-Object { Write-Host ("  pid {0} parent {1} {2}: {3}" -f $_.ProcessId, $_.ParentProcessId, $_.Name, $_.CommandLine) }
    Say 'diagnostics: windows open (a prompt waiting for an answer shows here)'
    Get-Process | Where-Object { $_.MainWindowTitle } |
        ForEach-Object { Write-Host ("  pid {0} {1}: '{2}'" -f $_.Id, $_.ProcessName, $_.MainWindowTitle) }
    Say 'diagnostics: installer logs'
    # logs written since this test started, from bounded places only (this test's folder and the install folder,
    # recursively; %TEMP% itself, not below it), newest first, at most 8
    # (only folders that exist, as literal paths: given a missing folder, Get-ChildItem -Recurse would search its parent)
    $deep = @($work, (Join-Path $env:LOCALAPPDATA $pack)) | Where-Object { Test-Path -LiteralPath $_ -PathType Container }
    $logs = @(@($deep | ForEach-Object { Get-ChildItem -LiteralPath $_ -Recurse -Depth 2 -File -Filter '*.log' `
                -ErrorAction SilentlyContinue }) + @(Get-ChildItem -LiteralPath $env:TEMP -File -Filter '*.log' `
            -ErrorAction SilentlyContinue) |
        Where-Object { $_.LastWriteTime -ge $started } | Sort-Object LastWriteTime -Descending | Select-Object -First 8)
    foreach ($log in $logs) {
        Write-Host "  --- $($log.FullName) (last 40 lines)"
        Get-Content $log.FullName -Tail 40 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
    }
}

function Fail([string] $message) {
    Write-Host "::error::$message"
    Show-Diagnostics
    exit 1
}

function Stop-Tree([int] $id) {
    & taskkill.exe /T /F /PID $id 2>&1 | ForEach-Object { Write-Host "  $_" }
}

function Invoke-Bounded([string] $file, [string[]] $arguments, [int] $seconds, [string] $what) {
    # Waits for this process only, never its children (a setup starts the launcher, which does not exit by itself).
    Say "start: $what"
    $proc = Start-Process $file -ArgumentList $arguments -PassThru
    $null = $proc.Handle  # keeps the exit code readable once it has exited
    if (-not $proc.WaitForExit($seconds * 1000)) {
        Write-Host "::error::$what did not finish within $seconds s"
        Show-Diagnostics
        Stop-Tree $proc.Id
        exit 1
    }
    Say "end: $what (exit code $($proc.ExitCode))"
    return $proc
}

function Stop-Launchers([string] $folder, [string] $why) {
    # A running launcher locks its files: the next setup or the uninstaller would wait on it (or ask).
    $running = @(Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($folder, 'OrdinalIgnoreCase') })
    if ($running) {
        Say "stopping $($running.Count) process(es) from $folder ($why): $(($running | ForEach-Object { "$($_.ProcessName) $($_.Id)" }) -join ', ')"
        $running | Stop-Process -Force
    }
    $gone = Wait-Until { -not @(Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($folder, 'OrdinalIgnoreCase') }) } 30
    if (-not $gone) { Fail "processes from $folder are still running ($why)" }
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
Say 'downloading the latest published release'
gh release download --repo $env:GITHUB_REPOSITORY --pattern 'RoundtableSouls-Setup.exe' --dir (Join-Path $work 'prev') --clobber
$prevSetup = Join-Path $work 'prev\RoundtableSouls-Setup.exe'
$prevTag = gh release view --repo $env:GITHUB_REPOSITORY --json tagName --jq '.tagName'
$prevAssets = @(gh release view --repo $env:GITHUB_REPOSITORY --json assets --jq '.assets[].name')
$prevIsVelopack = $prevAssets -contains 'releases.win.json'
Say "previous release: $prevTag ($(if ($prevIsVelopack) { 'Velopack' } else { 'Inno Setup' }) setup)"
$wasInno = $false
if ($prevIsVelopack) {
    # Velopack's setup ignores Inno's flags; without --silent it shows its window and starts the launcher
    $p = Invoke-Bounded $prevSetup @('--silent', '--installto', $install) 300 "the $prevTag setup"
    if ($p.ExitCode -ne 0) { Fail "the $prevTag setup exited with $($p.ExitCode)" }
    if (-not (Test-Path (Join-Path $install "$title.exe"))) { Fail "the $prevTag setup did not install into $install" }
    Stop-Launchers $install "started by the $prevTag setup"
} else {
    $p = Invoke-Bounded $prevSetup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$work\prev.log") 300 "the $prevTag setup"
    if (Test-Path $innoKey) {
        $wasInno = $true
        $oldDir = (Get-ItemProperty $innoKey).InstallLocation
        Say "previous release: Inno install $((Get-ItemProperty $innoKey).DisplayVersion) in $oldDir"
    } else {
        Fail "the $prevTag Inno setup (exit code $($p.ExitCode)) did not install"
    }
    Stop-Launchers (Join-Path $env:LOCALAPPDATA $pack) "started by the $prevTag setup"
}

# 2. data that must survive
New-Item -ItemType Directory -Force (Join-Path $data 'backups') | Out-Null
Set-Content -Path (Join-Path $data 'launcher_settings.json') -Value '{"install_test_marker": "kept"}' -Encoding utf8NoBOM
Set-Content -Path (Join-Path $data 'backups\backup.txt') -Value 'a backup'

# 3. this build
$p = Invoke-Bounded (Resolve-Path 'dist/share/RoundtableSouls-Setup.exe') @('--silent', '--installto', $install) 300 'this build''s setup'
if ($p.ExitCode -ne 0) { Fail "the setup exited with $($p.ExitCode)" }
$stub = Join-Path $install "$title.exe"
if (-not (Test-Path $stub) -or -not (Test-Path $vpKey)) { Fail 'the setup did not install the stub or its uninstall entry' }
Start-Sleep -Seconds 3
Stop-Launchers $install 'started by the setup'
Say 'starting the installed launcher'
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
Stop-Launchers $install 'the check is done'
$settings = Get-Content -Raw (Join-Path $data 'launcher_settings.json') | ConvertFrom-Json
if ($settings.install_test_marker -ne 'kept') { Fail 'the settings file lost its contents' }
if (-not (Test-Path (Join-Path $data 'backups\backup.txt'))) { Fail 'a backup was lost' }
Say 'installed; data kept'

# 4. uninstall keeps the data
$p = Invoke-Bounded (Join-Path $install 'Update.exe') @('uninstall', '--silent') 300 'the uninstaller'
if (-not (Wait-Until { -not (Test-Path $stub) } 60)) { Fail 'the uninstaller left the program' }
if (Test-Path $vpKey) { Fail 'the uninstall entry is still there' }
if (-not (Test-Path (Join-Path $data 'backups\backup.txt'))) { Fail 'the uninstaller removed the data folder' }
Say 'uninstalled; data kept'
