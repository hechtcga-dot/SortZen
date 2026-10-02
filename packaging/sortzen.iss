; SortZen Windows installer (Inno Setup 6). Built by .github/workflows/windows-build.yml:
;   iscc /DAppVersion=0.1.0 packaging\sortzen.iss
; Installs for the current user (no administrator rights needed), adds a Start menu
; shortcut (and a desktop one if chosen) and an uninstaller. Uninstalling removes the
; program and keeps the user's settings, answers and choices in %LOCALAPPDATA%\SortZen.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{2B7D4E1A-5C3F-4A8B-9E6D-1F0C7A3B5D92}
AppName=SortZen
AppVersion={#AppVersion}
AppPublisher=SortZen
AppVerName=SortZen {#AppVersion}
DefaultDirName={localappdata}\Programs\SortZen
DefaultGroupName=SortZen
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SortZen-Setup-{#AppVersion}
SetupIconFile=sortzen.ico
UninstallDisplayIcon={app}\SortZen.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\SortZen\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SortZen"; Filename: "{app}\SortZen.exe"; IconFilename: "{app}\SortZen.exe"; AppUserModelID: "SortZen.SortZen.0"
Name: "{group}\SortZen README"; Filename: "{app}\README.txt"
Name: "{group}\Uninstall SortZen"; Filename: "{uninstallexe}"
Name: "{app}\Uninstall SortZen"; Filename: "{uninstallexe}"; Comment: "Uninstall SortZen (your files are never touched)"
Name: "{autodesktop}\SortZen"; Filename: "{app}\SortZen.exe"; IconFilename: "{app}\SortZen.exe"; AppUserModelID: "SortZen.SortZen.0"; Tasks: desktopicon

[Run]
Filename: "{app}\SortZen.exe"; Description: "Start SortZen"; Flags: nowait postinstall skipifsilent
