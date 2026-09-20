# Plan de implementación: overlay de consulta para Warframe

Fecha: 19 de septiembre de 2026. Complementa a `investigacion.md` (mismo directorio), que contiene las fuentes y la justificación de cada decisión. Este documento es autosuficiente para ejecutarlo sin haber leído el otro.

## 0. Decisiones cerradas y contexto de trabajo

- **Stack**: Python 3.12 (64 bits), PySide6, `rapidocr` (ONNX Runtime, CPU) con modelo latino, SQLite con FTS5, `httpx`, PyInstaller (one-dir) + Inno Setup. Tamaño final aceptado: 150-200 MB.
- **Idioma**: el usuario juega en español y quiere el overlay en español. Índice bilingüe (nombre inglés + `i18n.es`) porque wiki, warframe.market y las APIs trabajan en inglés.
- **Funciones**: buscador de drops, objetivos de farmeo, estado del mundo completo (fisuras, ciclos, invasiones, alertas, arbitraciones, Baro, Nightwave, sortie, cazas de arcontes, Steel Path), precios de warframe.market, OCR de recompensas de reliquia automático por `EE.log` (con interruptor) y OCR bajo demanda del objeto bajo el cursor.
- **Plataforma**: solo PC; el código guarda la plataforma en un único sitio (`config.plataforma = "pc"`) para poder añadir selector después.
- **Distribución**: repo privado por ahora; instalador Inno Setup y zip portable; actualizador preparado contra GitHub Releases.
- **Sin integración con AlecaFrame ni Overwolf. Sin lectura de memoria, sin inyección, sin envío de entradas al juego, sin credenciales de la cuenta.**
- **Nombre del programa**: pendiente de elegir por el usuario. Propuestas: **Reliquario**, **Farmadex**, **Vórtice**. Usar `Reliquario` como nombre provisional en código y sustituir por constante única `NOMBRE_APP`.
- **User-Agent de warframe.market**: `{NOMBRE_APP}/{version} (+{URL_CONTACTO})`. `URL_CONTACTO` es un dato **a rellenar antes de la primera build** (URL del repo cuando sea público o un correo creado para el proyecto). No usar datos personales del usuario. Hasta entonces, el módulo de mercado se niega a arrancar si `URL_CONTACTO` está vacío y lo dice en el log.
- **Hotkeys por defecto** (todas configurables en Ajustes; se registran con `RegisterHotKey`, que se traga la combinación completa y no llega al juego; Warframe usa Ctrl para agacharse y no asigna Alt por defecto, así que las combinaciones Ctrl+Alt+letra no colisionan con nada útil):
  - `Ctrl+Alt+W`: mostrar/ocultar el overlay.
  - `Ctrl+Alt+Q`: "¿qué es esto?" (OCR del objeto bajo el cursor).
  - `Ctrl+Alt+R`: OCR manual de la pantalla de recompensas de reliquia.
  - `Escape` dentro del overlay: ocultarlo.
- **Cómo trabaja el usuario** (obligatorio en todas las fases): todo proceso que tarde más de un segundo tiene barra de progreso visible en la ventana; las herramientas nuevas van como pestañas de la misma ventana; el programa arranca y prepara solo todo lo que necesita (crea carpetas, descarga datos, construye índice, descarga nada del OCR en tiempo de ejecución porque va empaquetado); el usuario solo ejecuta el `.exe`.
- **Rutas**: proyecto en `C:\Users\angel\Escritorio\claude\warframe-overlay`. Datos de usuario en `%LocalAppData%\{NOMBRE_APP}\` (`datos\` para JSON descargados, `db\indice.sqlite`, `db\usuario.sqlite`, `logs\`, `config.json`). Nada se escribe en la carpeta de instalación ni en el Escritorio.
- **Idioma del código**: identificadores, comentarios y textos de interfaz en español; nombres de campos de las fuentes externas se conservan tal cual (`uniqueName`, `chance`...).

### Estructura de carpetas del proyecto

```
warframe-overlay/
  investigacion.md, plan.md
  pyproject.toml           # dependencias fijadas con versiones
  src/reliquario/
    __main__.py            # python -m reliquario
    app.py                 # QApplication, bandeja, hotkeys, ciclo de vida
    config.py              # rutas, constantes (NOMBRE_APP, URL_CONTACTO, plataforma), carga/guardado de config.json
    registro_log.py        # logging a fichero rotativo en logs/
    ui/  ventana.py  overlay.py  pestana_buscador.py  pestana_objetivos.py  pestana_mundo.py
         pestana_market.py  pestana_ajustes.py  widgets.py (barra de progreso, tarjetas)
    datos/  descargas.py  indice.py  esquema.sql  items.py  drops.py  relaciones.py  nodos.py
    online/  worldstate.py  market.py  http.py (cliente httpx con caché y límites)
    captura/  pantalla.py  ocr.py  reliquias.py  cursor.py  calibracion.py
    registro/  eelog.py
    estado/  objetivos.py  usuario_db.py
    actualizador/  datos.py  app.py
  recursos/  iconos/  modelos_ocr/ (det + rec latino + diccionario)  regiones_recompensas.json
  tests/                   # pytest; fixtures con JSON recortados en tests/fixtures/
  empaquetado/  reliquario.spec  instalador.iss  construir.ps1
  herramientas/  recortar_fixtures.py  comprobar_fuentes.py
