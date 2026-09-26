; Instalador de Farmadex (Inno Setup 6).
; Se compila desde empaquetado\construir.ps1, que pasa la version con /DVersionApp.
; Instala por usuario: no pide administrador.

#ifndef VersionApp
  #define VersionApp "0.1.0"
#endif

#define NombreApp "Farmadex"
#define Raiz ".."

[Setup]
AppId={{9E2B7C41-5B1A-4F0E-9E1E-FARMADEX0001}
AppName={#NombreApp}
AppVersion={#VersionApp}
AppPublisher=Proyecto Farmadex
DefaultDirName={localappdata}\Programs\{#NombreApp}
DefaultGroupName={#NombreApp}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#Raiz}\dist
OutputBaseFilename={#NombreApp}-{#VersionApp}-setup
SetupIconFile={#Raiz}\recursos\iconos\farmadex.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "inicio"; Description: "Abrir {#NombreApp} al iniciar Windows"; GroupDescription: "Arranque:"; Flags: unchecked

[Files]
Source: "{#Raiz}\dist\{#NombreApp}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Runtime de Visual C++: lo necesitan Qt y ONNX Runtime. Se instala solo si falta.
Source: "{#Raiz}\empaquetado\vc_redist.x64.exe"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist; Check: FaltaVCRedist

[InstallDelete]
; Las librerias de la version anterior se quitan antes de copiar las nuevas: sin esto
; se iban acumulando DLL y modulos que ya no usa nadie de version en version. Los datos
; del usuario (indice, objetivos, ajustes) viven en %LOCALAPPDATA%\Farmadex, no aqui.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#NombreApp}"; Filename: "{app}\{#NombreApp}.exe"
Name: "{autodesktop}\{#NombreApp}"; Filename: "{app}\{#NombreApp}.exe"; Tasks: escritorio

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "{#NombreApp}"; ValueData: """{app}\{#NombreApp}.exe"""; Flags: uninsdeletevalue; Tasks: inicio

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \
  StatusMsg: "Instalando el runtime de Visual C++..."; Check: FaltaVCRedist; Flags: skipifdoesntexist waituntilterminated
Filename: "{app}\{#NombreApp}.exe"; Description: "Abrir {#NombreApp}"; Flags: nowait postinstall skipifsilent
; Actualizacion automatica lanzada por el propio Farmadex (/SILENT /AUTOACTUALIZAR=1):
; la entrada de arriba se salta con skipifsilent (vale para /SILENT y /VERYSILENT),
; asi que esta vuelve a abrir el programa.
Filename: "{app}\{#NombreApp}.exe"; Flags: nowait; Check: EsActualizacionAutomatica

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Mutex que crea Farmadex al arrancar (actualizador/instalacion.py). Con AppMutex en
// [Setup] el modo silencioso abortaria sin mas; aqui se le pide que se cierre y se espera.
const
  MutexFarmadex = 'FarmadexEnEjecucion';
  // Tuberia de instancia unica (farmadex/instancia_unica.py): Farmadex se cierra solo,
  // guardando lo suyo, si recibe la linea "salir". Mismo nombre que nombre_tuberia().
  PrefijoTuberia = '\\.\pipe\Farmadex-instancia-';
  GENERIC_WRITE = $40000000;
  OPEN_EXISTING = 3;

function CreateFileW(lpFileName: String; dwDesiredAccess, dwShareMode, lpSecurityAttributes,
  dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile: Cardinal): Integer;
  external 'CreateFileW@kernel32.dll stdcall';
function WriteFile(hFile: Integer; const lpBuffer: AnsiString; nNumberOfBytesToWrite: Cardinal;
  var lpNumberOfBytesWritten: Cardinal; lpOverlapped: Cardinal): Boolean;
  external 'WriteFile@kernel32.dll stdcall';
function CloseHandle(hObject: Integer): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

// Pide al Farmadex abierto que se cierre por las buenas. True si el mensaje llego;
// False si no hay ninguno escuchando (cerrado, o una version anterior sin tuberia).
function PedirCierreFarmadex: Boolean;
var
  tuberia: Integer;
  escritos: Cardinal;
  orden: AnsiString;
begin
  Result := False;
  tuberia := CreateFileW(PrefijoTuberia + GetUserNameString, GENERIC_WRITE, 0, 0, OPEN_EXISTING, 0, 0);
  if (tuberia = 0) or (tuberia = -1) then
    Exit;
  orden := 'salir' + #10;
  Result := WriteFile(tuberia, orden, Length(orden), escritos, 0);
  CloseHandle(tuberia);
  if Result then
    Log('Se ha pedido a Farmadex que se cierre para poder actualizar.');
end;

// Actualizacion lanzada por el propio Farmadex: sin asistente y se vuelve a abrir al acabar.
function EsActualizacionAutomatica: Boolean;
begin
  Result := ExpandConstant('{param:AUTOACTUALIZAR|0}') = '1';
end;

// Antes de copiar nada, Farmadex tiene que estar cerrado del todo (proceso incluido):
// se le pide por su tuberia que se cierre y se le dan hasta 60 s para soltar sus
// ficheros (cerrar los hilos de captura, comparador y mercado puede llevar varios
// segundos cada uno). Vale igual para la actualizacion automatica (Farmadex ya se
// esta cerrando solo) que para quien abre el instalador a mano con Farmadex abierto.
// Si sigue abierto no se copia nada a medias: se aborta, y en la automatica el
// envoltorio que lanzo el setup vuelve a abrir la version que habia.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  espera: Integer;
  pedido: Boolean;
begin
  Result := '';
  if not CheckForMutexes(MutexFarmadex) then
    Exit;
  pedido := PedirCierreFarmadex;
  if (not pedido) and (not EsActualizacionAutomatica) and (not WizardSilent) then
  begin
    // Una version anterior, sin tuberia: hay que cerrarla a mano.
    while CheckForMutexes(MutexFarmadex) do
      if MsgBox('Farmadex esta abierto. Cierralo (icono junto al reloj, boton derecho, Salir) y pulsa Aceptar.',
                mbInformation, MB_OKCANCEL) = IDCANCEL then
        Break;
  end;
  espera := 0;
  while CheckForMutexes(MutexFarmadex) and (espera < 120) do
  begin
    Sleep(500);
    espera := espera + 1;
  end;
  if CheckForMutexes(MutexFarmadex) then
  begin
    // Esta linea la busca Farmadex al arrancar (instalacion.MARCA_OTRA_INSTANCIA) para
    // no dar la version por fallida: se reintenta al cerrar el ultimo Farmadex.
    Log('Farmadex sigue abierto: no se puede actualizar. Se reintentara al cerrar el ultimo Farmadex.');
    Result := 'Farmadex sigue abierto: cierralo desde el icono junto al reloj (Salir) y vuelve a abrir el instalador.';
  end;
end;

function FaltaVCRedist: Boolean;
var
  instalado: Cardinal;
begin
  Result := not (
    RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
                       'Installed', instalado) and (instalado = 1));
end;

// Al desinstalar se pregunta si borrar los datos (indice, objetivos, ajustes).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  datos: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    datos := ExpandConstant('{localappdata}\{#NombreApp}');
    if DirExists(datos) then
      if MsgBox('Borrar tambien tus datos de {#NombreApp} (objetivos, ajustes y el indice descargado)?',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(datos, True, True, True);
  end;
end;
