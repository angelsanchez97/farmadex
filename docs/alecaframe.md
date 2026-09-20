# AlecaFrame: qué hace, cómo lo hace y qué puede copiar Farmadex

Informe de investigación, 2026-09-20 (tercera revisión, tras la respuesta de
Warframe Support al usuario). Fuentes: la web y la wiki de AlecaFrame (recorrida
entera, incluido el código Markdown de la wiki en GitHub), su OpenAPI real en
`stats.alecaframe.com`, la ficha de la app en Overwolf, la documentación de
eventos de juego de Overwolf y sus condiciones de uso, el código fuente de
Sentinel y de WFHelper (herramientas que leen datos de AlecaFrame), los fixtures
de perfil de WFCD, y las declaraciones públicas de Digital Extremes. Todas las
URL van al final. Donde algo es deducción y no cita, se dice. Las pruebas con
`curl` se hicieron desde este equipo el mismo día.

---

## 0. Resumen

- AlecaFrame es una app de **Overwolf** (Windows, código cerrado, C# + HTML/JS,
  versión 2.6.93 del 29-08-2026, 4,5/5 con 78 votos), del desarrollador español
  Alejandro Cabrerizo. Gratis con publicidad; extras por Patreon (4 / 7 / 13,50 /
  45 €/mes; 3.427 miembros, 1.192 de pago).
- Su ventaja central es **una sola cosa**: tiene el **inventario completo del
  jugador**. Lo obtiene **Overwolf leyendo la memoria del proceso
  `Warframe.x64`** y entregándoselo como evento. Farmadex **no va a escribir un
  lector de memoria**: es "información protegida" en los términos del correo de
  DE, choca con el EULA y se rompería en cada parche.
- **Novedad**: el usuario preguntó a Warframe Support y DE respondió que **no
  tiene inconveniente** en que use Overwolf y AlecaFrame para obtener datos de
  su cuenta y llevarlos a una aplicación propia, con límites (sección 5.4).
  Conclusión de trabajo: **Farmadex puede integrarse con AlecaFrame como fuente
  de datos por sus vías oficiales** (API con token del usuario, exportaciones).
- **Qué da la API oficial de AlecaFrame** (sección 6): con un *token público*
  que el usuario genera en su pestaña Stats, (1) la **lista de reliquias que
  posee con cantidad por refinamiento**, y (2) **series temporales de platino,
  ducados, endo, créditos, aya, rango de maestría, reliquias abiertas y número de
  trades**, más el **historial de trades** (solo con el juego en inglés). Sin
  cuenta de pago, sin clave de API, 1 petición/s por IP, token válido un año y
  revocable.
- **Qué sigue sin ser posible** por vías oficiales: el inventario de **piezas y
  planos con cantidades, mods, arcanos, trazas del Vacío, XP por objeto
  (dominado/no), fundición**. Eso solo está en la caché cifrada local de
  AlecaFrame (`lastData.dat`), que Farmadex **no descifrará**: las condiciones
  de Overwolf lo prohíben (§7.2(iii)) y el correo de DE exige respetarlas.
- **Vinculación directa de la cuenta de Warframe**: no hay vía automática
  legítima, y **la vía manual documentada por la comunidad está rota a
  20-09-2026** (sección 5): `warframe.com/api/user-data` devuelve 404 incluso
  con sesión (probado por el usuario), y el endpoint de perfil devuelve **409
  vacío para cuentas reales**, incluida la de [DE]Rebecca que FrameHub usa de
  ejemplo, mientras que el host de PS4 responde "Retry with PC account:
  505875fb1a4d80894a000000,[DE]Rebecca": el servidor conoce la cuenta y aun así
  no la sirve. Quedan dos comprobaciones de un minuto para el usuario (5.3) y,
  si fallan, la maestría solo se obtiene por **OCR de sus pantallas de perfil**
  (5.4). El paquete `src/farmadex/perfil/` se conserva; cambia la entrada.
  Queda escrito: Farmadex **nunca** pedirá ni guardará el correo o la
  contraseña de Warframe ni usará la sesión del jugador contra los servidores
  de DE.
- Lo que más aportaría, por orden: **integración con AlecaFrame (reliquias
  reales + platino/ducados)**, **planificador de reliquias con esas
  reliquias**, **historial de recompensas y estadísticas de sesión**, **avisos
  del estado del mundo ligados a objetivos**, **overlay de recompensas
  enriquecido**.

---

## 1. Inventario de funciones de AlecaFrame

Una línea por función: qué resuelve al jugador.

### 1.1 Pestañas de la ventana principal

**Foundry (Fundición)** — todos los warframes/armas del juego con tu estado real.
- Etiquetas: *dominado* (aunque ya no lo tengas), *poseído*, *en bóveda*,
  *tienes reliquias que sueltan esta pieza*, *tiene fragmentos de arconte*.
- Filtros: Prime/normal, dominado, poseído, bóveda, **listo para construir**,
  **maestría suficiente**, Prime Resurgence, usado en otra receta, favorito,
  Helminth hecho, con fragmentos.
- Ficha: estadísticas del objeto, componentes con dónde se consiguen o
  comprar/vender en warframe.market.
- **Árbol de crafteo** con recursos y planos totales, descontando lo ya construido.

**Inventory (Inventario)** — lo vendible en warframe.market, con **orden de
venta en un clic**.
- Filtros: pieza de objeto dominado/no, más de una copia, bóveda, con orden
  puesta, Prime/normal, favorito, mínimo 5/10/15 platino, set completo, mod
  equipado, mod/arcano subido.
- **Set Manager**: sets con al menos una pieza; vender solo si está completo.

**Mastery Helper** — camino más corto al siguiente rango.
- *Easy*: lo que puedes subir ya. *From relics*: lo completable con **tus
  reliquias**, ordenado por probabilidad. *With platinum*: coste en WFM de lo
  que falta. Maestría total con ±100 XP de error reconocido.

**Relic Planner** — qué reliquia abrir.
- Orden por **beneficio en platino**, **en ducados**, piezas que faltan
  (**mejor para MR**), nombre, cantidad, **mejor para refinar** (por traza).
- Ajuste por **tamaño de escuadra**. Filtros: bóveda, recompensas ya poseídas,
  objetos dominados, ≥ 10 copias, refinamiento, favorito. Exporta la vista al
  overlay de recomendación.

**Riven Explorer** — nota Great/Good/OK/Bad por arma (hoja comunitaria), orden
por disposición/MR/rerolls/**perfección**/nota, **Finder** con precio medio a 15
días y precio base, popularidad y efecto en precio de cada atributo (valores
reales solo mecenas), **Sniper** con webhook de Discord (5 huecos gratis,
prioridad a mecenas, pausa a los 30 días sin abrir la app).

