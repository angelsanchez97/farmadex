# Auditoría de producto: Farmadex visto por un veterano

Fecha: 2026-09-20. Versión auditada: 0.1.3, contra una copia del índice real
(`%LocalAppData%\Farmadex\db\indice.sqlite`, 16.765 objetos) y el estado del
mundo en vivo. La interfaz se arrancó sin pantalla (`QT_QPA_PLATFORM=offscreen`,
`QT_QPA_FONTDIR=C:\Windows\Fonts`) y se capturó cada pestaña con
`QWidget.grab()`; además se volcó el texto de cada ficha. No se tocó código.

Perfil del jugador contra el que se juzga: maestría 30+, miles de horas, juega
a diario, hace incursión y arcontes cada semana, abre reliquias en escuadra
pública, comercia en warframe.market, tiene rivens, va a por bóveda y arcanos, y
emite en directo. Ya tiene Overframe, warframe.market y la wiki en el segundo
monitor. No quiere información: quiere decidir rápido.

## Qué se probó y qué se vio

| Consulta real | Lo que hace hoy | Veredicto |
|---|---|---|
| `axi` (¿cuál de las cuatro reliquias abro?) | Lista 40 reliquias por nombre. La ficha de una reliquia enseña contenido, rareza y % en Radiante, y 74 misiones donde cae. Ni platino ni ducados por pieza, ni valor esperado, ni comparación entre reliquias. | No responde la pregunta. La respuesta la da mejor la tabla de precios del propio juego o warframe.market. |
| `ash prime` (set en bóveda) | Precio del set (67p) y las cuatro piezas como enlaces. No dice qué reliquia trae cada pieza sin entrar en cada una, ni el precio por pieza, ni si sale mejor comprar el set. | La decisión "set o piezas" se hace en warframe.market. |
| `arcane energize` (¿dónde se farmea, cuánto vale?) | Fuentes correctas (Hydrolyst 5 %, Erato rotación C 1,4 %). Precio: "se vende desde **8 platino** … te lo compran por **130p**". | El precio está mal: warframe.market mezcla órdenes de rango 0 y rango máximo, y Farmadex no filtra `mod_rank`. Un comerciante deja de fiarse a la primera. Lo mismo con Vigor de Muda (2p / 35p). |
| `energizante`, `acolito`, `primed` | `energizante` no encuentra Energizar Arcano. `acolito` no da los mods de acólito. `primed` devuelve "Flujo Prime" (los mods Primed en español se llaman "Prime", igual que las piezas). | Sinónimos y categorías: falta buscar por origen ("cae de acólito", "lo vende Baro"). |
| Mundo (¿qué fisura me conviene ahora?) | 40 fisuras en lista plana, con las ya **terminadas** mezcladas, sin orden por utilidad y sin cruzar con la era que piden sus objetivos. Baro: "todavía no ha llegado", sin cuenta atrás ni inventario. Aviso naranja de datos de hace 26 min. | El propio menú de navegación del juego enseña las fisuras mejor. Lo único que aporta es el ciclo de Cetus/Valle, que ya le sale en el mapa. |
| Objetivos (set Ash Prime) | Cuatro filas "Solo en bóveda · Reliquia Axi I3 (20 %). Hay que comprarla a otro jugador". | Correcto pero sin precio de la reliquia ni de la pieza: no ayuda a decidir si comprar la pieza (5-15p) o la reliquia. |
| Perfil | "preparado, pero hoy sin fuente de datos". | Pestaña entera muerta; la marca de dominado/no dominado de cada ficha depende de ella. |
| Bajo el cursor (`Ctrl+Alt+Q`) y recompensas (`Ctrl+Alt+R`, automático por EE.log) | Encima de cada recompensa: platino, ducados, bóveda y si cubre un objetivo. | Esto es lo único que un veterano no tiene en el segundo monitor. Es la función central y va bien encaminada, pero hereda el fallo de precios por rango en mods/arcanos. |

## Coste de tenerlo abierto en directo

- 140 MB de RAM en reposo y dos hilos Python (el OCR se carga al primer uso).
  Estado del mundo cada 60 s visible / 300 s oculto; precios solo bajo demanda.
  No estorba a OBS ni al juego.
- La ventana es de 1100×700 y tapa un tercio de la pantalla. No hay modo
  compacto ni "tira" para dejar en una esquina o en el segundo monitor: se abre,
  se consulta y se cierra. En directo eso significa que el espectador ve una
  ventana grande cada vez que el jugador duda.
- Atajos `Ctrl+Alt+W/Q/R`: no chocan con Warframe ni con OBS por defecto.
  `Ctrl+Alt+R` sí lo usan algunos plugins de OBS para "reiniciar grabación";
  conviene poder comprobarlo desde Ajustes.
- Pantalla completa exclusiva: el overlay no se ve; el programa lo detecta y lo
  dice. Correcto.

## Lo que le hace cerrar el programa hoy

1. **Precios de mods y arcanos sin rango.** `warframe.market` devuelve
   `mod_rank` en cada orden; Farmadex ordena por platino sin filtrarlo, así que
   la venta más barata es rango 0 y la compra más alta es rango máximo. Para el
   trader es información falsa. Arreglo: filtrar por rango (mostrar r0 y máx.)
   en `online/market.py::analizar_ordenes` y en la etiqueta de recompensas.
   Coste: 3 h. Datos: ya están.
