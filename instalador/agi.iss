; Inno Setup: AGI installer for Windows (x64).
; Built after PyInstaller:  ISCC /DVersion=0.3 instalador\agi.iss
#ifndef Version
  #define Version "0.3"
#endif

[Setup]
AppId={{630D66A5-89DF-4733-B15A-8E856047A4F6}
AppName=AGI
AppVersion={#Version}
AppVerName=AGI {#Version}
AppPublisher=AGI (open project)
AppPublisherURL=https://github.com/JulianRodriguezETH
LicenseFile=..\LICENSE
DefaultDirName={autopf}\AGI
DefaultGroupName=AGI
DisableProgramGroupPage=yes
OutputDir=salida
OutputBaseFilename=AGI-{#Version}-setup
SetupIconFile=..\icono\agi.ico
UninstallDisplayIcon={app}\AGI.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=admin
; User data (%APPDATA%\GanaderiaDron) is NOT touched when updating or uninstalling.

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "escritorio"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\AGI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AGI"; Filename: "{app}\AGI.exe"
Name: "{autodesktop}\AGI"; Filename: "{app}\AGI.exe"; Tasks: escritorio

[Run]
Filename: "{app}\AGI.exe"; Description: "Open AGI"; Flags: nowait postinstall skipifsilent