**Stats** — series de **platino, ducados, ...** con gráficos, **historial de
trades** (solo inglés), export **CSV/JSON**, **enlaces públicos** (un año,
revocables, datos vivos), todo en su servidor bajo `userHash` anónimo,
desactivable.

**Trading Analytics (de pago, Patreon T2+)** — volumen y valor de WFM
procesados por ellos + tus ganancias.

**Warframe.Market** — inicio de sesión con la cuenta de WFM (no de Warframe);
órdenes y contratos, "!" si el objeto ya no está y **ajuste automático de
cantidad**; acciones masivas (visibles/invisibles, arreglar, borrar).

### 1.2 Overlays

- **Relic Rewards**: al abrir una reliquia, información sobre cada recompensa.
  EN/ES/DE/FR/RU.
- **Relic Recommendation**: al elegir reliquia para fisura, la lista del Relic
  Planner. Aviso: el inventario "solo se actualiza en pantallas de carga".
- **Chat Riven** y **Riven Reroll**: estadísticas y nota del riven abierto
  desde el chat / antes y después del reroll. **Solo inglés.**

### 1.3 Menos visible

- Avisos de Windows y de Discord; favoritos transversales; **API pública**
  (sección 6); temporizadores del juego; `relicLogs` de depuración; exige 1080 px
  verticales, copiar el escalado de interfaz, profundidad de campo activada,
  cerrar WFInfo; funciona en pantalla completa exclusiva porque Overwolf pinta
  el overlay inyectado.
- Patreon: "Ads? No, thanks" 4 €, "I ❤ AlecaFrame" 7 €, "Oh shit, your love is
  real" 13,50 € (según el buscador: exportar datos "para análisis externo",
  Trading Analytics, 100 plantillas de sniper con prioridad), "AlecaFrame
  Enjoyer" 45 € (sin anuncios, betas, temas, 200 plantillas). Patreon no deja
  leer los beneficios sin sesión; la wiki dice que la exportación de Stats es
  libre. Ver 6.4.
- Código .NET sin ofuscar y con símbolos; HTML/JS sin minimizar. "No es open
  source" pero legible. Google Analytics anónimo.

---

## 2. De dónde sale cada dato

| Dato | Mecanismo en AlecaFrame | Evidencia | Farmadex |
|---|---|---|---|
| Inventario completo (piezas, reliquias, mods, rivens, platino, ducados, trazas, fragmentos, Helminth, configuraciones) | **Overwolf lee la memoria de `Warframe.x64`** y entrega el JSON como evento `match_info.inventory` (campos `Slots`, `PremiumCredits`... del inventario privado de DE). `PROCESS_VM_READ` + `VirtualQueryEx` + `ReadProcessMemory`, marcador `LastInventorySync` | Docs de Overwolf; FAQ de WFHelper; FAQ de AlecaFrame G6 (solo en pantallas de carga), T4 (Overwolf antes que el juego), T5/T14 (Warframe no como administrador) | **No se copia el mecanismo.** Se consume lo que AlecaFrame exponga oficialmente (sección 6) |
| Maestría (dominado, XP) | Mismo JSON; cálculo propio ±100 XP | Wiki | Solo `mr` (rango) por la API. XP por objeto: no |
| Objeto resaltado / riven de chat / reroll | Eventos de Overwolf `match_info.highlighted` y `chat` (memoria). Deducción: overlays de riven solo en inglés | Docs de Overwolf; tabla de idiomas | No |
| Historial de trades | Deducción: mensajes del chat vía evento `chat`, regex en inglés | "Trade history won't be recorded" fuera del inglés; `EE.log` no registra chat | **Sí, vía API** (`trades`), solo si el usuario juega en inglés; el usuario juega en español, así que en la práctica no |
| Series de platino/ducados/endo/créditos/aya/MR | Instantáneas del inventario subidas a `stats.alecaframe.com` | OpenAPI `PlayerStatsDataPoint` | **Sí, vía API** con token |
| Reliquias poseídas | Inventario → servidor | OpenAPI `getRelicInventory` | **Sí, vía API** con token |
| Overlay de recompensas: nombres | **Captura + OCR** (escalado, 1080 px, profundidad de campo, choque con WFInfo, `relicLogs`) | FAQ T6-T9; tabla de idiomas | Ya hecho en Farmadex |
| Platino, ducados, bóveda de cada recompensa | warframe.market + datos del juego | Wiki | Ya hecho |
| Datos estáticos, estado del mundo | CDN propio; worldstate público | — | Ya hecho |
| Rivens (precios, sniper), Trading Analytics | Servidor propio procesando WFM y riven.market | Wiki | No (infraestructura suya) |
| Cuenta de warframe.market | API de WFM con sesión de WFM | FAQ M1-M3 | Posible; decisión de producto |
| Overlay en pantalla completa exclusiva | Overwolf inyectado (choca con RivaTuner) | FAQ T10, T15 | No; ventana sin bordes |
| Credenciales de Warframe | **No las pide** | Toda la wiki | — |

---

## 3. Contraste con lo que Farmadex ya tiene

**Cubierto (igual o mejor)**: dónde se consigue cada componente (Farmadex tiene
un buscador bilingüe con erratas y cadena pieza → reliquia → misión, que
AlecaFrame no tiene como tal); precios WFM; overlay de recompensas por OCR con
disparo por `EE.log` (`ProjectionRewardChoice.lua`), en español; estado del
mundo completo; objeto bajo el cursor; datos abiertos sin servidor.

**A medias**: seguimiento de lo que tienes (objetivos manuales +
`progreso_eventos`, sin historial consultable); recomendar qué abrir (se sabe
qué reliquia suelta cada objetivo, no cuáles tienes ni su valor esperado);
ducados (solo en el overlay); avisos (cuenta atrás, sin notificaciones);
favoritos (solo objetivos); árbol de crafteo (solo un nivel); `EE.log` (cinco
líneas).

**Falta**: fundición con estado real; inventario vendible y sets; ayudante de
maestría; rivens; estadísticas de cuenta; cuenta de WFM; overlay de
recomendación de reliquia; API propia.

---

## 4. Normas de Digital Extremes y postura sobre AlecaFrame

### 4.1 Lo público

- **"Third-Party Software and You"** ([DE]Dudley, foros, agosto de 2022): "If
  you use external software in conjunction with Warframe, then you do so at your
  own risk." Sin lista blanca ni negra; baneos por trampa/explotación/AFK
  definitivos. **Actualización del 23-08-2022 sobre Overwolf**: "lo anterior
  también se aplica a esas apps (y a todo el resto de software de terceros)";
  la implicación de DE con Overwolf ha sido "simplemente tener conversaciones
  para asegurar que no se incumplen el EULA y las condiciones".
