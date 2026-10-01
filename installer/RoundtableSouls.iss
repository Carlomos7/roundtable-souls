; Roundtable Souls installer (Inno Setup 6). Built by scripts/build.py:
;   ISCC /DAppVersion=3.14.0 installer\RoundtableSouls.iss
; Per-user install, no administrator prompt. Settings live in %LOCALAPPDATA%\RoundtableSouls and are never removed
; by an update or an uninstall.
;
; Silent update, as the launcher's Update now runs it (updates.installer_args):
;   RoundtableSouls-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS
;                             /DIR=<this copy's folder> /LOG=<data folder>\logs\setup-<time>.log /RELAUNCH=1
; With /RELAUNCH=1 the launcher is reopened when the setup ends: the new version after an install, the version
; already there when the setup fails or refuses, so the launcher can always say how the update went.
;
; The setup does not run while the launcher window or a Play from a Steam shortcut is open (AppMutex: the names
; system/instance.py holds), and the launcher waits while a setup runs (SetupMutex). A silent setup never installs
; an older version over a newer one; the wizard asks first.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Roundtable Souls"
#define AppExe "RoundtableSouls.exe"
#define AppUrl "https://github.com/Carlomos7/roundtable-souls"
#define AppIdGuid "B8463238-E9B5-4FD4-AEB5-A537E4B53D8E"

[Setup]
AppId={{{#AppIdGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Carlomos7
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
AppMutex=RoundtableSouls.Window,RoundtableSouls.Play
SetupMutex=RoundtableSouls.Setup
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
UsePreviousAppDir=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
SetupIconFile=..\src\roundtable_souls\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\dist\share
OutputBaseFilename=RoundtableSouls-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[InstallDelete]
; Left by a portable-style update in this folder (a parked or failed program); the setup's copy replaces both.
Type: files; Name: "{app}\RoundtableSouls.old.exe"
Type: files; Name: "{app}\RoundtableSouls.failed.exe"

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\How to use.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchAfterUpdate

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppIdGuid}}_is1';

var
  Installed: Boolean;

function RelaunchWanted: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

function RelaunchAfterUpdate: Boolean;
begin
  Result := RelaunchWanted;
  if Result then
    Log('Roundtable Souls: installed; reopening the launcher.');
end;

{ The leading numbers of a version: '3.14.0-rc.1' -> '3.14.0'. }
function NumericPart(V: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to Length(V) do
  begin
    if ((V[I] >= '0') and (V[I] <= '9')) or (V[I] = '.') then
      Result := Result + V[I]
    else
      Break;
  end;
end;

function NextPart(var S: String): Integer;
var
  P: Integer;
begin
  P := Pos('.', S);
  if P = 0 then
  begin
    Result := StrToIntDef(S, 0);
    S := '';
  end
  else
  begin
    Result := StrToIntDef(Copy(S, 1, P - 1), 0);
    Delete(S, 1, P);
  end;
end;

{ 1 when A is newer than B, -1 when older, 0 when the numbers are the same (pre-release marks are ignored). }
function CompareVersions(A, B: String): Integer;
var
  I, X, Y: Integer;
begin
  A := NumericPart(A);
  B := NumericPart(B);
  Result := 0;
  for I := 1 to 4 do
  begin
    X := NextPart(A);
    Y := NextPart(B);
    if X > Y then
    begin
      Result := 1;
      Exit;
    end;
    if X < Y then
    begin
      Result := -1;
      Exit;
    end;
  end;
end;

function InstalledValue(Name: String): String;
begin
  Result := '';
  if not RegQueryStringValue(HKCU, UninstallKey, Name, Result) then
    RegQueryStringValue(HKLM, UninstallKey, Name, Result);
end;

function InitializeSetup(): Boolean;
var
  Old: String;
begin
  Result := True;
  Old := InstalledValue('DisplayVersion');
  if (Old <> '') and (CompareVersions(Old, '{#AppVersion}') > 0) then
  begin
    Log(Format('Roundtable Souls: a newer version (%s) is installed; refusing %s.', [Old, '{#AppVersion}']));
    if WizardSilent then
      Result := False
    else
      Result := MsgBox(Format('{#AppName} %s is installed, which is newer than this setup (%s).'#13#10#13#10 +
        'Install the older version anyway?', [Old, '{#AppVersion}']), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    Installed := True;
end;

{ A silent update that did not install (refused, a file in use, cancelled) reopens the version that is there, so the
  launcher shows what happened instead of simply disappearing. }
procedure DeinitializeSetup();
var
  Dir, Exe: String;
  Code: Integer;
begin
  if Installed or not RelaunchWanted then
    Exit;
  Dir := ExpandConstant('{param:DIR|}');
  if Dir = '' then
    Dir := RemoveBackslashUnlessRoot(InstalledValue('InstallLocation'));
  Exe := AddBackslash(Dir) + '{#AppExe}';
  if (Dir <> '') and FileExists(Exe) then
  begin
    Log('Roundtable Souls: the update did not install; reopening the version already there.');
    Exec(Exe, '', Dir, SW_SHOWNORMAL, ewNoWait, Code);
  end;
end;
