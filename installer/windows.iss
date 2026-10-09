#define AppName "Claude Usage Widget"
#define AppVersion "0.12.5-codex"
#define AppExe "ClaudeUsageWidget.exe"

[Setup]
AppId={{6DCE80F1-6A2D-4A2D-A925-48C2D6D88D54}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\ClaudeUsageWidget
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=ClaudeUsageWidget-Setup-Windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible

[Files]
Source: "dist\ClaudeUsageWidget.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\setup_windows_config.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
; First configure before launch; preserving all user settings is essential.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\setup_windows_config.ps1"""; Flags: runhidden waituntilterminated; StatusMsg: "Enabling Claude and Codex providers..."
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