```

---

## 1. Fuentes de datos: ficheros, endpoints, cabeceras y límites

Todo el HTTP pasa por `online/http.py`: `httpx.Client(timeout=30, headers={"User-Agent": UA}, http2=False)`, reintentos con espera exponencial (3 intentos), caché en disco por URL con `ETag`/`Last-Modified` cuando el servidor lo devuelva. Una cola por host que respeta el límite indicado abajo.

### 1.1 WFCD warframe-items (estático, MIT)

- Base: `https://raw.githubusercontent.com/WFCD/warframe-items/master/data/json/`
- Ficheros a descargar (usar los `.min.json` si existen, comprobar con HEAD; si no, los normales): `Warframes`, `Primary`, `Secondary`, `Melee`, `Arch-Gun`, `Arch-Melee`, `Archwing`, `Sentinels`, `SentinelWeapons`, `Pets`, `Mods`, `Arcanes`, `Relics`, `Resources`, `Misc`, `Gear`, `Quests`, `Skins`, `Sigils`, `Glyphs`, `Fish`, `Railjack`, `Node`, `Honoria`, e `i18n.json` (52 MB; se descarga y se filtra a `es` en el import, guardando solo lo filtrado). Total ~140 MB de descarga inicial, con barra de progreso por fichero y global.
- Versión: `https://api.github.com/repos/WFCD/warframe-items/commits?path=data/json&per_page=1` -> `[0].sha` y `[0].commit.committer.date`. Cabecera `Accept: application/vnd.github+json`. Límite GitHub sin token: 60 peticiones/hora por IP; una al arrancar basta. Cachear el resultado 6 h.
- Campos que se usan (de `index.d.ts` del repo): `uniqueName`, `name`, `category`, `type`, `tradable`, `vaulted`, `vaultDate`, `imageName`, `wikiaUrl`, `description`, `drops[] {location, type, rarity, chance, rotation}`, `components[] {uniqueName, name, itemCount, ducats, tradable, drops[]}`, en reliquias `rewards[] {rarity, chance, item{name, uniqueName}}` y `locations[]`. Nodos (`Node.json`): `uniqueName` (`SolNode203`), `name`, `systemName`, `missionIndex`, `factionIndex`, `minEnemyLevel`, `maxEnemyLevel`.
- `i18n.json`: objeto `uniqueName -> { es: {name, description, systemName?}, de: ..., ... }`. Se conserva solo `es`.
- Imágenes: `https://cdn.warframestat.us/img/{imageName}` bajo demanda con caché en `datos\img\`.

### 1.2 WFCD warframe-drop-data (estático, MIT; tablas oficiales de DE)

- Base: `https://drops.warframestat.us/data/`
- `info.json` -> `{hash, timestamp, modified}`: se guarda `hash`; si cambia, se redescarga todo lo de abajo.
- Ficheros: `missionRewards.json`, `relics.json`, `modLocations.json`, `enemyModTables.json`, `blueprintLocations.json`, `enemyBlueprintTables.json`, `sortieRewards.json`, `transientRewards.json`, `cetusBountyRewards.json`, `solarisBountyRewards.json`, `zarimanRewards.json`, `keyRewards.json`, `syndicates.json`. (Alternativa: `all.json` de una vez.)
- Estructuras (del README del repo):
  - `missionRewards: { Planeta: { Nodo: { gameMode, isEvent, rewards: {A:[{itemName, chance, rarity}], B:[...], C:[...]} | [{itemName, chance, rarity}] } } }`. **La clave `Nodo` es el nombre en inglés tal como lo escribe DE**, p. ej. `"Hydron"`; en algunos casos lleva sufijo entre paréntesis (p. ej. `"Mot (Void)"` no aparece así aquí, pero sí en otras fuentes: normalizar quitando ` (Planeta)` antes de casar con `Node.json`).
  - `relics: [{tier, relicName, state (Intact|Exceptional|Flawless|Radiant), rewards:[{itemName, chance, rarity}]}]`.
  - `modLocations: [{modName, enemies:[{enemyName, enemyModDropChance, chance}]}]`; `enemyModTables: [{enemyName, enemyModDropChance, mods:[{modName, chance}]}]`.
  - `blueprintLocations: [{itemName, enemies:[{enemyName, enemyItemDropChance, chance}]}]`; `enemyBlueprintTables` simétrico.
  - `cetusBountyRewards | solarisBountyRewards | zarimanRewards: [{bountyLevel, rewards:{A:[{stage, itemName, chance, rarity}], B, C}}]`.
  - `transientRewards: [{objectiveName, rewards:[{itemName, chance, rarity, rotation?}]}]` (Arbitrations, Void Storms, Derelict Vault...).
  - `sortieRewards: [{itemName, chance, rarity}]`; `keyRewards` como missionRewards; `syndicates: { Nombre: [{item, chance, rarity, place, standing}] }`.
- Todos los nombres están en inglés. Se casan con `warframe-items` por `name` exacto (tras normalizar mayúsculas y espacios) y, si falla, por coincidencia difusa con umbral alto y se registra en el log como "sin casar" para revisarlo.

### 1.3 api.warframestat.us (worldstate; Apache-2.0; sin rate limit publicado)

- Base: `https://api.warframestat.us/pc/` (`pc` sale de `config.plataforma`). Añadir siempre `?language=es` (traduce descripciones y algunos nombres; **los nodos y tipos de misión siguen en inglés**, ver 2.4).
- Endpoints hijos que se usan: `fissures`, `earthCycle`, `cetusCycle`, `vallisCycle`, `cambionCycle`, `zarimanCycle`, `duviriCycle`, `invasions`, `alerts`, `arbitration`, `voidTrader`, `vaultTrader`, `nightwave`, `sortie`, `archonHunt`, `steelPath`, `events`. Alternativa más barata: una sola petición a `/pc/?language=es` (worldstate completo, ~200 KB) cada 60 s y repartir claves; es lo que se hará, con fallback a los hijos si falla el parseo de una clave.
- Política: refresco cada 60 s mientras el overlay esté visible o haya objetivos activos; cada 5 min si está oculto. Cabecera `User-Agent` propia. Si responde 5xx o timeout, se mantiene el último dato con marca "desactualizado hace N min".
- Campos de fisura: `id, node ("Alator (Mars)"), missionType, missionKey, tier (Lith|Meso|Neo|Axi|Requiem|Omnia), tierNum, enemy, isStorm, isHard, activation, expiry, active`.

### 1.4 warframe.market API v2 (pre-release; 3 peticiones/segundo)

- Base: `https://api.warframe.market/v2/`. Cabeceras obligatorias: `User-Agent: {NOMBRE_APP}/{version} (+{URL_CONTACTO})`, `Language: es`, `Platform: pc`, `Accept: application/json`. Respuesta siempre `{apiVersion, data, error}`.
- `GET /items`: lista completa (`id, slug, gameRef, tags, i18n{es:{name}}`) — se descarga una vez al día y se guarda en el índice para mapear `uniqueName` (warframe-items) <-> `gameRef`/`slug` (market). `gameRef` es el mismo `/Lotus/...` que `uniqueName`, con lo que el casado es exacto en la mayoría de casos; para el resto, por nombre inglés.
- `GET /item/{slug}`: `ducats, tradingTax, setRoot, setParts, tags, i18n`.
- `GET /orders/item/{slug}/top`: `data.buy[]`, `data.sell[]` con `platinum, quantity, perTrade, visible, createdAt, user{ingameName, reputation, status (ingame|online|offline), platform}`. Se muestran las 5 mejores ventas de usuarios `ingame`/`online` y la mediana.
- Límite: cola global de 3 req/s con margen (usar 2/s). Caché por slug de 10 min. Nunca polling en bucle; los precios se piden solo cuando se muestra un objeto o en el OCR de recompensas (máximo 4 objetos).
- La API está por debajo de 1.0: aislar el parseo en `online/market.py` y cubrirlo con tests de fixture para detectar cambios de contrato.

### 1.5 Public Export de DE (solo para nodos en español, ver 2.4)

