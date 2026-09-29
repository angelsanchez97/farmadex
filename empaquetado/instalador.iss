; Instalador de Farmadex (Inno Setup 6).
; Se compila desde empaquetado\construir.ps1, que pasa la version con /DVersionApp.
; Instala por usuario: no pide administrador.
;
; Instalacion a prueba de cortes: los ficheros nuevos se copian a {app}\_nuevo, sin tocar
; la version que ya hay. Solo cuando estan todos (se cuentan) y el Farmadex.exe nuevo arranca,
; se conmuta con renombrados: lo viejo pasa a {app}\_viejo y lo nuevo ocupa su sitio. Si algo
; falla (se cancela, se corta la luz, un fichero bloqueado, falta espacio...) la version
; anterior queda como estaba, y si el corte pilla justo en mitad de los renombrados, el
; siguiente arranque del instalador lo deshace (RecuperarConmutacionInterrumpida).
;
; Las definiciones de abajo se pueden cambiar al compilar (/DNombre=valor) para las pruebas
; del instalador: otro AppId, otro nombre y otra tuberia, sin tocar el Farmadex real.

#ifndef VersionApp
  #define VersionApp "0.1.0"
#endif
#ifndef NombreApp
  #define NombreApp "Farmadex"
#endif
#ifndef Raiz
  #define Raiz ".."
#endif
; Carpeta con lo que genera PyInstaller (Farmadex.exe y _internal).
#ifndef Origen
  #define Origen Raiz + "\dist\" + NombreApp
#endif
#ifndef IdApp
  #define IdApp "{{9E2B7C41-5B1A-4F0E-9E1E-FARMADEX0001}"
#endif
; Sufijo del mutex y la tuberia: vacio en la version real; las pruebas ponen el mismo que
; Farmadex calcula con FARMADEX_DATOS (instancia_unica._sufijo_datos).
#ifndef SufijoDatos
  #define SufijoDatos ""
#endif
#ifndef EsperaComprobacionMs
  #define EsperaComprobacionMs "90000"
#endif

; Cuantos ficheros y bytes lleva Origen, contados al compilar: al instalar se comprueba que
; en {app}\_nuevo esta todo antes de conmutar (una copia a medias no sustituye a nada).
#pragma parseroption -p-
; (Con -p- las cadenas llevan escapes de C: "\\" es una barra.) Modo 0 cuenta ficheros, 1 suma bytes.
#define ContarEn(str Carpeta, int Hallado, int Busqueda, int Modo) \
  Hallado \
    ? ( \
        Local[0] = FindGetFileName(Busqueda), \
        Local[1] = Carpeta + "\\" + Local[0], \
        (Local[0] == "." || Local[0] == "..") ? 0 : \
          (DirExists(Local[1]) ? Contar(Local[1], Modo) : (Modo == 0 ? 1 : FileSize(Local[1]))) \
      ) + ContarEn(Carpeta, FindNext(Busqueda), Busqueda, Modo) \
    : 0
#define Contar(str Carpeta, int Modo) \
  Local[0] = FindFirst(Carpeta + "\\*", faAnyFile), \
  Local[1] = ContarEn(Carpeta, Local[0], Local[0], Modo), \
  (Local[0] ? FindClose(Local[0]) : 0), \
  Local[1]
#pragma parseroption -p+
#define FicherosEsperados Contar(Origen, 0)
#define BytesEsperados Contar(Origen, 1)

