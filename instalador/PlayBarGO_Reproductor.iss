; Inno Setup 6 - instalador del reproductor PlayBar GO
#define Version "1.0.0"
[Setup]
AppId={{6F2B0C1E-7A41-4D58-9B3A-0A1B2C3D4E5F}
AppName=PlayBar GO Reproductor
AppVersion={#Version}
AppPublisher=PlayBar GO
DefaultDirName={autopf}\PlayBar GO Reproductor
DefaultGroupName=PlayBar GO
OutputBaseFilename=PlayBarGO_Reproductor_Setup
SetupIconFile=playbargo.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; Flags: checkedonce
Name: "autoinicio"; Description: "Abrir automáticamente al iniciar sesión en Windows"; Flags: unchecked

[Files]
Source: "..\dist\PlayBarGO_Reproductor.exe"; DestDir: "{app}"; Flags: ignoreversion
; credenciales.json se copia solo si existe junto a este script (no se sobrescribe al actualizar)
Source: "..\credenciales.json"; DestDir: "{app}"; Flags: onlyifdoesntexist skipifsourcedoesntexist

[Icons]
Name: "{group}\PlayBar GO Reproductor"; Filename: "{app}\PlayBarGO_Reproductor.exe"
Name: "{autodesktop}\PlayBar GO Reproductor"; Filename: "{app}\PlayBarGO_Reproductor.exe"; Tasks: desktopicon
Name: "{userstartup}\PlayBar GO Reproductor"; Filename: "{app}\PlayBarGO_Reproductor.exe"; Tasks: autoinicio

[Run]
Filename: "{app}\PlayBarGO_Reproductor.exe"; Description: "Abrir el reproductor"; Flags: nowait postinstall skipifsilent