- **EULA §7**: prohibidos los programas no autorizados que "intercept, emulate,
  or redirect any communication between the Services and us" y los que
  automatizan o interactúan con el servicio. Versiones anteriores nombraban
  expresamente "software that reads areas of RAM".
- **Precedente WFInfo**: un desarrollador de DE declaró en el foro que usarlo
  (captura + OCR + `EE.log`) no acarrea baneo. Es la categoría de Farmadex.
- **AlecaFrame** (FAQ G1): "safe to use"; lo arriesgado "is handled by
  Overwolf, which is explicitly said to be fine in DE's Third Party Policy",
  con enlace a un comentario del foro (hilo 1383123) que no se ha podido leer
  (403). Pie de web: "not affiliated with Digital Extremes".
- **Overwolf**: "Overwolf and all official Overwolf apps will NOT get you
  banned"; trabaja "directly with game publishers"; no menciona a DE.
- **Comunidad**: hilos de Steam con rumores de baneos sin pruebas y usuarios con
  años sin incidentes. Ningún caso documentado ni desmentido oficial.

### 4.2 Condiciones de uso de las herramientas (que el correo de DE obliga a respetar)

- **AlecaFrame no publica condiciones de uso ni política de privacidad** como
  documento (comprobado en web, wiki y pie de página). Lo que hay es la FAQ y
  la página API, y de ahí salen las reglas aplicables:
  - A2: sin clave de API, **límite de 1 petición/s con cola de 30 por IP**.
  - A3: el `userHash` es personal, "Please DO NOT share this with other people,
    use public tokens instead if you want to share your data". Los tokens
    públicos caducan al año y se pueden revocar.
  - API: "This is therefore just a 'personal' API"; para agregar datos de otros
    hay que pedirles su token público.
  - G2/A4: datos anónimos; el usuario puede desactivar Stats y pedir borrado.
- **Overwolf, Platform Terms of Use (23-06-2024)**: §7.2(iii) prohíbe "reverse
  engineer, decompile or disassemble, decrypt or attempt to derive the source
  code"; §7.2(iv) prohíbe "robot, spider, crawler, scraper, or other automated
  means to access or monitor" la plataforma; §7.2(vi) interferir con los
  servicios. **Consecuencia**: descifrar `lastData.dat` (lo que hacen Sentinel,
  WFHelper y `alecaframe-inventory-parser` con una clave extraída de la app)
  queda **fuera** para Farmadex. Consumir la API pública con un token que el
  propio usuario genera **no** es ninguna de esas cosas: es el uso previsto.

### 4.3 La autorización de Warframe Support al usuario

Recibida por correo en septiembre de 2026 en respuesta a la pregunta del
usuario sobre usar Overwolf y AlecaFrame para obtener datos de su cuenta y
llevarlos a una aplicación de terceros propia. Texto según lo transmitido por
el coordinador (**pegar aquí el literal del correo cuando se tenga**):

> DE **no tiene inconveniente**, siempre que se respeten las condiciones de uso
> de esas herramientas y las políticas de Warframe, y que no se afecte al
> servicio, a otros jugadores ni a la seguridad de las cuentas. Esto **no**
> autoriza a acceder a información protegida, modificar datos de cuentas ni
> eludir mecanismos de seguridad.

Lectura operativa, que es la que sigue el resto del informe:

| Queda autorizado | Queda excluido |
|---|---|
| Que el usuario use AlecaFrame/Overwolf y que Farmadex consuma **lo que AlecaFrame ofrece oficialmente**: su API con el token del usuario y sus exportaciones | Escribir nuestro propio lector de memoria del proceso: "información protegida", EULA §7, y se rompe en cada parche |
| Guardar en local, en el equipo del usuario, los datos que él mismo ha autorizado compartir | Descifrar la caché de AlecaFrame: "eludir mecanismos de seguridad" + Overwolf §7.2(iii) |
| Respetar el límite de 1 petición/s y la caducidad del token | Cualquier petición con la sesión del jugador a `api.warframe.com`; pedir o guardar credenciales de Warframe |
| Fallar limpio y seguir funcionando igual sin AlecaFrame | Compartir, subir o agregar datos de otros jugadores sin su token |

---

## 5. Vincular la cuenta de Warframe directamente: qué es posible y qué no

### 5.0 Lo que Farmadex no hará bajo ningún concepto

1. No pedirá al usuario su correo ni su contraseña de Warframe.
2. No guardará credenciales, tokens de sesión ni el `nonce` del cliente.
3. No usará la sesión del jugador (juego, lanzador o warframe.com) para hacer
   peticiones a los servidores de DE.
4. No leerá la memoria de `Warframe.x64` ni inyectará nada, ni directamente ni
   a través de otra plataforma.

### 5.1 Qué dicen hoy las herramientas vivas y qué pasa al probarlo

Se han leído las instrucciones **actuales** (HTML servido el 20-09-2026) de
browse.wf (`/profile`) y de FrameHub (gist `FRAMEHUB_LINK_ACCOUNT.md`), y el
código del parser de WFCD. Las tres coinciden en el mismo procedimiento, y las
tres fallan hoy al ejecutarlo:

| Paso documentado por la comunidad | Comprobación real (20-09-2026) |
|---|---|
| **Obtener el `accountId`**: "log in on warframe.com then visit `https://www.warframe.com/api/user-data` to find it after `user_id`" (browse.wf); "Method 1 (Recommended)", mismos pasos (FrameHub) | **404** HTML del sitio, **con sesión iniciada** (probado por el usuario) y sin ella (`/api/user-data`, `/api/user`, `/es/api/user-data`, `/en/api/user-data`, `/api/v1/user-data`, `api.warframe.com/api/user-data`). No es un 401 ni una redirección a login: la ruta **no existe**. La web nueva de DE (`www-static.warframe.com/build/assets/warframe-*.js`) no contiene ninguna referencia a `user-data`, `user_id` ni `/api/` |
| **Alternativa de FrameHub, "Method 2"**: buscar `Logged in <USERNAME>` en `EE.log` y copiar lo que va entre paréntesis | La línea real del usuario es `Logged in <cuenta del usuario>`, **sin paréntesis ni id**. Método caducado |
| **Descargar el perfil**: `https://api.warframe.com/cdn/getProfileViewingData.php?playerId=<ACCOUNTID>` y guardar el JSON; FrameHub incluso enlaza el de [DE]Rebecca (`505875fb1a4d80894a000000`) como ejemplo que funciona | **409 con cuerpo vacío** para [DE]Rebecca y para otras dos cuentas reales (fixtures de WFCD), con y sin cabeceras de navegador, con `Referer: https://browse.wf/`. Id falso → 409 "Could not find requested account"; nick → 409 "No account or guild ID specified". Y el host de consola `api-ps4.warframe.com` responde a la de Rebecca **"Retry with PC account: 505875fb1a4d80894a000000,[DE]Rebecca"**: el servidor resuelve la cuenta y sabe que es de PC, pero el host de PC no la sirve a peticiones anónimas |
| `api.warframestat.us/profile/{id}` (proxy de WFCD) | **timeout**. WFCD documenta que DE lo bloquea |
| Rutas antiguas `content.warframe.com/dynamic/*` | **404** (también `worldState.php`; lo público vive ahora en `api.warframe.com/cdn/`) |

