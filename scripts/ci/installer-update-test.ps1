# Release check on a clean Windows runner: install the latest published release, then update it with this build's
# setup exactly the way Update now runs it (updates.installer_args), and check what a user would notice.
#
#   1. the previous release installs silently
#   2. this build updates it: exit code 0, the new version registered, the settings file kept, a log written
#   3. an older setup is refused silently (the downgrade guard) and leaves the new version in place
#   4. a refused silent update reopens the installed launcher (so the launcher can report what happened)
#   5. the uninstaller removes the program and keeps the settings
#
# Run from the repository root after scripts/build.py:  pwsh scripts/ci/installer-update-test.ps1
param(
    [string] $NewSetup = 'dist/share/RoundtableSouls-Setup.exe'
)
$ErrorActionPreference = 'Stop'

$work = Join-Path $env:RUNNER_TEMP 'update-test'
$app = Join-Path $work 'app'
$exe = Join-Path $app 'RoundtableSouls.exe'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B8463238-E9B5-4FD4-AEB5-A537E4B53D8E}_is1'
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
New-Item -ItemType Directory -Force $work | Out-Null

function Fail([string] $message) {
    Write-Host "::error::$message"
    exit 1
}

function Invoke-Setup([string] $setup, [string[]] $arguments) {
    Write-Host "> $setup $($arguments -join ' ')"
    $p = Start-Process -FilePath $setup -ArgumentList $arguments -Wait -PassThru
    return $p.ExitCode
}

function Get-InstalledVersion {
    $item = Get-ItemProperty -Path $uninstallKey -ErrorAction SilentlyContinue
    if ($item) { return $item.DisplayVersion }
    return ''
}

function Get-UpdateArgs([string] $log, [bool] $relaunch) {
    # no quote characters inside: they would need escaping on their way to python.exe
    $py = 'import json, sys; from roundtable_souls.updates import installer_args; ' +
        'print(json.dumps(installer_args(sys.argv[1], sys.argv[2], relaunch=bool(int(sys.argv[3])))))'
    $json = uv run --locked python -c $py $app $log ([int] $relaunch)
    return [string[]] ($json | ConvertFrom-Json)
}

$version = uv run --locked python -c 'import roundtable_souls; print(roundtable_souls.__version__)'  # = pyproject's
if (-not (Test-Path $NewSetup)) { Fail "no setup at $NewSetup" }
if (-not $iscc) { Fail 'Inno Setup is not installed' }

# 1. the latest published release
gh release download --repo $env:GITHUB_REPOSITORY --pattern 'RoundtableSouls-Setup.exe' --dir (Join-Path $work 'prev') --clobber
$code = Invoke-Setup (Join-Path $work 'prev\RoundtableSouls-Setup.exe') @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$app", "/LOG=$work\prev.log")
if ($code -ne 0 -or -not (Test-Path $exe)) { Fail "the previous release did not install (exit code $code)" }
$previous = Get-InstalledVersion
Write-Host "previous release installed: $previous"

$data = Join-Path $env:LOCALAPPDATA 'RoundtableSouls'
New-Item -ItemType Directory -Force $data | Out-Null
$settings = Join-Path $data 'launcher_settings.json'
Set-Content -Path $settings -Value '{"update_test_marker": "keep me"}' -Encoding utf8NoBOM

# 2. this build, the way Update now runs it (without reopening: the runner has no one to look at it)
$log = Join-Path $work 'update.log'
$code = Invoke-Setup $NewSetup (Get-UpdateArgs $log $false)
if ($code -ne 0) { Fail "the update exited with $code; see $log" }
if ((Get-InstalledVersion) -ne $version) { Fail "registered version is '$(Get-InstalledVersion)', expected $version" }
if (-not (Test-Path $log) -or (Get-Item $log).Length -eq 0) { Fail 'the update wrote no log' }
if (-not (Select-String -Path $settings -Pattern 'keep me' -Quiet)) { Fail 'the update lost the settings file' }
Write-Host "updated $previous -> $version"

# 3. an older setup is refused when silent
& $iscc /Q '/DAppVersion=0.0.1' "/O$work\old" installer\RoundtableSouls.iss
if ($LASTEXITCODE -ne 0) { Fail 'could not build the old-version setup' }
$oldSetup = Join-Path $work 'old\RoundtableSouls-Setup.exe'
$downLog = Join-Path $work 'downgrade.log'
$code = Invoke-Setup $oldSetup (Get-UpdateArgs $downLog $false)
if ($code -eq 0) { Fail 'a silent downgrade was not refused' }
if ((Get-InstalledVersion) -ne $version) { Fail 'the refused downgrade changed the registered version' }
if (-not (Select-String -Path $downLog -Pattern 'newer version' -Quiet)) { Fail 'the downgrade log does not say why' }
Write-Host "downgrade to 0.0.1 refused (exit code $code)"

# 4. a silent update that did not install reopens the launcher that is there
$code = Invoke-Setup $oldSetup (Get-UpdateArgs (Join-Path $work 'relaunch.log') $true)
$reopened = $null
foreach ($i in 1..60) {
    $reopened = Get-Process -Name 'RoundtableSouls' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }
    if ($reopened) { break }
    Start-Sleep -Milliseconds 500
}
Get-Process -Name 'RoundtableSouls' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } |
    Stop-Process -Force -ErrorAction SilentlyContinue
if (-not $reopened) { Fail 'a refused silent update did not reopen the launcher' }
Write-Host 'the refused update reopened the installed launcher'
Start-Sleep -Seconds 2

# 5. uninstall keeps the settings
Start-Process -FilePath (Join-Path $app 'unins000.exe') -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
foreach ($i in 1..60) {
    if (-not (Test-Path $exe)) { break }
    Start-Sleep -Milliseconds 500
}
if (Test-Path $exe) { Fail 'the uninstaller left the program' }
if (-not (Test-Path $settings)) { Fail 'the uninstaller removed the settings' }
Write-Host 'uninstalled; settings kept'
