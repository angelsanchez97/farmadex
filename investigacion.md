# Overlay de consulta para Warframe: informe de viabilidad

Fecha: 19 de septiembre de 2026. Plataforma objetivo: Windows 11 (PC del usuario: RTX 5080), pero el ejecutable debe funcionar en cualquier PC con Windows.

Requisitos confirmados por el usuario:

- Cuatro funciones: buscador de drops ("¿dónde consigo X?"), seguimiento de objetivos de farmeo, estado del mundo (fisuras, ciclos, invasiones...) y precios de warframe.market.
- Invocación con hotkey global que abre/cierra el overlay encima del juego. Warframe ya corre en ventana sin bordes.
- Todo en español: nombres de objetos y búsqueda en español.
- OCR de pantalla: objeto bajo el cursor en inventario/tienda, pantalla de recompensas de reliquias, etc.
- Distribución como instalador o .exe portable para Windows, sin pedir al usuario que instale Python ni dependencias. Cuidado con el motor de OCR empaquetado, el tamaño y la actualización de datos y de la app.

Todo lo que sigue se ha comprobado contra las fuentes enlazadas; donde una fuente no se pudo abrir (varias páginas de support.warframe.com y forums.warframe.com devuelven 403 a peticiones automáticas) se indica y se cita a través de terceros.

---

## 1. Legalidad y condiciones de uso

### Lo que dice Digital Extremes