FrameHub ya avisaba: "Due to aggressive rate limiting by DE, this feature is no
longer exposed in the UI". browse.wf obliga a subir el JSON a mano. Ninguna de
las dos ha actualizado sus pasos, así que **no hay hoy una secuencia
verificada** con la que un jugador obtenga su JSON de perfil desde el
navegador. Otras herramientas revisadas no ofrecen nada distinto: Overframe no
importa perfiles; semlar.com solo tiene parser de muertes sobre `EE.log`;
OpenWF (`openwf.io/import`) devuelve una página vacía.

Cuando el endpoint funcionaba (fixtures de 2024 y 2025): JSON de 600-625 KB
con `Results[0]` (`PlayerLevel` = MR, `LoadOutInventory.XPInfo` con `{ItemType,
XP}` de ~700 objetos, `Missions` con ~455 nodos y `Tier`, `PlayerSkills` =
intrínsecos, `Affiliations` = sindicatos, clan, `Created`, `Wishlist`), `Stats`
(47-67 contadores), `TechProjects`, `XpComponents`, `XpCacheExpiryDate`.
**Nunca inventario.** Es el formato que ya lee `src/farmadex/perfil/lector.py`.

### 5.2 Conclusión sin adornos

**La importación manual del perfil se ha quedado sin fuente.** No se ha
encontrado ninguna vía verificada en 2026 para que un jugador obtenga su
`accountId` desde el navegador, y aunque lo tuviera, el endpoint de perfil de
PC no responde a peticiones anónimas. Solo quedan dos comprobaciones que
requieren la sesión o el equipo del usuario y que no se pueden hacer desde
aquí. Si las dos fallan, la única fuente de maestría es el OCR (5.4).

### 5.3 Dos comprobaciones de un minuto (las hace el usuario)

1. **¿Su navegador con sesión recibe el perfil?** Abrir en el navegador donde
   tiene iniciada la sesión de warframe.com esta URL pública de ejemplo (la
   cuenta de [DE]Rebecca, la misma que publica FrameHub; es inofensiva y no
   consume nada suyo):
   `https://api.warframe.com/cdn/getProfileViewingData.php?playerId=505875fb1a4d80894a000000`.
   - Si ve un JSON grande que empieza por `{"Results":[{"AccountId"...`, el 409
     que recibimos es un filtro para peticiones sin sesión/cookies de DE y la
     **descarga manual desde su navegador funciona**; solo falta su id (punto
     2). Farmadex seguirá sin hacer esa petición (5.0).
   - Si ve una página en blanco o un error, el endpoint está cerrado también
     para navegadores y **no hay importación de perfil**. Pasar a 5.4.
2. **¿Está su `accountId` en `EE.log` después de todo?** No en `Logged in`,
   pero FrameHub afirma que "you can actually find the account IDs of players
   in your squad by searching for `AddSquadMember`", y el código de Sentinel
   confirma el formato `AddSquadMember: <nombre>, mm=<24 hex>, squadCount=N` y
   que **el propio jugador también aparece** en esas líneas (Sentinel las
   filtra con `getName() != local_name`). Buscar en `EE.log` la cadena
   `AddSquadMember: <cuenta del usuario>, mm=` (hace falta haber estado en una escuadra
   con la app... con el juego abierto): el valor tras `mm=` es el candidato.
   **Verificación sin tocar el endpoint de PC**: pedir
   `https://api-ps4.warframe.com/cdn/getProfileViewingData.php?playerId=<candidato>`;
   si responde `Retry with PC account: <candidato>,<cuenta del usuario>`, ese es su
   `accountId` (una sola petición; el host de consola no está bloqueado y
   devuelve el nombre). Si el valor `mm=` no fuera el `accountId`, responderá
   "Could not find requested account" y se descarta la hipótesis.

Si 1 y 2 salen bien: los pasos para el usuario quedan en **abrir en su
navegador `https://api.warframe.com/cdn/getProfileViewingData.php?playerId=<su
id>`, guardar el JSON (Ctrl+S) y arrastrarlo a Farmadex**, cada pocas semanas.
Farmadex no hace ninguna petición a DE. Si cualquiera de las dos falla, se
retira b1 del plan.

### 5.4 Alternativa: OCR de las pantallas de perfil y equipamiento del propio jugador

Es la candidata evidente si 5.3 falla, y la única que no depende de DE ni de
AlecaFrame. Farmadex ya tiene RapidOCR, captura por región y casado difuso
contra el catálogo.

**Qué pantalla**: dentro del juego, Perfil → **Equipamiento**, por categoría
(warframes, primarias, secundarias, cuerpo a cuerpo, robóticos, compañeros,
vehículos, archcañones, archmelee, amps). Cada entrada muestra nombre y rango
(0-30, 40 en los que llegan a 40) y el juego **oculta lo que nunca ha tenido
rango 1** (wiki oficial): lo que no aparece no está dominado, lo que aparece
con rango máximo sí.

**Cuántas capturas**: para una cuenta con ~500-700 objetos con XP (los dos
perfiles reales medidos tienen 524 y 702 entradas en `XPInfo`) y 20-30 filas
visibles por pantalla a 1080p, **25-35 capturas** repartidas en 10 categorías,
pasando página el usuario y pulsando el atajo de Farmadex en cada una. Unos
10-15 minutos la primera vez; después solo las categorías que hayan cambiado.

**Precisión esperable**: nombres ≈ 95 % tras casado difuso contra el catálogo
(mismo motor que ya casa «Chasis de Ash Prime»); rango numérico ≈ 90 % (texto
pequeño; WFInfo tuvo que reescalar zonas pequeñas); estado *dominado*
(rango máximo) por encima del 95 % porque basta distinguir 30/40 de cualquier
otro número. Con revisión manual de las filas marcadas en duda, el resultado
útil ("dominado / a medias / nunca usado") es fiable. Lo que **no** da el OCR y
sí daba el JSON: XP exacta, nodos completados, intrínsecos, sindicatos,
estadísticas. Nodos e intrínsecos se podrían leer de sus pantallas propias
(mapa estelar y pantalla de intrínsecos), pero son otras 15-20 capturas y valor
bajo; se dejan fuera.

