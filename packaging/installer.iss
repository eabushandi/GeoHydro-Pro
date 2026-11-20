; Inno Setup script for the GeoHydro Pro Windows installer.
; Built by packaging/build_windows.ps1 after PyInstaller has produced dist\GeoHydroPro.
;   iscc /DAppVersion=0.3.0 packaging\installer.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "GeoHydro Pro"
#define AppExe "GeoHydroPro.exe"

[Setup]
AppId={{6E1C3F0A-5B7D-4E7A-9C42-6D3B8F0E2A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; Installs for the current user without administrator rights by default;
; the user can choose an all-users install (needs administrator rights).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=GeoHydroPro-{#AppVersion}-Setup
SetupIconFile=geohydro.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "fileassoc"; Description: "Open .ghproj project files with {#AppName}"; GroupDescription: "File association:"

[Files]
Source: "..\dist\GeoHydroPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} (open sample project)"; Filename: "{app}\{#AppExe}"; Parameters: "--sample"
Name: "{autoprograms}\{#AppName} installation self-test"; Filename: "{app}\{#AppExe}"; Parameters: "--selftest --report ""{userdocs}\GeoHydroPro-selftest.txt"""
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.ghproj"; ValueType: string; ValueName: ""; ValueData: "GeoHydroPro.Project"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\GeoHydroPro.Project"; ValueType: string; ValueName: ""; ValueData: "GeoHydro Pro project"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\GeoHydroPro.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\GeoHydroPro.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: fileassoc

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--sample"; Description: "Start {#AppName} with the sample project"; Flags: nowait postinstall skipifsilent