**EULA** ([warframe.com/en/EULA](https://www.warframe.com/en/EULA), citado literalmente en un [hilo de Steam](https://steamcommunity.com/app/230410/discussions/0/2595630410185598084/)):

- Sección 2.f: el usuario no puede "use cheats, automation software (bots), hacks, mods or any other unauthorized third-party software, tools or content designed to modify the Software, the Service or the Game experience".
- Los Términos de Uso ([warframe.com/en/terms](https://www.warframe.com/en/terms)) prohíben además programas de terceros no autorizados "that intercept, emulate, or redirect any communication between the Services and Digital Extremes or that collect information about the Game".
- Sección 4 (consentimiento de monitorización): "the software may monitor your computer's Random Access Memory (RAM) for unauthorized third-party programs running concurrently with the Software". Es decir, hay anticheat que inspecciona procesos concurrentes.

**Artículo de soporte "Third-Party Software and You"** ([support.warframe.com](https://support.warframe.com/hc/en-us/articles/360030014351-Third-Party-Software-and-You); la página devuelve 403 a peticiones automatizadas, citas tomadas de los resúmenes indexados): "If you use external software in conjunction with Warframe, then you do so at your own risk". Añade que software tolerado hoy puede acabar en la lista de baneo si se descubre que sirve de vector de exploit, y que los baneos por alterar ficheros del juego, hacer trampas o farmear AFK son "hefty and final".

### Lo que la práctica demuestra permitido

| Técnica | Herramienta que la usa | Evidencia |
|---|---|---|
| Ventana superpuesta independiente (no inyectada) + captura de pantalla + OCR | WFInfo | Un desarrollador de DE ([DE]Aidan, ya retirado) declaró en los foros oficiales que "using WFInfo would not result in a ban" ([resumen](https://warframe-app.digitalshopuy.com/tools/wfinfo); hilo original en [forums.warframe.com](https://forums.warframe.com/topic/1056041-wfinfo-mod-relic-reward-tool/), inaccesible a peticiones automáticas). WFInfo es Apache-2.0 y lleva años publicado en [GitHub/WFCD](https://github.com/WFCD/WFinfo). |
| Lectura del fichero `EE.log` | WFInfo (modo Auto), parsers de la comunidad | La [wiki oficial](https://wiki.warframe.com/w/EE.log) documenta el fichero y cita parsers de terceros como uso legítimo. Es un fichero de texto en `%LocalAppData%\Warframe\EE.log`, no se toca el proceso. |
| Overwolf (plataforma con acuerdo con editores) | AlecaFrame, Overframe app, Warframe Helper | AlecaFrame afirma que el acceso al inventario "is handled by Overwolf, which is explicitly said to be fine in DE's Third Party Policy" ([docs.alecaframe.com/faq](https://docs.alecaframe.com/faq)). Overwolf lista Warframe como juego soportado con eventos oficiales ([dev.overwolf.com](https://dev.overwolf.com/ow-native/live-game-data-gep/supported-games/warframe/)). |

### Lo que hay que evitar

- **Lectura de memoria del proceso o inyección de DLL/hook de DirectX**: cae de lleno en "modify the Software" y en la monitorización de RAM. Ninguna herramienta comunitaria respetada lo hace fuera de Overwolf.
- **Usar las credenciales de sesión del jugador (`accountId` + `nonce`) contra `api.warframe.com` (`inventory.php`)**: es lo que hace el ecosistema de servidores privados (OpenWF) y algunos scripts; encaja con "intercept, emulate, or redirect any communication" y no hay declaración de DE que lo tolere. Descartado.
- **Automatización de entradas (macros, clics)**: zona gris explícita en el artículo de soporte. El overlay no debe enviar ninguna entrada al juego.

### Conclusión legal

Un overlay que sea una ventana normal de Windows encima del juego, que sólo lea pantalla (captura + OCR) y el fichero `EE.log`, y que consuma APIs públicas de terceros, está en la misma categoría que WFInfo: tolerado en la práctica y con declaración informal de DE. No hay autorización escrita y DE se reserva el derecho a cambiar de criterio ("at your own risk"), lo que conviene decir en el README del programa.

---

## 2. Fuentes de datos

### 2.1 WFCD `warframe-items` (`@wfcd/items`)

- Repositorio: [github.com/WFCD/warframe-items](https://github.com/WFCD/warframe-items). Licencia **MIT**. Se instala con `npm install @wfcd/items`, pero los JSON compilados viven en `/data/json` del repo y se pueden descargar directamente sin Node.
- **Contenido**: 26 categorías (Warframes, Primary, Secondary, Melee, Mods, Relics, Arcanes, Resources, Node, Quests, Pets, Skins...). Cada objeto trae `uniqueName`, `name`, `category`, `type`, `tradable`, `vaulted`, `drops` (location, chance, rarity), `components` con sus propios `drops`, `wikiaUrl`, `patchlogs`, `marketInfo`.
- **Español**: opción `i18n` con idiomas `de, es, fr, it, ja, ko, pl, pt, ru, th, tr, uk, zh`. La traducción se sirve en `i18n.json` (52,5 MB) o adjunta a cada objeto con `i18nOnObject`. Comprobado en vivo: `api.warframestat.us/items/Lith A1/?language=es` devuelve `"name": "Reliquia Lith A1"` con descripción en español y `"vaulted": true`.
- **Tamaños reales** (`data/json`, septiembre 2026): Primary 11,0 MB, Melee 9,5 MB, Misc 8,7 MB, Relics 8,6 MB, Secondary 8,3 MB, Skins 7,4 MB, Mods 5,7 MB, Warframes 3,0 MB, Enemy 2,8 MB, Resources 0,56 MB, Arcanes 0,30 MB, Node 0,16 MB. Los `.min.json` pesan menos y se puede recortar `patchlogs` al importar.
- **Actualización**: bot automático "fix(items): new items" varias veces al día (5 commits entre el 18 y el 19 de septiembre de 2026). Fuente primaria: Public Export de DE más `warframe-drop-data`.
- **Offline**: sí, son ficheros estáticos. Imágenes en CDN `https://cdn.warframestat.us/img/{imageName}`.

### 2.2 WFCD `warframe-drop-data` (`drops.warframestat.us`)

- Repositorio: [github.com/WFCD/warframe-drop-data](https://github.com/WFCD/warframe-drop-data). Licencia **MIT**. Parsea la tabla oficial de DE.
- Ficheros en `https://drops.warframestat.us/data/`: `all.json`, `missionRewards.json`, `relics.json`, `modLocations.json`, `enemyModTables.json`, `blueprintLocations.json`, `enemyBlueprintTables.json`, `sortieRewards.json`, `transientRewards.json`, `cetusBountyRewards.json`, `solarisBountyRewards.json`, `zarimanRewards.json`, `syndicates.json`, `keyRewards.json`.
- `info.json` da `hash`, `timestamp` y `modified` (comprobado: hash `a0ece5e9...`, `modified` = 1782419611000, coherente con el "Last Update: 25 June, 2026" de la tabla de DE). Sirve para saber si hay que redescargar.
- Cada entrada lleva `_id`, `chance`, `rarity` y nombres en **inglés** (la tabla de DE sólo existe en inglés).
- **No marca reliquias vaulted**: eso viene de `warframe-items` (`vaulted` en cada reliquia y en cada objeto).

### 2.3 API `api.warframestat.us` (WFCD `warframe-status`)

- Docs: [docs.warframestat.us](https://docs.warframestat.us/). Repo: [github.com/WFCD/warframe-status](https://github.com/WFCD/warframe-status), licencia **Apache-2.0**, **autoalojable** con Docker (`ghcr.io/wfcd/warframe-status:latest`), con WebSocket para cambios de worldstate.
- Endpoints: `/{platform}` (worldstate completo) y `/{platform}/{hijo}`: `fissures`, `invasions`, `cetusCycle`, `vallisCycle`, `cambionCycle`, `sortie`, `archonHunt`, `nightwave`, `voidTrader`, `alerts`, `events`, `arbitration`, `steelPath`... Estáticos: `/items`, `/items/{nombre}`, `/items/search/{texto}`, `/drops/search/{texto}`, `/weapons`, `/warframes`, `/mods`, `/arcanes`, `/profile`.
- **Español, comprobado en vivo**:
  - `/items/{nombre}?language=es`: devuelve nombre y descripción en español, pero la clave de búsqueda sigue siendo el nombre en inglés.
  - `/items/search/Sistemas de Ash Prime?language=es` devuelve `[]`: **la búsqueda por nombre español no funciona en la API**. Hay que buscar en local sobre `i18n.json`.
  - `/pc/fissures?language=es`: `node`, `missionType` y `tier` salen en **inglés** (`"node":"Alator (Mars)","missionType":"Interception"`). Los nombres de nodo y tipo de misión hay que traducirlos con `Node.json` de warframe-items o con `ExportRegions` del Public Export en español.
  - `/drops/search/Ash Prime Systems` devuelve ~20 entradas del tipo `{"place":"Neo N5 Relic (Flawless)","item":"Ash Prime Systems Blueprint","rarity":"Uncommon","chance":17}`. Da objeto -> reliquia con refinamiento, **no** reliquia -> misión.
- Límites: la documentación pública no declara rate limit. Es un servicio comunitario sin SLA; para el overlay conviene cachear en disco y consultar el worldstate cada 60 s como máximo.

### 2.4 Tablas de drops oficiales de DE

- `warframe.com/droptables` redirige (302) a un HTML estático en DigitalOcean Spaces: `https://warframe-web-assets.nyc3.cdn.digitaloceanspaces.com/uploads/cms/hnfvc0o3jnfvc873njb03enrf56.html`.
- Secciones: Missions (por planeta y rotación A/B/C), Relics (por era y refinamiento), Keys, Dynamic Location Rewards, Sorties, Bounty Rewards, Mod Drops by Source/Item, Blueprint/Part Drops, Resource Drops, Sigil Drops, Additional Item Drops.
- Cabecera comprobada: "Last Update: 25 June, 2026"; advierte "This data comes with no guarantees". Sin licencia explícita; es la fuente que `warframe-drop-data` reempaqueta bajo MIT, así que se consume a través de este último.
- No indica vaulted ni tiene versión en español.

### 2.5 Public Export de DE

- Documentado en la [wiki oficial](https://wiki.warframe.com/w/Public_Export) y en [Public Endpoints](https://wiki.warframe.com/w/WARFRAME_Wiki:Public_Endpoints). Índice por idioma en `https://origin.warframe.com/PublicExport/index_es.txt.lzma` (existe `es`), después manifiestos en `http://content.warframe.com/PublicExport/Manifest/{hash}` en JSON comprimido LZMA.
- Contiene **definiciones** (ExportWeapons, ExportWarframes, ExportResources, ExportRelics, ExportRegions, ExportUpgrades...), **no** tablas de drops. En ExportRelics no hay `name`; se construye a partir de `category` y `era`.
- La wiki recuerda que "Third-party usage of these assets must comply to WARFRAME's Content Policy" y que el JSON tiene fallos conocidos (hay un [hilo en foros](https://forums.warframe.com/topic/1385291-please-make-the-public-export-json-files-less-painful-to-deal-with/) pidiendo arreglarlo).
- Para el overlay no hace falta consumirlo directamente: `warframe-items` ya lo digiere. Su único uso directo sería `ExportRegions` en español para traducir nodos si `Node.json` no bastase.
- Otros endpoints de DE ahí listados: `content.warframe.com/dynamic/worldState.php` (worldstate crudo, es lo que parsea warframestat), `www-static.warframe.com/repos/weeklyRivensPC.json` (precios semanales de rivens).

### 2.6 Wiki oficial `wiki.warframe.com`

- Desde el 31 de enero de 2025 es la wiki oficial, alojada por Weird Gloop y financiada por DE ([anuncio](https://wiki.warframe.com/w/WARFRAME_Wiki:Official_Wiki)). Fandom ya no es oficial.
- Comprobado en vivo: `https://wiki.warframe.com/api.php?action=query&meta=siteinfo` responde; MediaWiki 1.45.3 con Scribunto (Lua) y TextExtracts; **sin Cargo ni Semantic MediaWiki**. Los datos estructurados están en módulos Lua (`Module:DropTables/data`, `Module:Void/data` con estado vaulted de reliquias), legibles vía `action=query&prop=revisions` y parseables como Lua.
- Licencia de contenido **CC BY-NC-SA 3.0**: prohíbe uso comercial. Si el programa algún día se monetizara, la wiki quedaría fuera; los datos de WFCD (MIT/Apache) no tienen ese problema.
- Uso previsto: enlace "abrir en la wiki" desde cada objeto (`wikiaUrl` de warframe-items) y, opcionalmente, extractos de texto vía TextExtracts. No como fuente primaria.

### 2.7 warframe.market API v2

- Docs: [docs.warframe.market](https://docs.warframe.market/). Base `https://api.warframe.market/v2/`. **Todavía en pre-release** ("contracts are still below 1.0. Expect changes, including breaking changes"); v1 está "deprecated and unsupported".
- Cabecera `Language` con `ko, ru, de, fr, pt, zh-hans, zh-hant, es, it, pl, uk, tr, ja, en` (español incluido). Cabecera `Platform`: `pc, ps4, xbox, switch, mobile`.
- Endpoints públicos sin autenticación: `/items`, `/item/{slug}`, `/item/{slug}/set`, `/orders/item/{slug}/top`, estadísticas. Respuesta con envoltorio `{apiVersion, data, error}`.
- [Reglas](https://docs.warframe.market/docs/rules/overview/): **3 peticiones/segundo** (búsquedas de contratos 10-20/min), `User-Agent` descriptivo obligatorio del tipo `ExampleMarketTool/1.2.0 (+https://example.com/contact)`, prohibido hacerse pasar por navegador, exigen cachear y evitar polling; el servicio debe aportar algo más que replicar la web. WebSocket disponible para actualizaciones incrementales.

### 2.8 Cómo se encadena "parte X -> reliquia Y -> misión Z" y el estado vaulted

1. El usuario escribe en español ("sistemas de ash prime"). Se busca en local en un índice construido a partir de `i18n.json` (nombres `es` -> `uniqueName`), con búsqueda difusa y sin acentos.
2. En `warframe-items`, el objeto padre (Ash Prime) tiene `components[]`; el componente "Systems" trae `drops[]` con `location` del tipo `Axi A7 Relic (Radiant)`, `chance` y `rarity`. Se agrupan por reliquia.
3. Cada reliquia (en `Relics.json`) trae `vaulted: true|false` y sus `rewards`. Se marca en la interfaz y se ordena primero lo no vaulted.
4. Para "¿dónde cae la reliquia Axi A7?" se consulta `missionRewards.json` de `warframe-drop-data` buscando entradas cuyo `item` sea "Axi A7 Relic": devuelve planeta, nodo, tipo de misión, rotación y probabilidad. También `cetusBountyRewards.json`, `solarisBountyRewards.json`, `zarimanRewards.json`, `keyRewards.json` y `transientRewards.json` (Arbitrations, Void Storms...).
5. Para recursos, mods, arcanos y planos no prime la cadena es directa: `drops[]` del objeto o `modLocations.json` / `enemyModTables.json` / `blueprintLocations.json` / `enemyBlueprintTables.json` / `syndicates.json`.
6. Se cruza con el worldstate (`/pc/fissures`) para señalar "ahora mismo hay una fisura Axi en X". Los nombres de nodo del worldstate están en inglés; se traducen con `Node.json` o `ExportRegions` (es).

Todo lo anterior funciona offline con los JSON descargados; sólo worldstate y precios necesitan red. El actualizador compara `info.json` de drop-data y la fecha del último commit de `warframe-items` (API de GitHub) para decidir si redescargar.

---

## 3. Técnica del overlay en Windows

### 3.1 Cómo se hace y cuándo funciona

- Un overlay no inyectado es una ventana de nivel superior con `WS_EX_TOPMOST` y `WS_EX_LAYERED` (transparencia por píxel, compuesta por el DWM). Opcionalmente `WS_EX_TRANSPARENT` / `WS_EX_NOACTIVATE` para que los clics pasen al juego.
- Funciona encima del juego siempre que el juego esté **compuesto por el DWM**: ventana, ventana sin bordes, y también "pantalla completa" en DX12, porque **DX12 no tiene pantalla completa exclusiva**: cualquier opción "fullscreen" en DX12 es de hecho una ventana sin bordes con modelo flip ([Blur Busters](https://forums.blurbusters.com/viewtopic.php?t=8282)). En DX11, la pantalla completa exclusiva real sólo se da si el usuario desactiva las "Optimizaciones de pantalla completa" de Windows; con ellas activas (por defecto) Windows ejecuta el juego "behind the scenes ... in borderless windowed mode" y "supports overlays" ([DirectX Developer Blog](https://devblogs.microsoft.com/directx/demystifying-full-screen-optimizations/)).
- Warframe ofrece Fullscreen, Borderless Fullscreen y Windowed, y en el lanzador se elige DX11 o DX12 ([foros](https://forums.warframe.com/topic/1449385-game-always-starting-in-windowed-mode-regardless-of-last-saved-configuration-and-borderless-fullscreen-not-working-properly-on-startup/)). WFInfo exige "Borderless Fullscreen" precisamente por esto ([README](https://github.com/WFCD/WFinfo)). El usuario ya juega en ventana sin bordes, así que el caso está cubierto; el README del programa debe decir "ventana sin bordes o DX12".
- Hotkey global: `RegisterHotKey` de Win32 (o los equivalentes de cada stack). Como el overlay se **abre y cierra** con la hotkey, no hace falta el modo "click-through" mientras está abierto: cuando está visible captura ratón y teclado para escribir la búsqueda; cuando está oculto no existe. Eso elimina el problema más delicado de los overlays (hit-testing por regiones).
- Captura de pantalla para OCR: `BitBlt`/`PrintWindow` sobre el HWND del juego o Windows.Graphics.Capture. Con ventana sin bordes ambas funcionan. Hay que ocultar el propio overlay un instante o capturar sólo la región del juego.

### 3.2 Comparativa de stacks

| Criterio | Python + PySide6 | Tauri v2 (Rust + WebView2) | Electron | Overwolf |
|---|---|---|---|---|
| Overlay topmost/transparente | Sí: `Qt.WindowStaysOnTopHint`, `Qt.FramelessWindowHint`, `WA_TranslucentBackground`, `Qt.WindowTransparentForInput` para click-through | Sí: `transparent`, `alwaysOnTop`, `decorations:false`, `setIgnoreCursorEvents`; sin hit-test por regiones ([issue #13070](https://github.com/tauri-apps/tauri/issues/13070)), irrelevante con hotkey de abrir/cerrar | Sí: `transparent`, `alwaysOnTop`, `setIgnoreMouseEvents(true,{forward:true})`; hay un [issue](https://github.com/electron/electron/issues/8530) con juegos OpenGL/Vulkan, no con DX | Overlay nativo gestionado por Overwolf, el más fiable |
| Hotkey global | `RegisterHotKey` vía `ctypes` o `pynput` | [plugin global-shortcut](https://v2.tauri.app/plugin/global-shortcut/) | `globalShortcut` | API de Overwolf |
| OCR empaquetable | El mejor ecosistema: `rapidocr-onnxruntime` (modelo latino PP-OCRv5 de 7,5 MB, cubre español con tildes; CPU ~0,2 s por imagen), `winocr` (Windows.Media.Ocr, tamaño cero, depende del paquete de idioma OCR del sistema), Tesseract (`spa.traineddata` 17 MB, o 2,8 MB la versión fast) | Windows.Media.Ocr vía crate `windows` (tamaño cero, misma dependencia del paquete de idioma), o `ort` + modelos RapidOCR; más trabajo en Rust | `tesseract.js` (WASM, lento pero suficiente para capturas puntuales) o proceso nativo aparte | El que se quiera, en JS |
| Tamaño del ejecutable | 100-250 MB con PyInstaller (evitar arrastrar QtWebEngine) | ~5-15 MB; WebView2 viene con Windows 11 y el instalador lo resuelve en Windows 10 (+1,8 MB bootstrapper) | 150-200 MB | Requiere el cliente Overwolf instalado |
| Auto-actualización | A mano (comprobar release en GitHub y descargar) | [plugin updater](https://v2.tauri.app/plugin/updater/) con firma y JSON estático en GitHub Releases | `electron-updater` | Tienda de Overwolf |
| Datos WFCD | JSON estáticos, descarga directa; sin npm | Igual, o `@wfcd/items` en el frontend | `@wfcd/items` nativo | `@wfcd/items` nativo |
| Distribución | .exe portable o instalador Inno Setup | MSI/NSIS generados por Tauri | NSIS | Sólo vía tienda Overwolf tras revisión QA ([docs](https://dev.overwolf.com/ow-native/getting-started/release-your-app/)); exige ventana visible; el cliente Overwolf lleva publicidad |
| Ventaja única | Rapidez de desarrollo y depuración; el usuario ya tiene proyectos Python | Ejecutable pequeño y actualizador firmado de serie | Un solo lenguaje (JS) | Único canal con acceso legítimo al inventario (`match_info.inventory`) |
| Inconveniente principal | Tamaño y arranque más lento (2-4 s en frío) | Dos lenguajes (Rust + JS); OCR más laborioso | El más pesado sin aportar nada frente a Tauri | Dependencia de un cliente ajeno, revisión externa, no es "un .exe" |

### 3.3 Recomendación de stack

**Python 3.12 + PySide6, empaquetado con PyInstaller en modo carpeta e instalador Inno Setup (y zip portable).** Motivos:

1. Es el stack donde el OCR en español es un problema resuelto: `rapidocr-onnxruntime` con el modelo latino funciona en CPU en cualquier PC (la RTX 5080 del usuario no puede darse por supuesta en otros equipos) y no depende de paquetes de idioma del sistema. Se puede ofrecer `winocr` como motor alternativo de tamaño cero.
2. Qt hace el overlay (topmost, sin marco, translúcido, DPI-aware) sin trucos de Win32, y el resto de la lógica (índice de búsqueda, caché, worldstate, market) es Python normal.
3. El usuario trabaja habitualmente con proyectos Python (clipper, filtro de TikTok), así que el mantenimiento le queda en terreno conocido.
4. El coste es el tamaño (estimación 150-200 MB instalados con onnxruntime CPU y PySide6 recortado) y un actualizador propio sencillo (comprobar la última release en GitHub y descargar). Es aceptable para una herramienta de escritorio; si el tamaño se volviera un problema, Tauri v2 es la alternativa y el diseño de módulos propuesto abajo permite migrar la interfaz sin tocar la capa de datos.

Overwolf queda descartado como base porque contradice el requisito de "un ejecutable para Windows" y añade un cliente con publicidad y una revisión externa. Electron no aporta nada frente a Tauri y pesa como Python sin la ventaja del OCR.

---

## 4. Herramientas existentes y hueco

| Herramienta | Qué hace | Limitaciones relevantes |
|---|---|---|
| [WFInfo](https://github.com/WFCD/WFinfo) (C#/WPF, Apache-2.0) | Captura la pantalla de recompensas de reliquia, OCR con Tesseract, muestra platino (warframe.market), ducados, volumen, vaulted y cuántos tienes; modo Auto vigilando `EE.log`; escaneo de inventario "Snap-it"; panel de estadísticas de reliquias | Exige **juego en inglés**, ventana sin bordes y "Item Labels" activas. No es un buscador de "dónde se consigue X"; no hace seguimiento de farmeo ni worldstate |
| [AlecaFrame](https://alecaframe.com/) (Overwolf, código cerrado, funciones de pago en Patreon) | Inventario completo vía Overwolf, overlay de recompensas de reliquia, overlay de rivens, ayudante de maestría, foundry, integración con warframe.market | Requiere Overwolf; **juego en inglés** para los overlays; integración "far from perfect" según sus propios docs; la comunidad arrastra dudas recurrentes sobre baneos aunque no hay evidencia |
| [Overframe](https://overframe.gg) y su app de Overwolf (lanzada en julio de 2025 por M.O.B.A. Network) | Guías de builds y mods; la app lleva las builds al overlay | Orientada a builds, no a drops ni farmeo |
| [Warframe Hub](https://hub.warframestat.us) (WFCD, web) | Worldstate en tiempo real: fisuras, ciclos, Baro, Nightwave, sorties, invasiones | Web, sin overlay, sin buscador de drops, en inglés |
| [drops.warframestat.us](https://drops.warframestat.us/) (WFCD, web) | Búsqueda en las tablas de drops oficiales | Web, inglés, sin relación reliquia -> misión -> fisura activa, sin objetivos |
| Warframe Helper (Overwolf), [Warframe-RelicRunner](https://github.com/Aravos/Warframe-RelicRunner), [warframeocr](https://github.com/Zendelll/warframeocr) (Python), VoidStonks (web) | Variantes de "valor de la recompensa de reliquia" con OCR + market | Todas en inglés, todas centradas en la pantalla de recompensas |

**Hueco que justifica la herramienta propia**: no existe ningún overlay que responda en español a "¿dónde consigo esto?" para cualquier objeto (recurso, parte prime, mod, arcano, plano), que encadene parte -> reliquia (con vaulted) -> misión -> fisura activa ahora, que mantenga una lista de objetivos de farmeo y que haga OCR de nombres **en español**. Todas las herramientas de OCR existentes obligan a jugar en inglés. El precio de warframe.market y el worldstate son funciones ya cubiertas por otros, pero integrarlas en el mismo panel es lo que hace útil el conjunto.

---

## 5. Capacidades opcionales

### 5.1 OCR de pantalla

**Viable y de bajo riesgo** (misma técnica que WFInfo).

- Captura: región de la ventana del juego (por HWND). Preprocesado: escala x2, umbral, el texto de Warframe es una fuente sans limpia sobre fondos variables; RapidOCR aguanta bien ese caso. Post-proceso: casar la cadena leída contra el índice de nombres en español con distancia de edición (como hace WFInfo con los nombres en inglés), lo que corrige la mayoría de errores de OCR.
- Pantalla de recompensas de reliquia: 2-4 nombres en posiciones fijas relativas a la resolución; disparador por hotkey o por la línea correspondiente en `EE.log` (modo Auto de WFInfo). Muestra precio, ducados, vaulted y "lo necesitas para el objetivo X".
- Objeto bajo el cursor en inventario/tienda/arsenal: se captura una región alrededor del cursor y se reconoce el nombre en la etiqueta (requiere "Item Labels" activas, igual que WFInfo). Es la parte más frágil: depende de la resolución, del escalado de la interfaz y de los cambios de UI de DE; conviene tratarla como función "beta" con calibración por resolución.
- Español: `rapidocr` latino incluye tildes y ñ; el índice de nombres viene de `i18n.json` (`es`). Habrá que comprobar en pruebas reales qué variante de español usa el juego (el Public Export ofrece `es` como "Spanish (Latin America)"; los nombres de i18n de warframe-items salen de esa misma fuente, así que coincidirán con lo que pinta el juego).
- Riesgo: técnico (falsos positivos), no legal.

### 5.2 Leer el inventario del jugador

| Vía | Viable | Riesgo |
|---|---|---|
| `EE.log` | Parcial. Registra misiones completadas, recompensas obtenidas y eventos de juego; **no** vuelca el inventario. Se reinicia en cada arranque y contiene IP y correo del usuario ([wiki](https://wiki.warframe.com/w/EE.log)), así que nunca debe salir del PC ni subirse a ningún sitio | Bajo (lectura de fichero), aceptado por la comunidad. Útil para sumar recompensas a los objetivos de farmeo en tiempo real y para disparar el OCR de reliquias |
| Overwolf `match_info.inventory` | Sí, es la única vía sancionada para inventario completo | Bajo, pero obliga a construir sobre Overwolf; incompatible con el requisito de ejecutable independiente |
| `api.warframe.com/.../inventory.php` con `accountId` + `nonce` capturados de la sesión | Técnicamente sí (lo hace el ecosistema OpenWF y algunos scripts) | **Alto**: encaja con la prohibición de interceptar comunicaciones; sin ninguna declaración de tolerancia de DE. Descartado |
| API pública de AlecaFrame ([docs](https://docs.alecaframe.com/api)) | Sí, si el usuario ya usa AlecaFrame: tokens públicos generados por él con la lista de reliquias que posee y estadísticas; 1 petición/s | Bajo (es una API de terceros opt-in), pero añade dependencia de otra app. Posible integración opcional |
| OCR del propio inventario ("Snap-it" de WFInfo) | Sí, para recuentos puntuales de piezas prime | Bajo; laborioso para el usuario |

**Recomendación**: objetivos de farmeo con recuento manual ("tengo 2 de 3") más suma automática de lo que aparezca en `EE.log` y en el OCR de recompensas. Inventario completo sólo como integración opcional con AlecaFrame si el usuario lo tiene.

---

## Recomendación de arquitectura

### Stack

- Python 3.12, PySide6 (Qt 6) para overlay y ventana de ajustes, `rapidocr-onnxruntime` (modelo latino) como OCR por defecto con `winocr` opcional, `mss` o `PrintWindow` para captura, `httpx` con caché en disco, SQLite para índice de búsqueda (FTS5 con tokenizador sin acentos) y estado del usuario, `RegisterHotKey` vía `ctypes`.
- Empaquetado: PyInstaller (one-dir) + Inno Setup; zip portable adicional. Actualizador propio: comprobar la última release en GitHub al arrancar, avisar y descargar.
- Datos: `warframe-items` (`.min.json` de las categorías necesarias + `i18n.json` filtrado a `es`, recortando `patchlogs`), `warframe-drop-data` (`all.json` o los ficheros por tipo), `api.warframestat.us` para worldstate (`/pc/...`), `api.warframe.market/v2` para precios con `Language: es`, `User-Agent` propio y caché de 5-10 min por objeto. Todo bajo MIT/Apache; la wiki sólo como enlace externo.
- El propio programa no debe tocar el proceso del juego, ni enviar entradas, ni usar credenciales de la cuenta.

### Estructura de módulos

```
warframe_overlay/
  app.py                 # arranque, bandeja del sistema, hotkey global, ciclo de vida
  ui/
    overlay.py           # ventana topmost sin marco translúcida; buscador, pestañas
    panel_drops.py       # resultados: objeto -> fuentes (reliquia/misión/enemigo/sindicato)
    panel_objetivos.py   # lista de farmeo con progreso
    panel_mundo.py       # fisuras, ciclos, invasiones, Baro, sortie/archon
    panel_market.py      # precios y órdenes top
    ajustes.py           # hotkey, idioma, motor OCR, resolución, actualizaciones
  datos/
    actualizador.py      # descarga y versiona warframe-items / drop-data (hash, fecha)
    indice.py            # SQLite FTS5: nombres es/en -> uniqueName; búsqueda difusa
    items.py             # acceso a objetos, componentes, drops, vaulted
    drops.py             # missionRewards, bounties, mods, enemigos, sindicatos
    relaciones.py        # parte -> reliquias -> misiones; nodos en español
  online/
    worldstate.py        # api.warframestat.us, refresco cada 60 s, WebSocket opcional
    market.py            # warframe.market v2, límite 3 req/s, caché
  captura/
    pantalla.py          # captura por HWND/región, oculta el overlay durante la captura
    ocr.py               # RapidOCR / winocr; preprocesado; casado difuso con el índice
    reliquias.py         # detección de pantalla de recompensas, regiones por resolución
    cursor.py            # objeto bajo el cursor (beta)
  registro/
    eelog.py             # tail de EE.log: recompensas, fin de misión; nunca sale del PC
  estado/
    objetivos.py         # objetivos de farmeo, progreso, persistencia SQLite
```

### Flujo principal

1. Arranque: comprueba versión de datos (fecha de commit de warframe-items, `info.json` de drop-data) y de la app; descarga en segundo plano con barra de progreso.
2. Hotkey (por defecto configurable, p. ej. `Ctrl+Shift+W`): muestra/oculta el overlay. Al mostrarse, el foco va al buscador.
3. Búsqueda en español -> panel de drops con reliquias (vaulted marcado), misiones con rotación y probabilidad, y las fisuras activas que coinciden ahora mismo.
4. Botón "añadir a objetivos"; el panel de objetivos se actualiza con lo que llegue por `EE.log` y por el OCR de recompensas.
5. Segunda hotkey (o modo Auto por `EE.log`) para el OCR de recompensas de reliquia; tercera hotkey para "¿qué es esto?" bajo el cursor.

---

## Preguntas abiertas (dependen de preferencias del usuario)

1. **Idioma del juego**: ¿Warframe está configurado en español? Determina el idioma del OCR y del índice. Si juega en inglés con interfaz en español del overlay, el índice debe ser bilingüe (ya es posible: `name` en inglés + `i18n.es`).
2. **Hotkeys**: cuáles para abrir/cerrar, OCR de recompensas y "objeto bajo el cursor"; y si el overlay debe cerrarse solo al hacer clic fuera o al pulsar Escape.
3. **Posición y tamaño del overlay**: panel lateral fijo, ventana flotante centrada o recordar la última posición; opacidad del fondo.
4. **Modo Auto por `EE.log`**: ¿quiere que el OCR de recompensas se dispare solo al detectar la pantalla, como WFInfo, o sólo por hotkey?
5. **Plataforma para precios y worldstate**: PC se da por hecho; ¿hace falta selector de plataforma?
6. **Alcance de "estado del mundo"**: sólo fisuras/ciclos/invasiones, o también Baro, Nightwave, sortie, cazas de arcontes, arbitraciones y alertas de Steel Path.
7. **Objetivos de farmeo**: recuento manual, o además intentar integrar AlecaFrame (si lo usa) para leer reliquias poseídas.
8. **Filtros por defecto**: ocultar reliquias vaulted, ordenar por probabilidad o por "disponible ahora".
9. **Actualizaciones**: silenciosas al arrancar (datos siempre; app con aviso) o preguntar siempre. ¿Publicar en GitHub Releases para que otros lo descarguen?
10. **Tamaño frente a stack**: si 150-200 MB instalados le parecen excesivos para distribuirlo, la alternativa es Tauri v2 (~10 MB) a costa de más trabajo en Rust para el OCR.
11. **Nombre del programa** y `User-Agent` de contacto que exige warframe.market (URL o correo público).
12. **Aviso legal en el README**: texto del tipo "herramienta no afiliada a Digital Extremes; sólo lee pantalla y ficheros de registro; uso bajo tu responsabilidad según la política de terceros de DE".
