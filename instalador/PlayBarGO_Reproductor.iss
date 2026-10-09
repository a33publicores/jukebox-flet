; Inno Setup 6 - instalador del reproductor PlayBar GO
; La versión la pone construir_exe.py (/DVersion=...) leyendo reproductor\version.py.
#ifndef Version
  #define Version "1.1.0"
#endif

[Setup]
AppId={{6F2B0C1E-7A41-4D58-9B3A-0A1B2C3D4E5F}
AppName=PlayBar GO Reproductor
AppVersion={#Version}
AppVerName=PlayBar GO Reproductor {#Version}
VersionInfoVersion={#Version}
AppPublisher=PlayBar GO
DefaultDirName={autopf}\PlayBar GO Reproductor
DefaultGroupName=PlayBar GO
OutputBaseFilename=PlayBarGO_Reproductor_Setup
SetupIconFile=playbargo.ico
UninstallDisplayIcon={app}\PlayBarGO_Reproductor.exe
Compression=lzma2
SolidCompression=yes
; Sin pedir administrador: así la actualización automática se instala sola, en silencio.
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
; Al actualizar: cierra el reproductor si sigue abierto y conserva las opciones elegidas
; (acceso directo, arranque con Windows).
CloseApplications=force
RestartApplications=no
UsePreviousTasks=yes

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; Flags: checkedonce
Name: "autoinicio"; Description: "Abrir automáticamente al iniciar sesión en Windows"; Flags: unchecked

[Files]
; Programa completo (modo carpeta). Sin credenciales de Google: el bar entra con su llave.
; El código y la llave del bar NO están aquí (están en %USERPROFILE%\PlayBarGo), por eso
; sobreviven a las actualizaciones.
Source: "..\dist\PlayBarGO_Reproductor\*"; DestDir: "{app}"; Excludes: "credenciales.json"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Quita librerías de la versión anterior que ya no se usan.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\PlayBar GO Reproductor"; Filename: "{app}\PlayBarGO_Reproductor.exe"
Name: "{autodesktop}\PlayBar GO Reproductor"; Filename: "{app}\PlayBarGO_Reproductor.exe"; Tasks: desktopicon
Name: "{userstartup}\PlayBar GO Reproductor"; Filename: "{app}\PlayBarGO_Reproductor.exe"; Tasks: autoinicio

[Run]
; Instalación normal: casilla "Abrir el reproductor" al final.
Filename: "{app}\PlayBarGO_Reproductor.exe"; Description: "Abrir el reproductor"; Flags: nowait postinstall skipifsilent
; Actualización automática (el reproductor llama al instalador con /RELANZAR): se abre solo.
Filename: "{app}\PlayBarGO_Reproductor.exe"; Flags: nowait; Check: EsActualizacion

[Code]
function EsActualizacion: Boolean;
begin
  Result := Pos('/RELANZAR', UpperCase(GetCmdTail)) > 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Codigo: Integer;
begin
  { Cierra el reproductor y su ventana (flet.exe) si siguen abiertos desde esta carpeta,
    para poder reemplazar los archivos. }
  if DirExists(ExpandConstant('{app}')) then
  begin
    Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process | Where-Object { $_.Path -like ''' +
      ExpandConstant('{app}') + '\*'' } | Stop-Process -Force"',
      '', SW_HIDE, ewWaitUntilTerminated, Codigo);
    Sleep(1500);
  end;
  Result := '';
end;