**Coste**: 15-25 h (regiones de la pantalla de perfil, lectura de nombre +
rango por fila, paginación, pantalla de revisión) más mantenimiento cuando DE
cambie la interfaz.

### 5.5 Qué cambia en `src/farmadex/perfil/` si la fuente pasa a ser el OCR

El paquete no se tira; cambia la **entrada**, no el almacén ni la lógica de
maestría:

- `lector.py` (`cargar`, `interpretar` → `Perfil` con `rango`, `xp_por_item`,
  nodos, `intrinsecos`, sindicatos) se conserva tal cual para el JSON, por si
  5.3 acaba funcionando o DE reabre el endpoint.
- Se añade un segundo constructor, p. ej. `perfil/desde_ocr.py`, que produce
  el mismo `Perfil` a partir de las filas leídas (`unique_name` casado, rango
  leído, categoría) con los campos que el OCR no da a `None`/vacíos: `rango`
  (MR) leído de la cabecera del perfil, `xp_por_item` **sintética**: `umbral`
  si el rango leído es el máximo, y `rango × (umbral / rango_max)` si no
  (aproximación monótona suficiente para "a medias"), nodos/intrínsecos/
  sindicatos vacíos.
- `maestria.py`: añadir `estado_por_rango(rango, rango_max)` junto a
  `estado_por_xp`, para no pasar por XP sintética cuando se sepa el rango
  directo; `umbral_xp` y `es_masterizable` sirven tal cual.
- `almacen.py`: `guardar(usuario, perfil, ruta)` acepta el `Perfil` del OCR sin
  cambios; conviene añadir una columna `origen` (`json`/`ocr`) y `leido_en`
  por fila para que la interfaz distinga lo verificado de lo leído, y permitir
  **fusión** (el OCR de una categoría no debe borrar las demás): `guardar`
  pasa a actualizar por categoría en vez de sustituir todo.
- `resumen`, `estado_de`, `estados_de_todos`, `pendientes_por_categoria`,
  `resumen_maestria` no cambian. `nodos_pendientes`/`nodo_hecho` devolverán
  "desconocido" cuando no haya nodos.

---

## 6. La API oficial de AlecaFrame y sus exportaciones

### 6.1 Base, autenticación y límites

