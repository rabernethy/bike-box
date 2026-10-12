; Inno Setup script for the Bike Box Windows installer.
; The CI build runs PyInstaller first (dist\BikeBox\), then compiles this with
; iscc, passing /DAppVersion=<version>.  Produces BikeBox-Setup-<version>.exe.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppName=Bike Box
AppVersion={#AppVersion}
AppPublisher=Bike Box contributors
DefaultDirName={autopf}\Bike Box
DefaultGroupName=Bike Box
UninstallDisplayIcon={app}\BikeBox.exe
OutputDir=..\..\dist\installer
OutputBaseFilename=BikeBox-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
Source: "..\..\dist\BikeBox\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Bike Box"; Filename: "{app}\BikeBox.exe"
Name: "{group}\Uninstall Bike Box"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Bike Box"; Filename: "{app}\BikeBox.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Registry]
; associate .bikebox with the app
Root: HKCU; Subkey: "Software\Classes\.bikebox"; ValueType: string; ValueData: "BikeBox.Design"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\BikeBox.Design"; ValueType: string; ValueData: "Bike Box design"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\BikeBox.Design\DefaultIcon"; ValueType: string; ValueData: "{app}\BikeBox.exe,0"
Root: HKCU; Subkey: "Software\Classes\BikeBox.Design\shell\open\command"; ValueType: string; ValueData: """{app}\BikeBox.exe"" ""%1"""

[Run]
Filename: "{app}\BikeBox.exe"; Description: "Launch Bike Box"; Flags: nowait postinstall skipifsilent
