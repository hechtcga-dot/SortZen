; SortZen Windows installer (Inno Setup 6). Built by .github/workflows/windows-build.yml:
;   iscc /DAppVersion=0.3.0 packaging\sortzen.iss
; Installs for the current user (no administrator rights needed), adds a Start menu
; shortcut (and a desktop one if chosen) and an uninstaller. Uninstalling removes the
; program and asks whether to also remove the settings, answers, remembered results, move
; logs (%LOCALAPPDATA%\SortZen) and saved API keys. Sorted files are never touched.

#ifndef AppVersion
  #define AppVersion "0.3.0"
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

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if (not UninstallSilent) and (MsgBox('Also remove your SortZen settings?' + #13#10#13#10 +
              'This removes your folders list, answers, chosen destinations, remembered results, ' +
              'saved API keys and the move logs that Undo uses. Your files stay exactly where they are.' + #13#10#13#10 +
              'Choose No to keep them for a later install.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
    begin
      Exec(ExpandConstant('{app}\SortZen.exe'), '--remove-data', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      DelTree(ExpandConstant('{localappdata}\SortZen'), True, True, True);
    end;
  end;
end;
