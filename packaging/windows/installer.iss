; Inno Setup script for Rit Downloader.  Compile:  ISCC /DAppVersion=1.0.0 installer.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef Publisher
  #define Publisher "Rit Downloader"
#endif
#define AppName "Rit Downloader"
#define AppExe "RitDownloader.exe"
#define Root "..\.."

[Setup]
; Never change AppId: it is how Windows recognises upgrades of the same app.
AppId={{9C8DE266-220A-4B66-B961-AD9F066A555B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user without admin rights; offers "all users" when run as admin.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Root}\build\installer
OutputBaseFilename=RitDownloader-Setup-Windows
SetupIconFile={#Root}\app\static\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
LicenseFile={#Root}\packaging\LICENSE.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start automatically when I sign in to Windows (runs quietly in the tray)"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "{#Root}\build\dist\RitDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Root}\extension\*"; DestDir: "{app}\browser-extension"; Flags: ignoreversion recursesubdirs
Source: "{#Root}\packaging\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} browser extension folder"; Filename: "{app}\browser-extension"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--no-browser"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[Code]
procedure StopRunningApp();
var Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(400);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningApp();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    { SuppressibleMsgBox: silent uninstalls (/SUPPRESSMSGBOXES) answer "No" and keep the data }
    if SuppressibleMsgBox('Also remove your Rit Downloader settings and download history?' + #13#10 +
              '(Your downloaded videos and audio are NOT deleted.)', mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      DelTree(ExpandConstant('{localappdata}\RitDownloader'), True, True, True);
end;