- Índice: `https://origin.warframe.com/PublicExport/index_es.txt.lzma` (LZMA, descomprimir con `lzma` de la biblioteca estándar). Contiene una línea por manifiesto, p. ej. `ExportRegions_es.json!00_hashxxxx`.
- Manifiesto: `https://content.warframe.com/PublicExport/Manifest/ExportRegions_es.json!00_hash` (misma cadena que da el índice). Es JSON (`{"ExportRegions":[{uniqueName ("SolNode203"), name, systemName, missionName, factionName, ...}]}`); DE a veces deja caracteres de control o saltos de línea sin escapar dentro de strings, así que parsear con `json.loads(texto, strict=False)` y, si falla, limpiar `\r` y `\n` dentro de cadenas antes de reintentar.
- Se descarga solo cuando cambia el hash del índice. Sin límite publicado; una petición al día como mucho.

### 1.6 Wiki oficial (solo enlaces)

- `wikiaUrl` de warframe-items (apunta ya a `wiki.warframe.com`). Botón "Abrir en la wiki" que lanza el navegador. No se scrapea nada (licencia CC BY-NC-SA).

---

## 2. Base de datos SQLite

Dos ficheros: `indice.sqlite` (se regenera desde los JSON; borrable) y `usuario.sqlite` (nunca se regenera; contiene lo del usuario). `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`. Versionado por tabla `meta(clave, valor)` con `esquema_version`.

### 2.1 `indice.sqlite` (`datos/esquema.sql`)

```sql
CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);
-- claves: esquema_version, items_sha, items_fecha, drops_hash, drops_modified,
--         regions_hash, market_items_fecha, construido_en

CREATE TABLE items (
  id INTEGER PRIMARY KEY,
  unique_name TEXT NOT NULL UNIQUE,      -- /Lotus/...
  nombre_en TEXT NOT NULL,
  nombre_es TEXT,                        -- NULL si i18n no lo trae; la UI cae a nombre_en
  descripcion_es TEXT,
  categoria TEXT NOT NULL,               -- Warframes, Primary, Mods, Relics, Resources, Node...
  tipo TEXT,                             -- type de warframe-items
  es_prime INTEGER NOT NULL DEFAULT 0,
  comerciable INTEGER NOT NULL DEFAULT 0,
  vaulted INTEGER,                       -- NULL = no aplica
  vault_fecha TEXT,
  imagen TEXT,
  wiki_url TEXT,
  padre_id INTEGER REFERENCES items(id), -- componentes: apunta al objeto padre
  item_count INTEGER,                    -- componentes: cuántos hace falta
  ducados INTEGER,
  market_slug TEXT,                      -- de warframe.market /items
  market_id TEXT
);
CREATE INDEX ix_items_categoria ON items(categoria);
CREATE INDEX ix_items_padre ON items(padre_id);
CREATE INDEX ix_items_nombre_en ON items(nombre_en);

-- Fuentes de obtención unificadas: cada fila es "item X cae en Y"
CREATE TABLE fuentes (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id),
  tipo TEXT NOT NULL,       -- 'reliquia','mision','enemigo','bounty','sindicato','sortie',
                            -- 'transitoria','llave','baro','tienda','quest','otro'
  origen_id INTEGER,        -- FK lógica: reliquia -> items.id de la reliquia; mision -> nodos.id
  origen_texto TEXT NOT NULL, -- texto original en inglés (p. ej. 'Axi A7 Relic (Radiant)', 'Grineer Manic')
  refinamiento TEXT,        -- Intact|Exceptional|Flawless|Radiant (solo reliquias)
  rotacion TEXT,            -- A|B|C|NULL
  etapa TEXT,               -- bounties: 'Stage 1'...
  rareza TEXT,              -- Common|Uncommon|Rare|Legendary
  probabilidad REAL,        -- porcentaje 0-100
  probabilidad_enemigo REAL,-- enemyModDropChance / enemyItemDropChance
  standing INTEGER,
  datos_extra TEXT          -- JSON libre
);
CREATE INDEX ix_fuentes_item ON fuentes(item_id);
CREATE INDEX ix_fuentes_origen ON fuentes(tipo, origen_id);

CREATE TABLE nodos (
  id INTEGER PRIMARY KEY,
  unique_name TEXT UNIQUE,   -- SolNode203
  nombre_en TEXT NOT NULL,   -- Abaddon
  nombre_es TEXT,            -- de ExportRegions_es
  planeta_en TEXT NOT NULL,  -- Europa
  planeta_es TEXT,
  mision_en TEXT,            -- gameMode de drop-data / missionName
  mision_es TEXT,
  faccion_en TEXT, faccion_es TEXT,
  nivel_min INTEGER, nivel_max INTEGER,
  clave_drops TEXT           -- 'Europa/Abaddon' para casar con missionRewards
);
CREATE UNIQUE INDEX ux_nodos_clave ON nodos(clave_drops);

-- Traducciones de términos sueltos (tipos de misión, facciones, rotaciones, rarezas, eras)
CREATE TABLE glosario (dominio TEXT, en TEXT, es TEXT, PRIMARY KEY(dominio, en));

-- Contenido de cada reliquia (para la pantalla de recompensas y la ficha de reliquia)
CREATE TABLE reliquia_recompensas (
  reliquia_id INTEGER NOT NULL REFERENCES items(id),
  refinamiento TEXT NOT NULL,
  item_id INTEGER NOT NULL REFERENCES items(id),
  rareza TEXT, probabilidad REAL,
  PRIMARY KEY (reliquia_id, refinamiento, item_id)
);

-- Índice de texto completo: una fila por nombre (en y es) de cada item
CREATE VIRTUAL TABLE busqueda USING fts5(
  texto,                 -- nombre normalizado (ver abajo)
  item_id UNINDEXED,
  idioma UNINDEXED,      -- 'es' | 'en'
  categoria UNINDEXED,
  tokenize = "unicode61 remove_diacritics 2 tokenchars '-'"
);
```

Normalización antes de indexar y antes de buscar (misma función `normalizar()` en `datos/indice.py`): NFKD, quitar diacríticos, minúsculas, quitar signos salvo guion, colapsar espacios. Consulta FTS: cada palabra del usuario como prefijo (`"sistem"* "ash"*`), ordenada por `bm25(busqueda)`, con desempate: idioma `es` primero, luego categorías Warframes/Primary/Secondary/Melee/Mods/Arcanes/Resources, y exactitud. Si FTS devuelve 0 filas, fallback con `rapidfuzz.process.extract` sobre la tabla `items` (nombres normalizados en memoria) con umbral 80. Ese mismo fallback es el que usa el OCR.

