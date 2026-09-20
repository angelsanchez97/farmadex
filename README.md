# Farmadex

Overlay en español para Warframe: escribes cualquier cosa del juego y te dice de
dónde sale. Pensado para no tener que salir de la partida ni pelearse con el
códice, que cuenta la mitad de lo que necesitas.

## Qué hace

- **Buscar**: cualquier objeto, recurso, pieza, mod o reliquia, en español o en
  inglés, y aunque lo escribas con erratas. Te enseña la cadena completa: la
  pieza, en qué reliquias cae y con qué probabilidad según el refinamiento, si
  esa reliquia está en bóveda, y en qué misiones se consigue, con el nodo y el
  planeta en español.
- **Objetivos**: apuntas lo que quieres farmear (o el set entero de un prime de
  una vez) y ves el progreso y por dónde empezar.
- **Mundo**: fisuras abiertas ahora mismo filtrables por era y por Camino de
  Acero, ciclos de Cetus, el Valle y Cambion, invasiones, alertas, arbitración,
  incursión, caza de arcontes, Nightwave, Baro y la oferta del Camino de Acero,
  todo con cuenta atrás.
- **Precios**: lo que vale cada cosa en platino según warframe.market.
- **Leer la pantalla**: al abrir una reliquia te pone encima de cada recompensa
  su precio, sus ducados, si está en bóveda y si te sirve para un objetivo. Y con
  otro atajo te dice qué es lo que hay bajo el cursor.

## Requisitos

- Windows 10 (1809 o posterior) o Windows 11, 64 bits.
- **Warframe en «Ventana sin bordes»** (o en DX12). En pantalla completa
  exclusiva ningún overlay se ve, ni este ni ninguno.
- Conexión a internet la primera vez (descarga unos 140 MB de datos del juego) y
  para el estado del mundo y los precios.

## Instalación

Descarga el instalador o el zip portable, ejecútalo y ya está. No hace falta
instalar Python ni ninguna otra cosa.

Windows enseñará un aviso de SmartScreen la primera vez, porque el programa no
está firmado con un certificado de pago: pulsa **Más información** y luego
**Ejecutar de todas formas**.

## Atajos

| Atajo | Qué hace |
|---|---|
| `Ctrl+Alt+W` | Abre y cierra el overlay |
| `Ctrl+Alt+Q` | Lee lo que haya bajo el cursor y abre su ficha |
| `Ctrl+Alt+R` | Lee la pantalla de recompensas de reliquia |
| `Escape` | Cierra el overlay |

Se pueden cambiar en Ajustes. El programa vive en la bandeja del sistema, al
lado del reloj; se sale desde ahí.

## Dónde guarda las cosas

Todo en `%LocalAppData%\Farmadex`: los datos descargados, el índice, tus
objetivos y los ajustes. La carpeta de instalación no se toca. Al desinstalar se
pregunta si quieres conservarlo.

## Aviso legal

Farmadex **no está afiliado a Digital Extremes** ni tiene su respaldo. Warframe y
todo su contenido son propiedad de Digital Extremes.

El programa **no modifica el juego de ninguna forma**: no lee ni escribe en la
memoria del proceso, no inyecta nada, no envía pulsaciones ni clics al juego, no
automatiza ninguna acción y no usa las credenciales de tu cuenta. Lo único que
hace es (1) capturar píxeles de la pantalla cuando tú se lo pides o cuando se
abre la pantalla de recompensas, para leerlos con OCR, y (2) mirar las líneas
nuevas de `EE.log`, el registro que el propio juego escribe, del que solo se
reconocen mensajes concretos de la interfaz. Ese fichero contiene datos
personales (correo e IP): su contenido no se copia, ni se enseña, ni sale de tu
equipo.

Aun así, usarlo es responsabilidad tuya, conforme a la política de software de
terceros de Digital Extremes.

## Datos y licencias

Los datos del juego salen de proyectos abiertos, y se descargan directamente de
ellos:

- [WFCD/warframe-items](https://github.com/WFCD/warframe-items) — catálogo de
  objetos y traducciones (MIT).
- [WFCD/warframe-drop-data](https://github.com/WFCD/warframe-drop-data) — tablas
  de drops oficiales de Digital Extremes (MIT).
- [warframestat.us](https://docs.warframestat.us/) — estado del mundo
  (Apache-2.0).
- [warframe.market](https://warframe.market/) — precios en platino.
- Public Export de Digital Extremes — nombres del mapa estelar en español.

Y estas son las bibliotecas que lleva dentro:

- PySide6 / Qt for Python (LGPL-3.0; se enlaza dinámicamente y se distribuye sin
  modificar).
- RapidOCR y ONNX Runtime (Apache-2.0) para leer la pantalla.
- httpx (BSD-3), RapidFuzz (MIT), mss (MIT), OpenCV (Apache-2.0).

## Construirlo tú mismo

```powershell
powershell -ExecutionPolicy Bypass -File empaquetado\construir.ps1
```

Pasa las pruebas, empaqueta con PyInstaller, poda lo que no se usa, genera el zip
portable y, si tienes [Inno Setup 6](https://jrsoftware.org/isdl.php), también el
instalador. Deja todo en `dist\` con su SHA-256.

Para trabajar en el código:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m farmadex
```
