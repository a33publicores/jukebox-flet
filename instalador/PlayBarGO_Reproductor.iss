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
  Carpeta: String;
begin
  { Antes de copiar: el reproductor de ESTA instalación tiene que estar cerrado.
    1) se le dan hasta 10 s para cerrarse solo (cuando él mismo lanzó la actualización);
    2) si sigue abierto se cierra SOLO ese programa (sin /T: el instalador es hijo suyo
       y no debe cerrarse a sí mismo);
    3) la ventana (flet.exe) vive fuera de esta carpeta: se cierra por su título. }
  Carpeta := ExpandConstant('{app}');
  if DirExists(Carpeta) then
  begin
    Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -ExecutionPolicy Bypass -Command "' +
      '$p = Get-Process | Where-Object { $_.Path -like ''' + Carpeta + '\*'' }; ' +
      'if ($p) { $p | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue }; ' +
      'Get-Process | Where-Object { $_.Path -like ''' + Carpeta + '\*'' } | Stop-Process -Force -ErrorAction SilentlyContinue; ' +
      'Get-Process -Name flet -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like ''PlayBar GO*'' } | Stop-Process -Force"',
      '', SW_HIDE, ewWaitUntilTerminated, Codigo);
    Sleep(1000);
  end;
  Result := '';
end;
