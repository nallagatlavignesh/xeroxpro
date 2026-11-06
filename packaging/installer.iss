; Inno Setup script (free, https://jrsoftware.org/isinfo.php). Compile after packaging\build_windows.bat.
; The installer never touches the shop's data: records live in %LOCALAPPDATA%\XeroxPro and survive
; updates and even an uninstall.
#define AppName "XeroxPro"
#define AppVersion "0.1.0"

[Setup]
AppId={{6C1D6E55-4B0D-4C57-9B0E-3A5B6A8F7A11}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=XeroxPro-Setup-{#AppVersion}
SetupIconFile=..\resources\icons\xeroxpro.ico
UninstallDisplayIcon={app}\XeroxPro.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Files]
Source: "..\dist\XeroxPro\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\XeroxPro.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\XeroxPro.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Run]
Filename: "{app}\XeroxPro.exe"; Description: "Start XeroxPro"; Flags: nowait postinstall skipifsilent