### 2.2 `usuario.sqlite` (`estado/usuario_db.py`)

```sql
CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE objetivos (
  id INTEGER PRIMARY KEY,
  item_unique_name TEXT NOT NULL,   -- se guarda unique_name, no items.id, porque indice.sqlite se regenera
  cantidad_objetivo INTEGER NOT NULL DEFAULT 1,
  cantidad_actual INTEGER NOT NULL DEFAULT 0,
  creado_en TEXT NOT NULL, completado_en TEXT, notas TEXT, orden INTEGER
);
CREATE TABLE progreso_eventos (            -- de dónde vino cada incremento
  id INTEGER PRIMARY KEY, objetivo_id INTEGER REFERENCES objetivos(id),
  origen TEXT NOT NULL,                    -- 'manual' | 'eelog' | 'ocr'
  cantidad INTEGER NOT NULL, detalle TEXT, creado_en TEXT NOT NULL
);
CREATE TABLE cache_market (
  slug TEXT PRIMARY KEY, respuesta TEXT NOT NULL, obtenido_en TEXT NOT NULL
);
CREATE TABLE historial_recompensas (        -- pantallas de reliquia leídas por OCR
  id INTEGER PRIMARY KEY, leido_en TEXT NOT NULL, textos_ocr TEXT NOT NULL,
  items_json TEXT NOT NULL, elegido_unique_name TEXT
);
CREATE TABLE calibracion_ocr (
  resolucion TEXT PRIMARY KEY,             -- '2560x1440'
  regiones_json TEXT NOT NULL              -- rectángulos relativos de las 1-4 recompensas
);
```

`config.json` (no en SQLite, para poder editarlo a mano): hotkeys, posición/tamaño/opacidad del overlay, `ocr_reliquias_auto: true`, `motor_ocr: "rapidocr"`, `plataforma: "pc"`, `idioma_ui: "es"`, `comprobar_actualizaciones_app: true`, `ruta_eelog` (por defecto `%LocalAppData%\Warframe\EE.log`).

### 2.3 Resolución de la cadena parte -> reliquia (vaulted) -> misión -> fisura activa

1. **Búsqueda**: el texto del usuario se normaliza y va a `busqueda` (FTS5). Devuelve `item_id`. Si es un componente (`padre_id` no nulo), la ficha muestra el padre y resalta el componente; si es un padre con componentes, muestra todos.
2. **Fuentes del componente**: `SELECT * FROM fuentes WHERE item_id=? ORDER BY tipo, probabilidad DESC`. Las filas `tipo='reliquia'` se agrupan por `origen_id` (la reliquia) mostrando las 4 probabilidades por refinamiento; se lee `items.vaulted` de la reliquia y se marca "En bóveda" (gris, al final) o "Disponible". Origen de estas filas en el import: `components[].drops[]` de warframe-items, cuyo `location` es `"Axi A7 Relic (Radiant)"`; se parsea con la expresión `^(Lith|Meso|Neo|Axi|Requiem|Omnia|Vanguard) (\w+) Relic(?: \((Intact|Exceptional|Flawless|Radiant)\))?$` y se casa con el item de categoría `Relics` cuyo `nombre_en` es `"Axi A7 Relic"`. Además se cruza con `relics.json` de drop-data para completar refinamientos que falten.
3. **Dónde cae la reliquia**: `SELECT * FROM fuentes WHERE item_id = <id de la reliquia> AND tipo IN ('mision','bounty','transitoria','llave')`. Estas filas vienen de `missionRewards.json` (clave Planeta/Nodo, rotación, probabilidad), bounties y transitorias; en el import se busca en cada tabla toda `itemName` que termine en ` Relic` y se casa con el item de la reliquia. Cada fila `mision` guarda `origen_id = nodos.id`, y de `nodos` salen `nombre_es`, `planeta_es`, `mision_es`, niveles.
4. **Fisuras activas ahora**: el worldstate da `fissures[]` con `node="Alator (Mars)"` y `tier="Axi"`. Se parsea `^(.*) \((.*)\)$` -> nodo `Alator`, planeta `Mars`, se busca `nodos` por (`nombre_en`, `planeta_en`) y se obtiene `nodos.id`. Para una reliquia de era `Axi`, en la ficha se listan las fisuras activas de esa era ordenadas por: nodos que además la dropean (poco frecuente, es un bonus), luego tipo de misión "rápido" (Captura, Exterminio, Sabotaje, Rescate), luego tiempo restante. También al revés: en la pestaña Mundo, cada fisura muestra "reliquias que necesitas para tus objetivos" (era coincidente).
5. **Nombres en español**: nodos y planetas de `nodos.nombre_es/planeta_es` (ExportRegions_es); tipo de misión, facción, rareza, rotación y era desde `glosario` (tabla pequeña rellenada a mano en `datos/glosario_es.json`: `Interception -> Intercepción`, `Defense -> Defensa`, `Survival -> Supervivencia`, `Excavation -> Excavación`, `Capture -> Captura`, `Exterminate -> Exterminio`, `Sabotage -> Sabotaje`, `Rescue -> Rescate`, `Spy -> Espionaje`, `Mobile Defense -> Defensa móvil`, `Disruption -> Disrupción`, `Void Cascade -> Cascada del Vacío`, `Common -> Común`, `Uncommon -> Poco común`, `Rare -> Raro`, `Rotation A -> Rotación A`, etc.). Si falta una traducción se muestra el inglés y se anota en el log.

---

## 3. Fases

