; Roundtable Souls installer (Inno Setup 6). Built by scripts/build.py:
;   ISCC /DAppVersion=3.2.0 installer\RoundtableSouls.iss
; Per-user install, no administrator prompt. Settings live in %LOCALAPPDATA%\RoundtableSouls and are never removed
; by an update or an uninstall.
;
; Silent update, as the launcher's Update now runs it:
;   RoundtableSouls-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RELAUNCH=1

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Roundtable Souls"
#define AppExe "RoundtableSouls.exe"
#define AppUrl "https://github.com/Carlomos7/roundtable-souls"

[Setup]
AppId={{B8463238-E9B5-4FD4-AEB5-A537E4B53D8E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Carlomos7
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
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
function RelaunchAfterUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;
