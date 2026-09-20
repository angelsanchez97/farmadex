# Instalación de Farmadex

## Requisitos

- Windows 10 (versión 1809 o posterior) o Windows 11, de 64 bits.
- Conexión a internet la primera vez que se abre (descarga los datos del
  juego) y mientras se usa, para el estado del mundo y los precios.

## Descargar

Todas las versiones están en la página de
[Releases](https://github.com/angelsanchez97/farmadex/releases/latest) del
repositorio. Ahí hay dos ficheros por versión:

- **`Farmadex-X.X.X-setup.exe`**: el instalador. Es la forma recomendada.
- **`Farmadex-X.X.X-portable.zip`**: la versión sin instalador, para quien
  prefiera no tocar el sistema.

## Instalar con el instalador

1. Descarga `Farmadex-X.X.X-setup.exe` y ábrelo.

2. Windows va a enseñar un aviso de **SmartScreen** que dice algo como
   «Windows protegió tu PC» o que no reconoce a la aplicación. No es que el
   instalador esté dañado: es que no está firmado con un certificado de pago
   (cuestan varios cientos de euros al año y esto es un proyecto sin ánimo
   de lucro). Para seguir:

   1. Pulsa **«Más información»**.
   2. Pulsa **«Ejecutar de todas formas»**.

3. El instalador es de los que no piden permisos de administrador: se
   instala solo para tu usuario, en
   `%LocalAppData%\Programs\Farmadex`. Puedes elegir si quieres un acceso
   directo en el escritorio y si quieres que Farmadex se abra solo al
   encender Windows.

4. Si tu equipo no tiene instalado el runtime de Visual C++ que necesitan Qt
   y el motor de lectura de pantalla, el instalador lo instala también, sin
   que tengas que hacer nada.

5. Al terminar, el instalador puede abrir Farmadex por ti.

## La primera vez que se abre

En cuanto arranca, Farmadex descarga los datos del juego: el catálogo de
objetos y las tablas de dónde cae cada cosa. Son unos **140 MB**, se ve una
barra de progreso y tarda unos minutos, según tu conexión. Solo hace falta
una vez; a partir de ahí, Farmadex comprueba cada pocas horas si hay algo
nuevo y descarga solo lo que haya cambiado.

Mientras dura esta primera descarga, la pestaña Buscar está desactivada; el
resto de la ventana ya se puede usar. Farmadex se queda en la bandeja del
sistema, al lado del reloj; se abre y se cierra con `Ctrl+Alt+W`.

## Dónde se guardan los datos

Todo lo que Farmadex descarga y todo lo que tú generas (tus objetivos, tus
ajustes, el índice construido) vive en:

```
%LocalAppData%\Farmadex
```

La carpeta donde se instaló el programa no se toca nunca. Puedes abrir esta
carpeta de datos desde Ajustes, con el botón «Abrir la carpeta de datos».

## Actualizar

Farmadex comprueba si hay una versión nueva publicada en GitHub (se puede
desactivar en Ajustes) y, si la hay, lo dice en la pestaña Ajustes con un
enlace o un botón para instalarla. **Nunca se instala nada por su cuenta**:
la decisión es siempre tuya.

- Si aparece el botón **«Instalar la versión nueva»**, al pulsarlo se lanza
  el instalador nuevo y Farmadex se cierra; tus objetivos y tus ajustes se
  conservan.
- Si en vez de eso aparece un enlace de descarga, te lleva a la página de la
  versión en GitHub: descarga el instalador y ejecútalo igual que la primera
  vez, sobre la instalación que ya tienes. Tus datos no se tocan.
- También puedes comprobarlo a mano en cualquier momento con el botón
  «Comprobar ahora», en Ajustes.

Para la versión portable no hay comprobación ni instalador: descarga el zip
nuevo y sustituye los ficheros del programa por los de dentro (tus datos,
que están en `%LocalAppData%\Farmadex`, no están ahí y no se pierden).

## Desinstalar

Desinstala Farmadex como cualquier otro programa: desde **Configuración >
Aplicaciones** de Windows, o desde el grupo «Farmadex» del menú Inicio.

Al terminar, el desinstalador pregunta si quieres borrar también tus datos
(objetivos, ajustes y el índice descargado). Si crees que vas a volver a
instalarlo más adelante, contesta que no y te ahorras la descarga inicial la
próxima vez.

## Zip portable

Si prefieres no instalar nada:

1. Descarga `Farmadex-X.X.X-portable.zip`.
2. Descomprímelo donde quieras (un USB, una carpeta cualquiera).
3. Ejecuta `Farmadex.exe` directamente, dentro de esa carpeta.

Funciona igual que la versión instalada, con el mismo aviso de SmartScreen
la primera vez y la misma descarga inicial de datos. La única diferencia es
que no queda registrado en Windows ni deja accesos directos: para quitarlo
basta con borrar la carpeta. Tus datos (objetivos, ajustes, índice) se
guardan igualmente en `%LocalAppData%\Farmadex`, no dentro de esta carpeta.

## Ejecutar desde el código fuente

Esta sección es para quien quiera tocar el código, no hace falta para usar
Farmadex normalmente.

Requisitos: Python 3.12 o posterior, y Windows (algunas partes, como la
captura de pantalla y los atajos globales, solo funcionan ahí).

```powershell
git clone https://github.com/angelsanchez97/farmadex.git
cd farmadex
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Para lanzarlo:

```powershell
.venv\Scripts\python.exe -m farmadex
```

Para correr las pruebas:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m pytest tests -q
```

Para generar tú mismo el ejecutable, el zip portable y (si tienes instalado
[Inno Setup 6](https://jrsoftware.org/isdl.php)) el instalador:

```powershell
powershell -ExecutionPolicy Bypass -File empaquetado\construir.ps1
```

El script pasa las pruebas antes de empaquetar y deja todo en `dist\`, con su
SHA-256.