2. **La ficha de reliquia no vale nada para decidir.** Sin platino ni ducados
   por pieza, sin valor esperado Intacta/Radiante, sin comparación. Arreglo:
   columna de platino (ya emparejado, 3.625 objetos) y ducados (ya en `items`)
   en `_bloque_contenido`, más una línea "valor esperado: X p / Y ducados".
   Coste: 6 h. Datos: ya están.
3. **Mundo es una lista sin criterio.** Fisuras terminadas mezcladas, sin orden,
   sin cruce con objetivos. Arreglo: ocultar las expiradas, ordenar por (era que
   necesitan mis objetivos, misión rápida, tiempo restante) y marcar en color
   las que sirven. Coste: 5 h. Datos: ya están (`eras_necesarias` existe).
4. **Perfil muerto.** Sin él no hay "dominado / no dominado", que es la
   pregunta número uno de un MR30 en cada recompensa. Arreglo real: importar
   maestría por OCR de las pantallas de perfil (ya diseñado en `perfil/desde_ocr`)
   o por la API pública de AlecaFrame. Coste: 12-16 h. Datos: nuevos (capturas
   del usuario o token de AlecaFrame).
5. **Ventana grande sin modo compacto.** En directo tapa el juego y al
   espectador le molesta. Arreglo: modo "tira" de una línea (fisura
   recomendada, Baro, objetivo activo) anclable a un borde o al segundo monitor.
   Coste: 6 h.

## Lo que más le engancharía

1. **Comparador de reliquias en la pantalla de selección de fisura.** Al
   elegir reliquia (evento de EE.log ya vigilado), leer por OCR las que ofrece
   y puntuar cada una en platino, ducados y objetivos, Intacta y Radiante,
   ajustado a escuadra de 4. Es lo que AlecaFrame hace con el inventario, pero
   sin inventario también sirve: se puntúa lo que está en pantalla. Coste:
   12-14 h (OCR de esa pantalla 6 h, cálculo 3 h, overlay 3 h). Datos: ya están.
2. **Baro útil.** Cuenta atrás a su llegada, inventario cuando esté (viene en
   `voidTrader.inventory` de warframestat.us) y para cada objeto: precio en
   platino, "cubre un objetivo" y, con perfil, "no lo tienes". Coste: 4 h sin
   perfil. Datos: ya están.
3. **Precio por rango y regla ducados/platino.** En cada pieza prime, "vale
   más en ducados" o "véndela" según umbral configurable (por defecto: <5p y
   ≥45 ducados = Baro). Tanto en la ficha como sobre las recompensas. Coste:
   4 h. Datos: ya están.
4. **Integración con AlecaFrame por su API pública.** Con el token del
   usuario: reliquias que posee con cantidad por refinamiento, series de
   platino y ducados, historial de trades. Convierte el comparador del punto 1
   en un planificador de verdad ("de las que tienes, abre esta"). Coste: 12-16 h.
   Datos: nuevos (token que genera el usuario en AlecaFrame; ver
   `docs/alecaframe.md`, sección 6).
5. **Historial de sesión.** Cada recompensa que el OCR ya lee se guarda con
   hora, precio y ducados; pestaña "Hoy": reliquias abiertas, platino
   estimado, piezas conseguidas, con exportación para el directo (fichero de
   texto que OBS puede leer como fuente). Coste: 6 h. Datos: ya están.

## Menores, pero baratos

- Sinónimos de búsqueda: "energizante", "acolito", "baro", "primed" (1-2 h).
- Ocultar el checkbox "Ocultar reliquias en bóveda" de la barra de búsqueda y
  moverlo a Ajustes: casi nunca se toca y ocupa el sitio del botón principal.
- En la ficha de un prime, enseñar la reliquia y el precio de cada pieza sin
  tener que entrar en cada una (2 h).
- Objetivos: añadir dos veces el mismo set crea filas duplicadas (visto al
  añadir Ash Prime dos veces en la sesión de prueba); comprobar antes (1 h).
- Comprobar en Ajustes si un atajo ya lo tiene registrado otra aplicación
  (`RegisterHotKey` devuelve error 1409) y decirlo con el nombre del atajo.

## Qué resuelve mejor una web que ya tiene abierta

- Precio de un objeto suelto: warframe.market, siempre. Farmadex solo gana si
  el precio aparece **sobre la recompensa** sin salir del juego.
- Dónde cae algo: la wiki tiene lo mismo y con notas. Farmadex gana en
  velocidad (tres letras y ya está) y en español, pero no en contenido.
- Builds, rivens, disposición: Overframe y semlar. Farmadex no lo cubre ni
  debería.
- Lo que ninguna web cubre y Farmadex sí puede: **lo que hay en pantalla ahora
  mismo** (recompensas, reliquia elegida, objeto bajo el cursor) cruzado con
  **lo que el jugador quiere** (objetivos) y, con AlecaFrame, con lo que tiene.
  Ahí está todo el valor; el resto es relleno.