Cada fase termina con: tests de la fase en verde (`pytest tests/ -q`, filtrar salida a las últimas 5 líneas), la app arrancando con `python -m reliquario` sin trazas de error en `logs\`, y una anotación en `CHANGELOG.md`. No pasar a la siguiente sin cumplir el criterio de aceptación.

### Fase 1. MVP de punta a punta: descargar datos, índice, buscar y ver drops

**Objetivo**: ejecutar `python -m reliquario`, que descargue solo los datos con barra de progreso, construya el índice y permita escribir "sistemas de ash prime" y ver de dónde cae.

**Ficheros**: `pyproject.toml`, `src/reliquario/{__main__,app,config,registro_log}.py`, `datos/{descargas,indice,items,drops,esquema.sql}.py`, `ui/{ventana,pestana_buscador,widgets}.py`, `datos/glosario_es.json`, `tests/test_indice.py`, `tests/test_import_drops.py`, `herramientas/recortar_fixtures.py`, `tests/fixtures/*.json` (recortes de 20-50 objetos por fichero, generados por la herramienta a partir de los JSON reales).

**Implementar**:
- `config.py`: rutas en `%LocalAppData%`, creación de carpetas, `NOMBRE_APP`, versión, lectura/escritura de `config.json` con valores por defecto.
- `descargas.py`: descarga con `httpx` en streaming, progreso por bytes (señal Qt), verificación de tamaño, escritura atómica (`.tmp` + rename), registro de `sha`/`hash` en `meta`. Descarga solo lo que falte o haya cambiado.
- `indice.py`: crea `indice.sqlite` desde `esquema.sql`; importa items (padres y componentes, `es_prime` = `"Prime" in nombre_en`), `i18n` filtrado a `es`, reliquias y `reliquia_recompensas`, nodos (solo de `Node.json`, sin español todavía), `fuentes` de tipo `reliquia`, `mision`, `enemigo`, `bounty`, `sindicato`, `sortie`, `transitoria`, `llave`; rellena `busqueda`. Corre en un `QThread` con progreso por etapas ("Importando objetos 3/24...").
- `ui/ventana.py`: `QMainWindow` normal (todavía no overlay) con `QTabWidget`; pestaña "Buscar" con `QLineEdit` + lista de resultados + panel de ficha (nombre es/en, categoría, imagen, componentes, y tabla de fuentes agrupadas por tipo con probabilidad y rotación). Barra de progreso global en la barra de estado.
- `registro_log.py`: fichero rotativo `logs\reliquario.log`, nivel INFO, excepciones no capturadas a log y a un diálogo.

**Aceptación**: en un PC con los datos borrados, `python -m reliquario` muestra la ventana con barra de progreso, termina la descarga e importación sin errores en el log (tiempo esperado 1-3 min), y al escribir `sistemas ash prime` el primer resultado es "Sistemas de Ash Prime" (o el nombre que traiga `i18n.es`) con al menos una fila de fuente `reliquia` que contiene `Axi A7`. `pytest` pasa con fixtures. Segundo arranque: sin descargas (log dice "datos al día").

### Fase 2. Cadena completa y nodos en español

**Objetivo**: ficha completa parte -> reliquias (vaulted) -> misiones con nodo/planeta/tipo en español; ficha de reliquia con su contenido.

**Ficheros**: `datos/{relaciones,nodos}.py`, ampliación de `indice.py`, `ui/pestana_buscador.py`, `tests/test_relaciones.py`, `tests/test_nodos.py`.

**Implementar**:
- `nodos.py`: descarga de `index_es.txt.lzma`, localización de `ExportRegions_es.json!...`, descarga y parseo tolerante, casado con `Node.json` por `uniqueName` (`SolNode203`) y relleno de `nombre_es`, `planeta_es`, `mision_es`, `faccion_es`. Casado de `missionRewards` (Planeta/Nodo en inglés) con `nodos` por (`planeta_en`, `nombre_en`) normalizados; los no casados se registran y se guardan igualmente con `origen_id NULL` y `origen_texto` para no perder información.
- `relaciones.py`: funciones `fuentes_de(item_id)`, `reliquias_de(componente_id)` (agrupadas, con `vaulted`), `misiones_de(reliquia_id)`, `contenido_de(reliquia_id, refinamiento)`, `mejor_ruta(componente_id)` (heurística: reliquia no vaulted con mayor probabilidad en Radiant, y la misión con mayor probabilidad de esa reliquia).
- UI: en la ficha, sección "Reliquias" con badge "En bóveda"/"Disponible", desplegable por reliquia con sus misiones ("Hydron, Sedna · Defensa · Rotación B · 12,5 %"); clic en una reliquia abre su ficha (contenido por refinamiento). Filtro "ocultar en bóveda" (activado por defecto, recordado en config).

**Aceptación**: buscar `axi a7` abre la ficha de la reliquia con las 4 columnas de refinamiento y una lista de misiones con nodo y planeta en español (p. ej. `Hidrón, Sedna`); el log de import muestra menos de 3 % de nodos sin casar. Test: `misiones_de(Axi A7)` devuelve al menos una fila con `rotacion` y `probabilidad > 0`.

### Fase 3. Overlay, hotkey global, bandeja y ajustes

**Objetivo**: la misma ventana se convierte en overlay encima de Warframe, se abre/cierra con `Ctrl+Alt+W`, y hay pestaña de Ajustes.

**Ficheros**: `ui/{overlay,pestana_ajustes}.py`, `app.py` (bandeja `QSystemTrayIcon`, registro de hotkeys), `tests/test_hotkeys.py` (parseo de combinaciones).

**Implementar**:
- `overlay.py`: la ventana pasa a `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`, `WA_TranslucentBackground`, fondo semitransparente configurable (opacidad 0,85 por defecto), esquinas redondeadas, arrastrable por la cabecera, tamaño y posición recordados. Al mostrarse, `activateWindow()` + foco en el buscador; `Escape` la oculta. Al ocultarse no libera nada (sigue en memoria para abrir en < 100 ms).
- Hotkeys: hilo nativo con `RegisterHotKey` vía `ctypes` (bucle `GetMessage` en su propio hilo, `WM_HOTKEY` -> señal Qt). Parseo de cadenas `"Ctrl+Alt+W"` a modificadores/`VK_*`. Si el registro falla (combinación ocupada), aviso en la bandeja y en Ajustes.
- Bandeja: icono con menú (Mostrar, Ajustes, Actualizar datos, Salir). Cerrar la ventana la oculta; salir solo desde la bandeja. Arranque con Windows opcional (clave en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, desactivado por defecto).
- Ajustes: hotkeys (captura de combinación al pulsar), opacidad, posición inicial (centrado / última), `ocr_reliquias_auto` (se usa en fase 7), motor OCR, ruta de `EE.log`, botón "Reconstruir índice", botón "Abrir carpeta de datos", versión y estado de datos (fechas de items y drops).
- Aviso al detectar que Warframe está en pantalla completa exclusiva: comprobación heurística con `GetForegroundWindow` + `GetWindowRect` == tamaño de monitor y sin estilo `WS_BORDER`... no es fiable, así que se limita a un texto en Ajustes: "Warframe debe estar en Ventana sin bordes (o DX12). En pantalla completa exclusiva el overlay no se ve".

**Aceptación**: con Warframe abierto en ventana sin bordes, `Ctrl+Alt+W` muestra el overlay encima del juego y vuelve a ocultarlo; se puede escribir en el buscador; `Escape` lo oculta; cambiar la hotkey en Ajustes surte efecto sin reiniciar; el icono de bandeja aparece y "Salir" cierra el proceso limpiamente (log sin excepciones).

### Fase 4. Estado del mundo completo

**Objetivo**: pestaña "Mundo" con fisuras, ciclos, invasiones, alertas, arbitración, Baro (y bóveda de Varzia), Nightwave, sortie, caza de arcontes y Steel Path, en español, y cruce con reliquias/objetivos.

**Ficheros**: `online/{http,worldstate}.py`, `ui/pestana_mundo.py`, `tests/test_worldstate.py` (fixture de `/pc/?language=es` recortada).

**Implementar**:
- `http.py`: cliente compartido, cola por host, reintentos, caché en disco, cabecera `User-Agent`.
- `worldstate.py`: `QTimer` 60 s (visible) / 300 s (oculto); una petición a `/pc/?language=es`; parseo defensivo por clave (una clave rota no tumba las demás; se registra); modelos `dataclass` para fisura, ciclo, invasión, alerta, arbitración, comerciante, nightwave, sortie, archon, steel path; traducción de `node`, `missionType`, `enemy`, `tier` con `nodos` y `glosario`; cuenta atrás calculada en cliente a partir de `expiry` (no se vuelve a pedir para refrescar el reloj).
- UI: tarjetas por bloque con cuenta atrás; fisuras agrupadas por era con filtro Normal/Steel Path/Void Storm y marcado "sirve para: <objetivo>" cuando la era coincide con una reliquia necesaria para un objetivo (fase 6 lo alimenta; hasta entonces el marcado se basa en la ficha abierta); invasiones con recompensas de cada bando casadas con `items` (clic abre la ficha); Baro con inventario casado con `items` cuando está activo; sortie/arcontes con misiones y modificadores traducidos; Steel Path con la oferta rotativa; ciclos de Tierra/Cetus/Vallis/Cambion/Zariman/Duviri.
- Estado "desactualizado hace N min" si la última petición falló.

**Aceptación**: la pestaña se rellena en menos de 3 s tras abrir el overlay; los nodos de fisura aparecen en español; desconectar la red no rompe la pestaña (muestra el último estado con aviso); test de parseo pasa con la fixture y con una fixture mutilada (clave `fissures` ausente).

### Fase 5. Precios de warframe.market

**Objetivo**: precio en platino y ducados en la ficha de cada objeto comerciable y pestaña "Mercado" para consultar cualquier objeto.

**Ficheros**: `online/market.py`, `ui/pestana_market.py`, ampliación de `indice.py` (importar `/items` a `items.market_slug/market_id`), `tests/test_market.py`.

**Implementar**:
- Import diario de `GET /items` (cabeceras `Language: es`, `Platform: pc`) y casado por `gameRef == unique_name`, fallback por nombre inglés; guardar `market_slug`.
- `precio(slug)`: `GET /orders/item/{slug}/top`; filtra `visible` y usuarios `ingame`/`online`; devuelve las 5 ventas más baratas, mediana de venta, mejor compra, `ducats` de `GET /item/{slug}` (cacheado 24 h). Caché 10 min en `cache_market`. Cola global 2 req/s. Si `URL_CONTACTO` está vacío, el módulo se desactiva con aviso visible en Ajustes.
- UI: en la ficha, bloque "Mercado" con los datos y botón "Copiar mensaje de compra" (`/w {ingameName} Hi! I want to buy: "{nombre_en}" for {platinum} platinum. (warframe.market)`); pestaña Mercado con buscador propio (reutiliza el índice) e historial de consultas.
- Indicador "platino por ducado" para las piezas prime.

**Aceptación**: abrir la ficha de `Sistemas de Ash Prime` muestra 5 órdenes de venta y la mediana en menos de 2 s; abrir 10 fichas seguidas no produce ningún 429 (comprobar en el log); repetir la misma ficha en menos de 10 min no hace petición.

### Fase 6. Objetivos de farmeo y lectura de EE.log

**Objetivo**: pestaña "Objetivos" con lista de objetos a conseguir, progreso manual, y suma automática de lo que registre `EE.log`.

**Ficheros**: `estado/{objetivos,usuario_db}.py`, `registro/eelog.py`, `ui/pestana_objetivos.py`, `tests/test_eelog.py` (fixture con fragmentos reales de `EE.log` anonimizados), `tests/test_objetivos.py`.

**Implementar**:
- `usuario_db.py`: creación y migraciones de `usuario.sqlite`.
- `objetivos.py`: alta desde la ficha ("Añadir a objetivos", con cantidad; para un warframe/arma prime, botón "añadir el set completo" que crea un objetivo por componente con `item_count`), incremento manual (+1/-1), completado, reordenación, borrado. Para cada objetivo, cálculo de "mejor ruta ahora" (`relaciones.mejor_ruta` + fisuras activas de la era).
- `eelog.py`: `QThread` que abre `%LocalAppData%\Warframe\EE.log` con `FILE_SHARE_READ|FILE_SHARE_WRITE` (en Python: `open(..., 'r', encoding='utf-8', errors='replace')` funciona porque el juego lo abre compartido), hace `seek` al final al arrancar, detecta truncado (tamaño menor que la posición: el juego se reinició) y emite líneas nuevas. Formato de línea: `<segundos> <Fuente> [<Tipo>]: <mensaje>`. Detecta: fin de misión y recompensas (líneas de tipo `Script [Info]` que contienen nombres `/Lotus/...` de objetos obtenidos; hay que identificar los patrones exactos con una sesión real del usuario y guardarlos como fixtures), y la apertura de la pantalla de recompensas de reliquia (WFInfo busca las cadenas `Pause countdown done` y `Got rewards`; verificar contra `EE.log` real y ajustar). Los `uniqueName` encontrados se casan con `items` y suman al objetivo si existe (`progreso_eventos.origen='eelog'`). **El contenido del fichero nunca se copia, sube ni muestra entero**: contiene IP y correo del usuario; solo se procesan las líneas reconocidas.
- Notificación discreta en el overlay (toast) cuando un objetivo avanza o se completa.

**Aceptación**: añadir "Ash Prime (set)" crea 4 objetivos con cantidades correctas; el +1 manual persiste tras reiniciar la app; con la fixture de `EE.log` reproducida línea a línea en un fichero temporal, el test detecta la recompensa y suma 1 al objetivo correspondiente; tras una misión real, el log de la app registra "EE.log: recompensa reconocida ..." (o "no reconocida" con la línea, para ampliar patrones).

### Fase 7. OCR: recompensas de reliquia y objeto bajo el cursor

**Objetivo**: al aparecer la pantalla de recompensas (detectada por `EE.log`, o con `Ctrl+Alt+R`), leer los 1-4 nombres, mostrar sobre cada uno precio/ducados/vaulted/"lo necesitas"; con `Ctrl+Alt+Q`, leer el nombre bajo el cursor y abrir su ficha.

**Ficheros**: `captura/{pantalla,ocr,reliquias,cursor,calibracion}.py`, `recursos/modelos_ocr/`, `recursos/regiones_recompensas.json`, `tests/test_ocr.py` (capturas reales del usuario en `tests/fixtures/capturas/`, con la salida esperada).

**Implementar**:
- `pantalla.py`: localizar el HWND de Warframe (`FindWindow` por clase/título, o `EnumWindows` buscando el proceso `Warframe.x64.exe`), `GetClientRect` + `ClientToScreen`, captura con `mss` de esa región; ocultar el overlay 1 frame antes si se solapa. DPI awareness `PerMonitorV2` declarado en el manifiesto del ejecutable.
- `ocr.py`: envoltorio de `rapidocr` con `Det.model_path` y `Rec.model_path` apuntando a `recursos/modelos_ocr/` (modelo de detección por defecto de la versión fijada y modelo de reconocimiento `latin` PP-OCRv5 mobile con su diccionario; descargarlos una vez durante el desarrollo y **versionarlos en el repo**, nunca descargar en tiempo de ejecución). Preprocesado: recorte, escala x2, gris, umbral adaptativo. Casado: `rapidfuzz` contra nombres `es` (y `en` como respaldo) restringido a categorías plausibles (en recompensas: componentes prime, planos, Forma, Kuva, Exilus...). Motor alternativo `winocr` (Windows.Media.Ocr) seleccionable en Ajustes; si el paquete de idioma OCR `es` no está instalado, mostrar el comando `Add-WindowsCapability -Online -Name "Language.OCR~~~es-ES~0.0.1.0"` y no fallar.
- `reliquias.py`: al recibir el evento de `EE.log` (si `ocr_reliquias_auto`) o la hotkey, esperar 1,5 s a que termine la animación, capturar, localizar las 1-4 tarjetas (regiones relativas por relación de aspecto en `regiones_recompensas.json`, con calibración manual en Ajustes si la resolución no está), OCR de cada nombre, y pintar sobre cada tarjeta una etiqueta con platino (mediana), ducados, "En bóveda" y "Objetivo: X/Y" en verde si sirve. Desaparece a los 12 s o al pulsar `Escape`. Guarda en `historial_recompensas`. Requisito documentado: opción "Etiquetas de objetos" activada en el juego y ventana sin bordes.
- `cursor.py`: `Ctrl+Alt+Q` captura un rectángulo de 600x160 px alrededor del cursor (ajustado por escala de UI), OCR, casado con umbral 85 y abre la ficha en el overlay; si hay varias candidatas, muestra las 3 mejores para elegir.
- Barra de progreso/indicador "Leyendo pantalla..." durante el OCR (0,3-1 s en CPU).

**Aceptación**: con las capturas de fixture, el test reconoce los 4 nombres correctos en al menos 9 de 10 capturas; en juego real, tras abrir una reliquia, aparecen las etiquetas encima de las recompensas sin pulsar nada, con precio y estado de bóveda; `Ctrl+Alt+Q` sobre un mod del arsenal abre su ficha en menos de 2 s. Desactivar `ocr_reliquias_auto` en Ajustes detiene el disparo automático sin reiniciar.

### Fase 8. Actualizador de datos y de la aplicación

**Objetivo**: los datos se mantienen al día solos; la app avisa de nuevas versiones (GitHub Releases) y prepara la actualización aunque el repo sea privado hoy.

**Ficheros**: `actualizador/{datos,app}.py`, ajustes correspondientes, `tests/test_actualizador.py`.

**Implementar**:
- Datos: al arrancar y cada 6 h, comparar `items_sha` (commit de GitHub), `drops_hash` (`info.json`), `regions_hash` (índice del Public Export) y fecha de `market_items`. Si algo cambió: descargar en segundo plano con progreso en la barra de estado, construir un `indice.sqlite.nuevo` completo y hacer swap atómico al terminar (la app sigue usable durante la construcción). Botón manual en Ajustes. Si GitHub devuelve 403 por rate limit, reintentar a la hora siguiente.
- Aplicación: `GET https://api.github.com/repos/{PROPIETARIO}/{REPO}/releases/latest` (constantes en `config.py`; mientras el repo sea privado la petición falla con 404 y se silencia). Comparar `tag_name` (semver) con la versión de la app; si hay nueva, mostrar aviso con notas y botón "Descargar" que abre el asset del instalador en el navegador (no se autoinstala). Dejar preparado, pero desactivado, el modo silencioso: descargar el instalador a `%Temp%`, verificar el hash SHA-256 publicado en las notas de la release, y lanzarlo con `/SILENT` al cerrar la app.
- `CHANGELOG.md` y política de versiones: `MAJOR.MINOR.PATCH`; el número vive en un único sitio (`pyproject.toml`) y se lee en tiempo de ejecución con `importlib.metadata`.

**Aceptación**: modificar a mano `meta.items_sha` en `indice.sqlite` y arrancar provoca una reconstrucción en segundo plano con progreso, sin bloquear la búsqueda, y al terminar el índice nuevo está en uso (log "índice sustituido"); test que simula una release nueva (fixture JSON) produce el aviso; con el repo privado, el arranque no muestra ningún error.

### Fase 9. Empaquetado, instalador y prueba en PC limpio

**Objetivo**: `empaquetado\construir.ps1` genera `Reliquario-{version}-setup.exe` y `Reliquario-{version}-portable.zip` que funcionan en un Windows 10/11 limpio sin Python.

**Ficheros**: `empaquetado/{reliquario.spec,instalador.iss,construir.ps1,manifiesto.xml}`, `recursos/iconos/reliquario.ico`, `README.md` (usuario final, con aviso legal).

**Implementar**:
- `reliquario.spec` (PyInstaller 6.x, one-dir, `--noconsole`, `--name Reliquario`, icono, manifiesto con `dpiAwareness=PerMonitorV2` y `longPathAware`): `datas` = `recursos/**` (modelos OCR, `glosario_es.json`, `regiones_recompensas.json`, iconos, `esquema.sql`); `hiddenimports`/`collect_all` para `rapidocr`, `onnxruntime`, `rapidfuzz`, `mss`, `httpx`; `collect_data_files("rapidocr")` para su `config.yaml`; `excludes` = `PySide6.QtWebEngine*`, `QtQml`, `Qt3D`, `QtMultimedia`, `QtCharts`, `tkinter`, `matplotlib`, `numpy.tests`... y borrado posterior de DLLs de Qt no usadas (`Qt6WebEngineCore.dll`, `Qt6Quick*.dll`, `Qt6Pdf.dll`, carpetas `qml/`, `translations/` salvo `qtbase_es.qm`). Objetivo de tamaño: < 200 MB instalados.
- Runtime de Visual C++: `onnxruntime` y Qt necesitan `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`, `MSVCP140.dll`. PyInstaller copia las del Python de compilación, pero para no depender de eso el instalador incluye `vc_redist.x64.exe` (Microsoft, "Visual C++ 2015-2022 Redistributable") y lo ejecuta con `/install /quiet /norestart` si falta (comprobar clave `HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64\Installed`). El zip portable lleva las tres DLL junto al `.exe`.
- `instalador.iss` (Inno Setup 6): instalación por usuario en `{localappdata}\Programs\Reliquario` (sin UAC), acceso directo en menú Inicio y opcional en escritorio, opción "Iniciar con Windows", desinstalador que pregunta si borrar `%LocalAppData%\Reliquario` (datos y objetivos). Firma de código: no hay certificado; documentar en el README el aviso de SmartScreen y cómo pasar ("Más información" -> "Ejecutar de todas formas").
- `construir.ps1`: crea/actualiza un venv limpio en `.venv-build`, instala dependencias fijadas, ejecuta `pytest`, PyInstaller, poda de DLL, calcula SHA-256 de los artefactos y los deja en `dist\`, compila el `.iss` con `ISCC.exe`, comprime el portable. Imprime tamaños.
- Prueba en limpio: en **Windows Sandbox** (viene con Windows 11 Pro, `Habilitar o deshabilitar las características de Windows` -> `Espacio aislado de Windows`) o una VM sin Python ni VC++: instalar, ejecutar, comprobar que descarga datos con progreso, busca, abre el overlay con la hotkey (sin juego, sobre el escritorio), hace OCR de una captura de prueba desde Ajustes (botón "Probar OCR con imagen") y cierra sin errores en `logs\`. Repetir con el zip portable. Comprobar arranque en frío < 6 s.
- `README.md`: requisitos (Windows 10 1809+ / 11, Warframe en ventana sin bordes o DX12, "Etiquetas de objetos" activadas), instalación, hotkeys, aviso legal ("herramienta no afiliada a Digital Extremes; solo lee la pantalla y el fichero de registro `EE.log`; no modifica el juego ni envía entradas; uso bajo tu responsabilidad conforme a la política de software de terceros de DE"), créditos y licencias de WFCD (MIT/Apache-2.0), warframe.market, RapidOCR (Apache-2.0), PySide6 (LGPL: enlazado dinámico, se cumple con one-dir y mención en el README).

**Aceptación**: `construir.ps1` termina sin errores y produce los dos artefactos con su SHA-256; el instalador se ejecuta en Windows Sandbox limpio y la app supera la lista de comprobación anterior; tamaño instalado < 200 MB; el desinstalador deja el sistema sin restos salvo lo que el usuario decida conservar.

---

## 4. Riesgos conocidos y plan de contingencia

| Riesgo | Detección | Qué hacer |
|---|---|---|
| Cambio de estructura en warframe-items (campos renombrados) | Tests de import con fixtures fallan al refrescar fixtures; en producción, contador de objetos importados cae > 20 % respecto al anterior | El actualizador aborta el swap del índice y conserva el anterior; aviso en Ajustes "datos nuevos no importables, se usan los del {fecha}". Arreglar import y publicar versión |
| drops.warframestat.us caído | HTTP 5xx / timeout | Se sigue con la copia local; `warframe-items` incluye ya `drops` por objeto, así que la búsqueda no se queda vacía, solo pierde detalle de misiones nuevas. Fuente alternativa documentada: parsear el HTML oficial de DE (`warframe-web-assets...hnfvc0o3jnfvc873njb03enrf56.html`), guardado como `datos/parser_droptable_html.py` de reserva si el repo WFCD dejara de mantenerse |
| api.warframestat.us caído o cambia claves | Parseo defensivo por clave; estado "desactualizado" | Fallback: `https://content.warframe.com/dynamic/worldState.php` (crudo de DE) con un parser mínimo solo para fisuras y ciclos (los campos son `ActiveMissions[]` con `Node` (`SolNode...`), `Modifier` (`VoidT1..T4`), `Expiry`). Se implementa solo si hace falta; dejarlo anotado |
| warframe.market v2 rompe contrato (< 1.0) o aplica 429 | Test de fixture; códigos 429/509 en log | Módulo de mercado se desactiva solo y muestra "precios no disponibles"; el resto de la app no depende de él. Bajar a 1 req/s si aparecen 429 |
| Public Export cambia formato o `ExportRegions_es` falla | Parseo tolerante; si falla, nodos sin `nombre_es` | La UI cae al nombre inglés; no bloquea nada |
| DE cambia la UI de recompensas o la fuente | Tasa de casado OCR baja (medida en `historial_recompensas`) | Calibración manual en Ajustes; actualizar `regiones_recompensas.json`; el resto de funciones no se ve afectado |
| DE cambia el formato de `EE.log` | Patrones no casan; log "no reconocida" | El OCR manual (`Ctrl+Alt+R`) sigue funcionando; actualizar patrones |
| DE endurece la política de terceros | Seguir foros/soporte; el README lo advierte | El programa no hace nada que no haga WFInfo; si DE prohibiera overlays, retirar la parte de captura y dejar el buscador como ventana normal |
| Rate limit de GitHub (60/h sin token) | 403 con `X-RateLimit-Remaining: 0` | Cachear 6 h; un solo `GET` por arranque; nunca en bucle |
| Falsos positivos de antivirus/SmartScreen en el `.exe` sin firmar | Aviso al instalar | Documentado en README; valorar certificado si se hace público |
| PyInstaller arrastra QtWebEngine (250 MB) | Tamaño de `dist\` | `excludes` y poda de DLL en `construir.ps1`; el script falla si `dist\` > 220 MB |

Herramienta `herramientas/comprobar_fuentes.py`: un `GET` a cada endpoint con validación de esquema mínima; se ejecuta a mano antes de cada release.

---

## 5. Fuera del alcance (explícito)

- Integración con AlecaFrame, Overwolf o cualquier lectura del inventario completo del jugador.
- Lectura de memoria del proceso, inyección de DLL, hooks de DirectX, envío de teclas o clics al juego, macros.
- Uso de credenciales de la cuenta de Warframe o de `api.warframe.com` con sesión del jugador.
- Consolas y móvil (solo PC; el selector de plataforma queda preparado pero no implementado).
- Publicación de órdenes en warframe.market (solo lectura de precios; sin OAuth).
- Guías de builds, rivens, estadísticas de armas, cálculo de daño.
- Traducción del OCR a otros idiomas distintos de español e inglés.
- Sincronización en la nube de objetivos, cuentas de usuario, telemetría.
- Scraping de la wiki (solo enlaces).
- Firma de código y publicación en tiendas (Microsoft Store, Overwolf).
- Soporte a Windows 7/8 y a Linux/Proton.