- **Base**: `https://stats.alecaframe.com/api`. OpenAPI 3.0.1 ("StatsBackend
  v1") en `https://stats.alecaframe.com/api/swagger/v1/swagger.json`; interfaz
  en `/api/swagger/index.html`.
- **Sin clave de API, sin cuenta de AlecaFrame, sin cuenta de Overwolf, sin
  Patreon.** Dos credenciales posibles, ambas las genera y copia el usuario:
  - `userHash`: identificador personal anónimo, visible en la pestaña Stats.
    Da acceso a **todo** lo tuyo. La FAQ pide no compartirlo. Opcionalmente
    acompañado de `secretToken`.
  - **Token público**: se crea en Stats → "Create Public Link", eligiendo qué
    partes compartir → "Generate token". Caduca al **año**, revocable desde la
    app, y los datos que devuelve son **vivos**, no una instantánea.
- **Límite**: 1 petición/s con cola de 30, por IP (FAQ A2). Sin cabeceras de
  rate limit en las respuestas (comprobado).
- **Errores observados**: token inválido → `500` con
  `application/problem+json` y `"detail":"Invalid token"`; `userHash`
  desconocido → `404`; sin credencial → `401`.
- **Recomendación para Farmadex: usar solo el token público**, con las partes
  que el usuario elija. Es la credencial que AlecaFrame diseñó para terceros,
  revocable, y no expone el `userHash`.

### 6.2 Endpoints

| Método y ruta | Parámetros | Devuelve |
|---|---|---|
| `GET /api/stats/{userHash}` | `userHash` (path), `secretToken` (query, opcional) | `PlayerStatsData` completo del propio usuario |
| `GET /api/stats/public` | `token` (query, obligatorio) | `PlayerStatsData` filtrado por las partes autorizadas en el token |
| `GET /api/stats/public/getRelicInventory` | `publicToken` (query, obligatorio; el token debe incluir la parte *Relics*) | **Binario** little-endian (declarado como `application/json`, pero es binario): `uint32` número de reliquias; por reliquia 9 bytes: `uint8` tipo (0 Lith, 1 Meso, 2 Neo, 3 Axi, 4 Requiem), `uint8` refinamiento (0 Intact, 1 Exceptional, 2 Flawless, 3 Radiant; 4/5/6 repiten Exceptional/Flawless/Radiant, presumiblemente un legado a tratar como 1/2/3), `char[3]` nombre corto (`"L1 "`, `"B21"`), `uint32` cantidad |

**Esquema `PlayerStatsData`** (del OpenAPI):

- `generalDataPoints[]` — `PlayerStatsDataPoint`: `ts` (fecha-hora), `plat`,
  `credits`, `endo`, `ducats`, `aya`, `relicOpened`, `trades`, `mr`,
  `percentageCompletion` (enteros). Una fila por instantánea mientras
  AlecaFrame está abierto; la app sube cuando el inventario se refresca
  (pantallas de carga).
- `trades[]` — `PlayerStatsTrade`: `ts`, `tx[]` y `rx[]` (`name`,
  `displayName`, `cnt`, `rank`), `user` (con quién), `type` (0 Sale, 1
  Purchase, 2 Trade), `totalPlat`. **Solo se rellena con el juego en inglés.**
- `lastUpdate`, `userHash`, `publicParts`, `usernameWhenPublic`.

**Partes del token público** (`PublicLinkParts`, máscara de bits): 1 Trades, 2
Platinum, 4 Ducats, 8 Endo, 16 Credits, 32 AccountData, 64 Aya, 128 Relics.
Para Farmadex interesan **Relics + Platinum + Ducats** (y Aya/Endo/Credits si
se quiere el panel completo). Dejar fuera Trades y AccountData: no aportan y
son lo más personal.

### 6.3 Cómo obtiene el usuario su token, paso a paso

1. Tener AlecaFrame instalado (tienda de Overwolf), Overwolf arrancado **antes**
   que Warframe, y haber entrado al juego al menos una vez con la app abierta
   (para que el inventario haya sincronizado: G6, T4).
2. En AlecaFrame, pestaña **Stats**. Comprobar que la recogida de datos no está
   desactivada en ajustes.
3. **"Create Public Link"** → marcar las partes a compartir: **Relics**,
   **Platinum**, **Ducats** (y las que quiera) → **"Generate token"**.
4. Copiar el token y pegarlo en **Farmadex → Ajustes → AlecaFrame → Token**.
   Farmadex hace una primera petición de prueba y enseña "N reliquias, última
   actualización hace X".
5. Anotar la fecha: caduca al año. Farmadex avisará a los 11 meses. Si el
   usuario revoca el token en AlecaFrame, Farmadex pasa a "sin datos" sin
   romper nada.

### 6.4 Exportaciones de la aplicación

- **Stats → Export**: CSV y JSON al Escritorio con "todo lo que la pestaña
  Stats ha registrado": los mismos `generalDataPoints` y `trades` del esquema
  anterior. Es una instantánea: hay que repetirla a mano cada vez. La API con
  token da lo mismo en vivo, así que **para Farmadex la exportación de Stats es
  redundante**; solo tendría sentido como importación de respaldo si el
  servidor de AlecaFrame no responde. Nota: el buscador atribuye "exportar
  datos para análisis externo" a un nivel de Patreon; la wiki presenta la
  exportación de Stats como libre. No se ha podido confirmar sin sesión de
  Patreon; irrelevante si se usa la API.
- **No existe exportación oficial de inventario, fundición, reliquias (salvo
  la API) ni maestría**. Lo confirma también que las herramientas que quieren
  ese inventario (Sentinel, WFHelper, `alecaframe-inventory-parser`) recurran a
  descifrar `lastData.dat`.
- **Caché local `%LocalAppData%\AlecaFrame\lastData.dat`**: JSON de inventario
  cifrado con AES-CBC y clave fija. Contiene (claves que lee Sentinel):
  `InventoryJson` con `Suits`, `LongGuns`, `Pistols`, `Melee`, `MiscItems`
  (`ItemType`, `ItemCount`), `Recipes`, `XPInfo`, `PeriodicMissionCompletions`,
  `LastSortieReward`... es decir, **todo** lo que falta. **Farmadex no lo
  toca** (4.2 y 4.3).

### 6.5 Qué cubre cada vía de lo que antes era imposible

| Dato | API AlecaFrame (token) | Export Stats | JSON de perfil de DE (manual, si funciona) | Resultado |
|---|---|---|---|---|
| **Reliquias poseídas con cantidad por refinamiento** | **Sí**, en vivo | No | No | **Se consigue** |
| **Platino, ducados** (saldo actual y evolución) | **Sí** (última instantánea + serie) | Sí (instantánea) | No | **Se consigue**, con el retardo de la última sincronización de AlecaFrame |
| Endo, créditos, aya | Sí | Sí | No | Se consigue |
| Rango de maestría (número) | Sí (`mr`) | Sí | Sí (`PlayerLevel`) | Se consigue |
| Reliquias abiertas (contador) y número de trades | Sí | Sí | No | Se consigue |
| Historial de trades | Sí, **solo con juego en inglés** | Ídem | No | En la práctica no (el usuario juega en español) |
| **Qué objetos tienes dominados / XP por objeto** | No | No | **Sí** (`XPInfo`), pero sin fuente verificada hoy (5.1-5.3) | b1: JSON si 5.3 sale bien; si no, **OCR de Perfil → Equipamiento** (5.4) |
| Nodos y Camino de Acero completados, intrínsecos, sindicatos | No | No | Sí, misma condición | Solo con el JSON; el OCR no lo cubre |
| **Piezas y planos con cantidades** | **No** | No | No | **Sigue sin conseguirse** |
| **Mods, arcanos** (poseídos, rango, equipados) | No | No | No | **Sigue sin conseguirse** |
| **Trazas del Vacío** | No | No | No | **Sigue sin conseguirse** |
| Fundición (en construcción, listo), fragmentos, Helminth, rivens poseídos | No | No | No | **Sigue sin conseguirse** |

Con reliquias + platino + ducados reales, el planificador de reliquias deja de
ser "sin inventario" y pasa a ser el de AlecaFrame en su parte útil: qué abrir
de lo que tienes, valor esperado, ducados para Baro. Lo que no se consigue por
ninguna vía oficial (piezas, mods, trazas) se queda en recuento manual +
OCR + lo que el propio Farmadex vaya viendo en las recompensas.

### 6.6 Sobre la vinculación directa

Sigue como en la sección 5: sin vía automática legítima, y la importación
manual del perfil **sin fuente verificada** a 20-09-2026 (queda condicionada a
las dos comprobaciones de 5.3; si fallan, la maestría sale por OCR, 5.4). La
integración con AlecaFrame no cambia eso, porque AlecaFrame tampoco expone el
`accountId` ni el JSON de perfil.

---

## 7. Diseño de la integración en Farmadex

### 7.1 Principios

- **Opcional y silenciosa**: sin token, Farmadex es exactamente el de hoy. No
  se detecta ni se lee nada de AlecaFrame en disco; no hace falta que esté
  instalado en el equipo (el token funciona desde cualquier PC).
- **Solo API oficial con token público.** Nada de `userHash` por defecto, nada
  de `lastData.dat`, nada de Overwolf.
- **Una fuente más**, con el mismo tratamiento que worldstate o WFM: caché
  local, fecha de última actualización visible, degradación limpia.

### 7.2 Módulos

- `farmadex/online/alecaframe.py` — cliente HTTP (reutiliza `online/http.py`):
  `obtener_stats(token) -> DatosCuenta`, `obtener_reliquias(token) ->
  list[ReliquiaPoseida]`, parser binario del inventario de reliquias
  (`struct` little-endian, normalizando refinamientos 4/5/6 a 1/2/3), mapeo
  del nombre corto (`L1`, `B21`) + era al `unique_name` de la reliquia en
  `indice.sqlite` (la tabla de reliquias ya tiene era y nombre). Errores
  tipados: `TokenInvalido` (500 "Invalid token"), `SinRespuesta`.
- `farmadex/estado/cuenta_externa.py` — persistencia en `usuario.sqlite`:
  - `reliquias_poseidas(relic_id, refinamiento, cantidad, actualizado_en)`
    (se sustituye entera en cada refresco).
  - `cuenta_puntos(ts, plat, ducats, endo, credits, aya, mr, relic_opened,
    trades)` (se añaden solo las filas nuevas por `ts`).
  - `cuenta_fuente(nombre='alecaframe', ultima_ok, ultimo_error,
    token_creado_en)`.
- `farmadex/tareas.py` — tarea periódica `RefrescoAlecaFrame` como las de
  worldstate: cada **30 min** mientras el juego está abierto (ya se sabe por el
  hilo de `EE.log`), una vez al arrancar, y bajo demanda con el botón
  "Actualizar" (enfriamiento 60 s). Dos peticiones por refresco, espaciadas ≥ 1
  s: muy por debajo del límite.
- `ui/pestana_ajustes.py` — bloque "AlecaFrame": campo de token (enmascarado),
  botón probar, estado ("428 reliquias, platino 1.240, hace 12 min"), enlace a
  los pasos de 6.3, aviso de caducidad, botón "Olvidar token".
- Consumidores: `ui/pestana_buscador.py` (ficha de reliquia: "tienes 3 Intact,
  1 Radiant"), planificador de reliquias (a2), overlay de recompensas ("te
  quedan N de esta reliquia"), pestaña Historial (a1: platino/ducados reales
  junto a lo estimado).

### 7.3 Refresco y frescura

- Los datos en AlecaFrame se actualizan **solo en pantallas de carga** del
  juego (G6); su servidor recibe lo que la app sube. Farmadex enseña siempre
  `lastUpdate` del servidor, no la hora de la petición, y marca en ámbar si
  tiene más de 2 h.
- En misiones infinitas las reliquias se quedan viejas (aviso propio de
  AlecaFrame): Farmadex descuenta localmente una unidad de la reliquia abierta
  detectada por `EE.log` hasta el siguiente refresco (`ajuste_local` en
  memoria, se descarta al refrescar).

### 7.4 Guardado del token

- **Cifrado con DPAPI de Windows** (`CryptProtectData`, ámbito usuario actual,
  vía `ctypes`; sin dependencias nuevas), guardado en base64 en `config.json`
  bajo `alecaframe.token_dpapi`. Solo el mismo usuario de Windows en el mismo
  equipo puede descifrarlo. **Nunca** en el registro, nunca en claro, nunca en
  los logs (el log escribe `token=***`).
- "Olvidar token" borra la clave del `config.json` y vacía las tablas
  `reliquias_poseidas` y `cuenta_puntos` si el usuario lo pide.
- El token es de AlecaFrame y revocable por el usuario desde AlecaFrame:
  la exposición máxima si alguien copiara `config.json` es la lista de
  reliquias y el platino del usuario, no su cuenta.

### 7.5 Sin AlecaFrame

- Sin token: el bloque de Ajustes explica qué aporta y cómo obtenerlo; el resto
  de la aplicación no cambia; las funciones que lo usan enseñan su versión
  manual (planificador con "reliquias que tengo" a mano, historial sin platino
  real).
- Token inválido/revocado/caducado: mensaje en Ajustes y en la barra de estado,
  se conservan los últimos datos con su fecha, no se reintenta hasta que el
  usuario cambie el token.
- Servidor caído: se conservan los últimos datos; reintento en el siguiente
  ciclo de 30 min.

### 7.6 Pruebas

Fixtures: un JSON de `PlayerStatsData` y un binario de reliquias construido a
mano (incluyendo refinamientos 4/5/6 y `Requiem`), respuestas 401/404/500,
token caducado. Test del mapeo nombre corto → reliquia del índice sobre todas
las reliquias del catálogo (debe casar el 100 % o listar las que no).

---

## 8. Propuesta priorizada

Ordenada por valor para quien juega a diario. Horas con pruebas.

### (a) Con lo que ya tenemos (más la API de AlecaFrame), aporta mucho

| # | Función | Qué resuelve | Datos y origen | Horas |
|---|---|---|---|---|
| a1 | **Integración con AlecaFrame** (sección 7): reliquias poseídas, platino, ducados | Base de todo lo demás. "Tienes 3 de esta reliquia", platino y ducados reales | API con token público (6.2); DPAPI; tablas nuevas en `usuario.sqlite` | 10-14 |
| a2 | **Planificador de reliquias** con las reliquias reales | Qué abrir ahora: valor esperado en platino y ducados por reliquia y refinamiento, ajustado por escuadra; "mejor para mis objetivos"; "mejor para Baro". Con a1 es el Relic Planner de AlecaFrame menos los filtros de maestría | Drops (índice), precios WFM, ducados, objetivos, reliquias de a1 (o lista manual si no hay token) | 12-18 |
| a3 | **Historial de recompensas y estadísticas de sesión** | Qué te ha salido hoy, cuántas reliquias, valor estimado; con a1, platino/ducados reales al lado | OCR ya existente + `EE.log` (`reliquia_abierta`, `reliquia_elegida`, `mision_completada`); comprobar si el log deja la recompensa elegida, si no, un clic en el overlay | 8-12 |
| a4 | **Avisos del estado del mundo ligados a objetivos** | "Fisura Neo en Camino de Acero", "Baro ha llegado", "esta invasión da Forma" | Worldstate + `eras_necesarias()` + toasts (`QSystemTrayIcon.showMessage`) | 6-10 |
| a5 | **Overlay de recompensas enriquecido** | Mejor opción marcada, **volumen de ventas** (WFM `statistics`), "te ha salido N veces", "te quedan N de esta reliquia" (a1) | WFM, historial a3, a1 | 4-8 |
| a6 | **Ranking ducados/platino y ayuda para Baro** | Qué vender a Baro y qué guardar; con a1, "tienes X ducados, te faltan Y para lo que quieres de Baro" | Índice + a1 | 3-5 |
| a7 | **Favoritos** con "favoritos primero" | Copia directa | Local | 3-4 |
| a8 | **Contador de misiones por sesión desde `EE.log`** | "Llevas 9 rondas de Hepit" | Líneas `OnStateStarted, mission type=`, `Client loaded ... MissionInfo`, `EOM missionLocationUnlocked=` (verificar con log real) | 4-6 |
| a9 | **Exportar CSV/JSON** de objetivos, historial y reliquias | Igual que Stats → export | Local | 2-3 |

Total (a): 52-80 h. a1 + a2 + a3 son el grueso del valor.

### (b) Se puede, pero cuesta trabajo o datos nuevos

| # | Función | Datos, origen y coste real | Horas |
|---|---|---|---|
| b1 | **Maestría del jugador**, en este orden: (i) importar el JSON de perfil de DE **solo si** las dos comprobaciones de 5.3 salen bien (lector ya construido en `src/farmadex/perfil/`); (ii) si no, **OCR de Perfil → Equipamiento** (5.4) alimentando el mismo paquete (5.5) | (i) 2-4 h de interfaz sobre lo ya hecho; (ii) 15-25 h: 25-35 capturas la primera vez, nombres ≈ 95 %, dominado > 95 %, con revisión manual. A fecha de hoy la vía (i) **no tiene fuente verificada** | 2-4 / 15-25 |
| b2 | **Overlay de recomendación de reliquia** al elegir fisura | Requiere a2 y localizar la línea de `EE.log` de esa pantalla con un log real | 6-10 |
| b3 | **Árbol de crafteo con recursos totales** y lista manual de piezas | `components` de WFCD, recursivo; marcado manual | 12-20 |
| b4 | **Inventario de piezas por OCR** ("Snap-it"): solo pantallas de piezas prime y planos, con corrección manual | Única vía a las cantidades de piezas; 20-40 páginas; nombres ≈ 95 %, cifras ≈ 85-90 %; frágil ante cambios de UI | 25-40 |
| b5 | **Cuenta de warframe.market** (ver órdenes, crear venta desde ficha/overlay) | API v2 de WFM con sesión de WFM; `plan.md` §5 lo excluyó por producto, no por normas | 15-25 |
| b6 | **Ayudante de maestría** sobre el estado de b1 (JSON u OCR) | WFCD `masteryReq`; `perfil/almacen.py` (`pendientes_por_categoria`, `resumen_maestria`) | 12-25 |
| b7 | **Valoración de rivens offline** por OCR + hoja comunitaria | Muy frágil; solo si el usuario tradea rivens | 30-50 |
| b8 | **Sniper local ligero** en WFM | Sondeo cada 60-120 s, sin riven.market | 8-12 |
| b9 | **Panel de escuadra desde `EE.log`** (sin IPs de terceros) | Líneas `AddSquadMember`, `HOST MIGRATION` | 6-10 |

### (c) No se puede sin violar las normas o sin la infraestructura de AlecaFrame

| Función | Por qué no |
|---|---|
| **Piezas y planos con cantidades, mods, arcanos, trazas, fundición, rivens poseídos, fragmentos, Helminth** de forma automática | No salen por la API ni por las exportaciones de AlecaFrame. Solo están en su caché cifrada (fuera: Overwolf §7.2(iii), "eludir mecanismos de seguridad") o en la memoria del juego (fuera: 5.0). Alternativa parcial: b4 |
| **Vinculación automática de la cuenta de Warframe** | `accountId` no está en `EE.log`/`EE.cfg`/registro; el endpoint de perfil no responde sin sesión; usar la sesión está vetado |
| **Chat Riven / Riven Reroll** como AlecaFrame; **historial de trades** en español | Eventos de Overwolf desde memoria; `EE.log` no registra chat; el historial de trades de la API solo se rellena en inglés |
| **Riven Explorer con precios**, **Sniper** competitivo, **Trading Analytics**, enlaces públicos, API propia | Servidor y base histórica de AlecaFrame |
| **Overlay en pantalla completa exclusiva** | Requiere inyección en el proceso |
| **Set Manager / Inventory vendible / Fundición con "listo para construir"** | Necesitan las cantidades de piezas; ver primera fila |

---

## 9. Fuentes

Autorización y normas
- Correo de Warframe Support al usuario, septiembre de 2026 (transmitido por
  el coordinador; pendiente de pegar el literal).
- "Third-Party Software and You" ([DE]Dudley, 2022):
  https://forums.warframe.com/topic/1320042-third-party-software-and-you/
  (espejo legible: https://devtrackers.gg/warframe/p/dc37ee98-third-party-software-and-you)
- Artículo de soporte: https://support.warframe.com/hc/en-us/articles/360030014351-Third-Party-Software-and-You
- EULA: https://www.warframe.com/en/EULA · Condiciones: https://www.warframe.com/en/terms
- Hilo citado por la FAQ de AlecaFrame (no verificable, 403):
  https://forums.warframe.com/topic/1383123-third-party-software-usage/#comment-12964630
- Overwolf Platform Terms of Use (23-06-2024), §7.2:
  https://legal.overwolf.com/docs/overwolf/platform/platform-terms-of-use/
- Overwolf, "won't get you banned": https://support.overwolf.com/en/support/solutions/articles/9000182312-overwolf-won-t-get-you-banned
- Política de privacidad de Overwolf (uso sin cuenta, `MUID`):
  https://legal.overwolf.com/docs/overwolf/platform/platform-privacy-policy/

AlecaFrame
- Web: https://alecaframe.com/ · Wiki: https://docs.alecaframe.com/welcome
- Código de la wiki (MIT): https://github.com/alecamaracm/AlecaFrame-Docs
  (`docs/api.md`, `docs/faq.md`, `docs/features/*.md`, `docs/overlays/*.md`,
  `docs/language-compatibility.md`, `docs/get-started/connecting.md`)
- **OpenAPI real**: https://stats.alecaframe.com/api/swagger/v1/swagger.json
  (interfaz: https://stats.alecaframe.com/api/swagger/index.html)
- API (wiki): https://docs.alecaframe.com/api · Stats: https://docs.alecaframe.com/features/stats
- FAQ: https://docs.alecaframe.com/faq (versión antigua: https://cdn.alecaframe.com/)
- Ficha en Overwolf (2.6.93): https://www.overwolf.com/app/alejandro_cabrerizo-alecaframe
- Patreon: https://www.patreon.com/AlecaFrame/membership

Mecanismo de Overwolf y herramientas relacionadas
- Eventos de Warframe en Overwolf: https://dev.overwolf.com/ow-native/live-game-data-gep/supported-games/warframe/
- FAQ de WFHelper (describe la lectura de memoria): https://wfhelper.com/faq ·
  repo: https://github.com/MikhailMostWanted/WFHelper
- Sentinel (`Inventory.cpp` descifra `lastData.dat`; `LogDevotee.cpp` parsea
  `EE.log`): https://github.com/calamity-inc/Sentinel-for-Warframe
- `alecaframe-inventory-parser`: https://github.com/Sainan/alecaframe-inventory-parser
- WFInfo: https://github.com/WFCD/WFinfo · Wiki `EE.log`: https://wiki.warframe.com/w/EE.log

Perfil de DE
- browse.wf: https://browse.wf/profile · FrameHub:
  https://gist.github.com/DaPigGuy/18349a0fd5ad08502305a98f8b115c26
- `@wfcd/profile-parser` (tipos y fixtures `test/data/*.json`):
  https://github.com/WFCD/profile-parser
- OpenAPI de warframestat.us: https://docs.warframestat.us/openapi.yaml
- Hilo sobre bloqueo de IP por la API (403 a peticiones automáticas):
  https://forums.warframe.com/topic/1473810-can-api-warframe-with-403-error-forbidden-cause-my-ip-to-be-blocked-cannot-login-into-game/

Comunidad
- https://steamcommunity.com/app/230410/discussions/0/4700160821461246847
- https://steamcommunity.com/app/230410/discussions/0/662719183492084718/
- https://forums.warframe.com/topic/1367872-alecaframe/ (403 a peticiones automáticas)