[Setup]
AppId={#IdApp}
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
; A {app}\_nuevo, no a {app}: la version instalada no se toca hasta tener la nueva entera
; (se conmuta en CurStepChanged, ssPostInstall).
Source: "{#Origen}\*"; DestDir: "{app}\_nuevo"; Flags: ignoreversion recursesubdirs createallsubdirs
; Runtime de Visual C++: lo necesitan Qt y ONNX Runtime. Se instala solo si falta.
Source: "{#Raiz}\empaquetado\vc_redist.x64.exe"; DestDir: "{tmp}"; \
  Flags: deleteafterinstall skipifsourcedoesntexist; Check: FaltaVCRedist

[InstallDelete]
; Restos de una instalacion anterior que se corto a medias: se empieza de limpio. (Antes
; aqui se borraba {app}\_internal antes de copiar, y si la instalacion se cortaba el
; programa quedaba roto; ahora la carpeta vieja se sustituye entera al conmutar, con lo
; que tampoco se acumulan DLL de versiones anteriores.)
Type: filesandordirs; Name: "{app}\_nuevo"
; El fichero temporal que Inno Setup deja en la carpeta si se le mata a mitad de copia.
Type: files; Name: "{app}\is-*.tmp"

[Icons]
; IconFilename explicito: Windows cachea el icono por ruta+indice del .exe y, tras cambiar el
; icono del programa, el acceso directo seguia saliendo con el viejo. Apuntar al .ico lo refresca.
Name: "{group}\{#NombreApp}"; Filename: "{app}\{#NombreApp}.exe"; IconFilename: "{app}\_internal\recursos\iconos\farmadex.ico"
Name: "{autodesktop}\{#NombreApp}"; Filename: "{app}\{#NombreApp}.exe"; IconFilename: "{app}\_internal\recursos\iconos\farmadex.ico"; Tasks: escritorio

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "{#NombreApp}"; ValueData: """{app}\{#NombreApp}.exe"""; Flags: uninsdeletevalue; Tasks: inicio

[Run]
; El runtime de Visual C++ se instala desde el codigo (InstalarVCRedist), antes de probar
; el Farmadex.exe nuevo. (Aqui habia un "ie4uinit -show" para refrescar los iconos: en
; algun PC dejaba el Escritorio congelado un rato al actualizar. Lo sustituye el
; IconFilename explicito de [Icons].)
Filename: "{app}\{#NombreApp}.exe"; Description: "Abrir {#NombreApp}"; Flags: nowait postinstall skipifsilent
; La actualizacion automatica (/AUTOACTUALIZAR=1) vuelve a abrir Farmadex desde el codigo
; (RelanzarTrasActualizar), no desde aqui: las entradas de [Run] sin "postinstall" se
; ejecutan antes de ssPostInstall, cuando la version nueva aun no esta en su sitio.

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Mutex que crea Farmadex al arrancar (actualizador/instalacion.py). Con AppMutex en
// [Setup] el modo silencioso abortaria sin mas; aqui se le pide que se cierre y se espera.
const
  MutexFarmadex = 'FarmadexEnEjecucion{#SufijoDatos}';
  // Tuberia de instancia unica (farmadex/instancia_unica.py): Farmadex se cierra solo,
  // guardando lo suyo, si recibe la linea "salir". Mismo nombre que nombre_tuberia().
  PrefijoTuberia = '\\.\pipe\Farmadex-instancia{#SufijoDatos}-';
  GENERIC_WRITE = $40000000;
  OPEN_EXISTING = 3;
  // Lo que se copio en {app}\_nuevo y hay que tener entero antes de conmutar.
  FicherosEsperados = {#FicherosEsperados};
  BytesEsperados = '{#BytesEsperados}';
  // Frase que busca Farmadex en instalador.log (instalacion.MARCA_NO_COMPLETADA) para
  // contar por que no se actualizo. Va al principio de la linea del motivo.
  MarcaNoCompletada = 'No se ha podido completar la instalacion';
  // Cuanto se espera a que el Farmadex.exe nuevo conteste (--comprobar-rapidfuzz tarda
  // un par de segundos; el margen es para el antivirus mirando el .exe la primera vez).
  EsperaComprobacionMs = {#EsperaComprobacionMs};
  CodigoSinRespuesta = 99;

var
  // False si la version nueva no llego a ponerse (la anterior sigue intacta).
  Completada: Boolean;
  MotivoFallo: String;

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
    Log('Se ha pedido a Farmadex que se cierre (para instalar o desinstalar).');
end;

// Actualizacion lanzada por el propio Farmadex: sin asistente y se vuelve a abrir al acabar.
function EsActualizacionAutomatica: Boolean;
begin
  Result := ExpandConstant('{param:AUTOACTUALIZAR|0}') = '1';
end;

// Con que argumentos se vuelve a abrir Farmadex tras una actualizacion automatica.
function ArgumentosRelanzar(Param: String): String;
begin
  Result := '--tras-actualizar';
  if ExpandConstant('{param:BANDEJA|0}') = '1' then
    Result := Result + ' --bandeja';
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

// -- Instalacion a prueba de cortes -------------------------------------------------
//
// Los ficheros nuevos se copian a {app}\_nuevo ([Files]). En ssPostInstall se comprueba
// que esten todos y que el Farmadex.exe nuevo arranque, y solo entonces se conmuta:
//   1. se crea el diario {app}\_conmutacion.txt (vacio): "conmutacion en curso";
//   2. cada entrada vieja que se va a sustituir (Farmadex.exe, _internal...) pasa a {app}\_viejo;
//   3. cada entrada nueva se apunta en el diario y pasa de _nuevo a {app};
//   4. se borra el diario (a partir de aqui la version nueva es la buena) y luego _viejo y _nuevo.
// Si algo falla en 2 o 3 se deshace al momento. Si el proceso muere en mitad (apagon, lo
// matan), el diario sigue ahi y el siguiente instalador lo deshace antes de empezar.

function RutaApp(Nombre: String): String;
begin
  Result := AddBackslash(ExpandConstant('{app}')) + Nombre;
end;

function ExisteEntrada(Ruta: String): Boolean;
begin
  Result := FileExists(Ruta) or DirExists(Ruta);
end;

procedure BorrarEntrada(Ruta: String);
begin
  if DirExists(Ruta) then
    DelTree(Ruta, True, True, True)
  else if FileExists(Ruta) then
    DeleteFile(Ruta);
end;

// Renombrar con reintentos: el antivirus suele tener abierto un rato lo recien copiado.
function Mover(Desde, Hasta: String): Boolean;
var
  intento: Integer;
begin
  Result := False;
  for intento := 1 to 20 do
  begin
    if RenameFile(Desde, Hasta) then
    begin
      Result := True;
      Exit;
    end;
    Sleep(250);
  end;
  Log(Format('No se pudo mover "%s" a "%s".', [Desde, Hasta]));
end;

// Nombres de primer nivel de una carpeta (sin "." ni "..").
function Entradas(Carpeta: String): TArrayOfString;
var
  r: TFindRec;
  n: Integer;
begin
  n := 0;
  SetArrayLength(Result, 0);
  if FindFirst(AddBackslash(Carpeta) + '*', r) then
  try
    repeat
      if (r.Name <> '.') and (r.Name <> '..') then
      begin
        SetArrayLength(Result, n + 1);
        Result[n] := r.Name;
        n := n + 1;
      end;
    until not FindNext(r);
  finally
    FindClose(r);
  end;
end;

procedure ContarCarpeta(Carpeta: String; var Ficheros: Integer; var Bytes: Int64);
var
  r: TFindRec;
begin
  if FindFirst(AddBackslash(Carpeta) + '*', r) then
  try
    repeat
      if (r.Name <> '.') and (r.Name <> '..') then
      begin
        if (r.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          ContarCarpeta(AddBackslash(Carpeta) + r.Name, Ficheros, Bytes)
        else
        begin
          Ficheros := Ficheros + 1;
          Bytes := Bytes + r.SizeLow;
          if r.SizeHigh > 0 then
            Bytes := Bytes + Int64(r.SizeHigh) * 4294967296;
        end;
      end;
    until not FindNext(r);
  finally
    FindClose(r);
  end;
end;

// Deshace una conmutacion a medias: quita lo nuevo que llego a entrar (apuntado en el
// diario) y devuelve a su sitio lo viejo que se aparto a _viejo. True si todo volvio.
function DeshacerConmutacion: Boolean;
var
  diario, viejo: String;
  nuevas, viejas: TArrayOfString;
  i: Integer;
begin
  Result := True;
  diario := RutaApp('_conmutacion.txt');
  viejo := RutaApp('_viejo');
  if LoadStringsFromFile(diario, nuevas) then
    for i := 0 to GetArrayLength(nuevas) - 1 do
      if (Trim(nuevas[i]) <> '') and ExisteEntrada(RutaApp(Trim(nuevas[i]))) then
        BorrarEntrada(RutaApp(Trim(nuevas[i])));
  viejas := Entradas(viejo);
  for i := 0 to GetArrayLength(viejas) - 1 do
    if not ExisteEntrada(RutaApp(viejas[i])) then
      if not Mover(AddBackslash(viejo) + viejas[i], RutaApp(viejas[i])) then
        Result := False;
  if Result then
  begin
    DelTree(viejo, True, True, True);
    DeleteFile(diario);
    Log('Conmutacion deshecha: la version anterior esta en su sitio.');
  end;
end;

// Al empezar: si un instalador anterior murio en mitad de la conmutacion, se deshace.
procedure RecuperarConmutacionInterrumpida;
begin
  if FileExists(RutaApp('_conmutacion.txt')) then
  begin
    Log('Una instalacion anterior se corto mientras conmutaba: se deshace.');
    DeshacerConmutacion;
  end
  else if DirExists(RutaApp('_viejo')) then
    // La conmutacion termino pero no se llego a borrar lo viejo.
    DelTree(RutaApp('_viejo'), True, True, True);
end;

procedure InstalarVCRedist;
var
  codigo: Integer;
  redist: String;
begin
  redist := ExpandConstant('{tmp}\vc_redist.x64.exe');
  if FaltaVCRedist and FileExists(redist) then
  begin
    WizardForm.StatusLabel.Caption := 'Instalando el runtime de Visual C++...';
    if not Exec(redist, '/install /quiet /norestart', '', SW_HIDE, ewWaitUntilTerminated, codigo) then
      Log('No se pudo lanzar vc_redist.');
    Log(Format('vc_redist termino con codigo %d.', [codigo]));
  end;
end;

// Lanza "Exe --comprobar-rapidfuzz" sin ventana y devuelve su codigo de salida, con plazo:
// Exec de Inno espera sin limite, y un .exe roto puede quedarse colgado (o con el aviso de
// error del arranque de PyInstaller abierto) y dejar la actualizacion parada para siempre.
// El plazo lo pone PowerShell, que viene con Windows; si no se puede usar, Exec a secas.
function ProbarExe(Exe, Carpeta: String): Integer;
var
  ps, orden: String;
begin
  ps := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  // Comillas simples de PowerShell: una ' dentro de la ruta se escribe ''.
  StringChangeEx(Exe, '''', '''''', True);
  StringChangeEx(Carpeta, '''', '''''', True);
  orden := '-NoProfile -NonInteractive -WindowStyle Hidden -Command "' +
    '$p = Start-Process -FilePath ''' + Exe + ''' -ArgumentList ''--comprobar-rapidfuzz'' ' +
    '-WorkingDirectory ''' + Carpeta + ''' -WindowStyle Hidden -PassThru; $null = $p.Handle; ' +
    'if (-not $p.WaitForExit(' + IntToStr(EsperaComprobacionMs) + ')) { Stop-Process -Id $p.Id -Force; exit ' +
    IntToStr(CodigoSinRespuesta) + ' }; exit $p.ExitCode"';
  if FileExists(ps) and Exec(ps, orden, Carpeta, SW_HIDE, ewWaitUntilTerminated, Result) then
    Exit;
  Log('Sin PowerShell: se prueba el programa nuevo sin plazo.');
  StringChangeEx(Exe, '''''', '''', True);
  StringChangeEx(Carpeta, '''''', '''', True);
  if not Exec(Exe, '--comprobar-rapidfuzz', Carpeta, SW_HIDE, ewWaitUntilTerminated, Result) then
    Result := -1;
end;

// Esta todo lo nuevo en _nuevo y el Farmadex.exe nuevo arranca? '' si si; si no, el motivo.
function ComprobarNueva: String;
var
  nuevo: String;
  ficheros, codigo: Integer;
  bytes: Int64;
begin
  Result := '';
  nuevo := RutaApp('_nuevo');
  ficheros := 0;
  bytes := 0;
  ContarCarpeta(nuevo, ficheros, bytes);
  Log(Format('Copiados %d ficheros y %s bytes (se esperaban %d y %s).', [ficheros, IntToStr(bytes), FicherosEsperados, BytesEsperados]));
  if (ficheros <> FicherosEsperados) or (IntToStr(bytes) <> BytesEsperados) then
  begin
    Result := 'faltan ficheros de la version nueva (no se copiaron todos)';
    Exit;
  end;
  // El .exe nuevo tiene que arrancar de verdad: --comprobar-rapidfuzz (empaquetado\arranque.py)
  // carga Python y las librerias compiladas y sale sin abrir ventanas ni tocar datos.
  // 0 = bien; 3 = arranca pero con rapidfuzz lento, que sigue siendo un programa que funciona.
  WizardForm.StatusLabel.Caption := 'Comprobando la version nueva...';
  codigo := ProbarExe(AddBackslash(nuevo) + '{#NombreApp}.exe', nuevo);
  if codigo = CodigoSinRespuesta then
    Result := 'el programa nuevo no responde'
  else if (codigo <> 0) and (codigo <> 3) then
    Result := Format('el programa nuevo no arranca (codigo %d)', [codigo]);
end;

// Pone la version nueva en su sitio. '' si todo fue bien; si no, el motivo (y deshecho).
function Conmutar: String;
var
  nuevo, viejo, diario: String;
  nuevas: TArrayOfString;
  i: Integer;
begin
  Result := '';
  nuevo := RutaApp('_nuevo');
  viejo := RutaApp('_viejo');
  diario := RutaApp('_conmutacion.txt');
  WizardForm.StatusLabel.Caption := 'Poniendo la version nueva en su sitio...';
  nuevas := Entradas(nuevo);
  DelTree(viejo, True, True, True);
  if (not ForceDirectories(viejo)) or (not SaveStringToFile(diario, '', False)) then
  begin
    Result := 'no se puede escribir en la carpeta del programa';
    Exit;
  end;
  // 2. Apartar lo viejo. Si algo esta en uso (otro Farmadex abierto desde esta carpeta,
  //    un antivirus...) Windows no deja renombrarlo y se deshace sin haber tocado nada.
  for i := 0 to GetArrayLength(nuevas) - 1 do
    if ExisteEntrada(RutaApp(nuevas[i])) then
      if not Mover(RutaApp(nuevas[i]), AddBackslash(viejo) + nuevas[i]) then
      begin
        Result := 'hay ficheros del programa en uso (' + nuevas[i] + ')';
        DeshacerConmutacion;
        Exit;
      end;
  // 3. Meter lo nuevo, apuntando antes cada entrada en el diario.
  for i := 0 to GetArrayLength(nuevas) - 1 do
  begin
    SaveStringToFile(diario, nuevas[i] + #13#10, True);
    if not Mover(AddBackslash(nuevo) + nuevas[i], RutaApp(nuevas[i])) then
    begin
      Result := 'no se pudo colocar ' + nuevas[i];
      DeshacerConmutacion;
      Exit;
    end;
  end;
  // 4. Hecho: sin diario, la version nueva es la buena pase lo que pase despues.
  DeleteFile(diario);
  DelTree(viejo, True, True, True);
  DelTree(nuevo, True, True, True);
  Log('Version nueva colocada y comprobada.');
end;

// Actualizacion lanzada por el propio Farmadex: se vuelve a abrir la version nueva. Con
// --tras-actualizar, para que ese arranque no vuelva a buscar actualizaciones antes de
// abrirse (evita bucles), y con --bandeja si la actualizacion se lanzo desde el arranque
// con Windows (/BANDEJA=1): sin ventana. Si la version nueva no se pudo poner no se abre
// nada aqui: el setup devuelve error y el envoltorio que lo lanzo (instalacion.py) abre
// la version de siempre.
procedure RelanzarTrasActualizar;
var
  codigo: Integer;
begin
  if ShellExec('', RutaApp('{#NombreApp}.exe'), ArgumentosRelanzar(''), ExpandConstant('{app}'),
               SW_SHOWNORMAL, ewNoWait, codigo) then
    Log('Farmadex vuelto a abrir tras actualizar.')
  else
    Log('No se pudo volver a abrir Farmadex: ' + SysErrorMessage(codigo));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    RecuperarConmutacionInterrumpida
  else if CurStep = ssPostInstall then
  begin
    InstalarVCRedist;
    MotivoFallo := ComprobarNueva;
    if MotivoFallo = '' then
      MotivoFallo := Conmutar;
    Completada := MotivoFallo = '';
    if Completada and EsActualizacionAutomatica then
      RelanzarTrasActualizar;
    if not Completada then
    begin
      // Lo copiado no sirve: fuera, para no dejar cientos de MB ocupados.
      DelTree(RutaApp('_nuevo'), True, True, True);
      Log(MarcaNoCompletada + ': ' + MotivoFallo + '. La version anterior sigue instalada.');
      SuppressibleMsgBox(MarcaNoCompletada + ': ' + MotivoFallo + '.' + #13#10#13#10 +
        'No se ha cambiado nada: la version que tenias de {#NombreApp} sigue instalada y funciona igual.' + #13#10 +
        'Cierra los programas que puedan estar usando la carpeta de {#NombreApp} y vuelve a abrir el instalador.',
        mbError, MB_OK, IDOK);
    end;
  end;
end;

// Sin esto, el asistente diria "instalado correctamente" aunque la version nueva no entrase.
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and (MotivoFallo <> '') then
  begin
    WizardForm.FinishedHeadingLabel.Caption := 'No se ha podido actualizar {#NombreApp}';
    WizardForm.FinishedLabel.Caption :=
      'La version que tenias sigue instalada y funcionando: no se ha cambiado nada.' + #13#10#13#10 +
      'Motivo: ' + MotivoFallo + '.';
  end;
end;

// Si no se pudo poner la version nueva, el setup devuelve error: la actualizacion
// automatica (instalacion.py) lo ve y vuelve a abrir la version anterior.
function GetCustomSetupExitCode: Integer;
begin
  if MotivoFallo <> '' then
    Result := 9
  else
    Result := 0;
end;

// -- Desinstalacion ------------------------------------------------------------------

// Antes de borrar nada, Farmadex tiene que estar cerrado: si no, sus ficheros en uso se
// quedarian en la carpeta. Se le pide que se cierre como al instalar.
function InitializeUninstall: Boolean;
var
  espera: Integer;
begin
  Result := True;
  if not CheckForMutexes(MutexFarmadex) then
    Exit;
  PedirCierreFarmadex;
  espera := 0;
  while CheckForMutexes(MutexFarmadex) and (espera < 60) do
  begin
    Sleep(500);
    espera := espera + 1;
  end;
  while CheckForMutexes(MutexFarmadex) do
    if SuppressibleMsgBox('{#NombreApp} esta abierto. Cierralo (icono junto al reloj, boton derecho, Salir) y pulsa Aceptar.',
                          mbInformation, MB_OKCANCEL, IDCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  datos, run: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    // "Abrir con Windows" tambien se puede activar desde Farmadex (farmadex/arranque.py),
    // que escribe el mismo valor: si apunta a esta carpeta, fuera, o quedaria colgando.
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#NombreApp}', run) then
      if Pos(Lowercase(AddBackslash(ExpandConstant('{app}'))), Lowercase(run)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#NombreApp}');
  end
  else if CurUninstallStep = usPostUninstall then
  begin
    // Se pregunta si borrar los datos (indice, objetivos, ajustes). Sin nadie delante
    // (desinstalacion silenciosa) nunca se borran.
    datos := ExpandConstant('{localappdata}\{#NombreApp}');
    if DirExists(datos) and not UninstallSilent then
      if SuppressibleMsgBox('Borrar tambien tus datos de {#NombreApp} (objetivos, ajustes y el indice descargado)?',
                            mbConfirmation, MB_YESNO, IDNO) = IDYES then
        DelTree(datos, True, True, True);
  end;
end;
