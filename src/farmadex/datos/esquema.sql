-- Indice de datos del juego. Se regenera entero desde los JSON descargados.
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);

CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  unique_name TEXT NOT NULL UNIQUE,
  nombre_en TEXT NOT NULL,
  nombre_es TEXT,
  descripcion_es TEXT,
  categoria TEXT NOT NULL,
  tipo TEXT,
  es_prime INTEGER NOT NULL DEFAULT 0,
  comerciable INTEGER NOT NULL DEFAULT 0,
  vaulted INTEGER,
  vault_fecha TEXT,
  imagen TEXT,
  wiki_url TEXT,
  padre_id INTEGER REFERENCES items(id),
  item_count INTEGER,
  ducados INTEGER,
  market_slug TEXT,
  market_id TEXT,
  -- Cuando salio (releaseDate de WFCD, AAAA-MM-DD) y en que actualizacion ("Update 44.0"):
  -- de ahi sale "lo nuevo" del buscador. Solo lo traen los objetos de verdad, no los adornos.
  fecha_salida TEXT,
  actualizacion TEXT
);
CREATE INDEX IF NOT EXISTS ix_items_categoria ON items(categoria);
CREATE INDEX IF NOT EXISTS ix_items_padre ON items(padre_id);
CREATE INDEX IF NOT EXISTS ix_items_nombre_en ON items(nombre_en);

CREATE TABLE IF NOT EXISTS fuentes (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id),
  tipo TEXT NOT NULL,
  origen_id INTEGER,
  origen_texto TEXT NOT NULL,
  refinamiento TEXT,
  rotacion TEXT,
  etapa TEXT,
  rareza TEXT,
  probabilidad REAL,
  probabilidad_enemigo REAL,
  standing INTEGER,
  datos_extra TEXT
);
-- Compuesto (item, tipo): sin el, "WHERE item_id = ? AND tipo = 'reliquia'" elegia
-- ix_fuentes_origen y recorria las 130.000 fuentes de reliquia en cada ficha.
CREATE INDEX IF NOT EXISTS ix_fuentes_item_tipo ON fuentes(item_id, tipo);
CREATE INDEX IF NOT EXISTS ix_fuentes_origen ON fuentes(tipo, origen_id);

CREATE TABLE IF NOT EXISTS nodos (
  id INTEGER PRIMARY KEY,
  unique_name TEXT UNIQUE,
  nombre_en TEXT NOT NULL,
  nombre_es TEXT,
  planeta_en TEXT NOT NULL,
  planeta_es TEXT,
  mision_en TEXT,
  mision_es TEXT,
  faccion_en TEXT,
  faccion_es TEXT,
  nivel_min INTEGER,
  nivel_max INTEGER,
  clave_drops TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_nodos_clave ON nodos(clave_drops);

CREATE TABLE IF NOT EXISTS glosario (
  dominio TEXT, en TEXT, es TEXT, PRIMARY KEY(dominio, en)
);

-- Glosario de componentes (y la palabra "Blueprint") en los idiomas que WFCD no
-- traduce por si solo: fr, de, pt (ver glosario_fr.json etc). El espanol se queda
-- en 'glosario' tal cual estaba, sin tocar lo que ya funcionaba.
CREATE TABLE IF NOT EXISTS glosario_idiomas (
  dominio TEXT, idioma TEXT, en TEXT, valor TEXT, PRIMARY KEY(dominio, idioma, en)
);

-- Nombre de cada objeto en un idioma que no sea espanol o ingles (fr, de, pt, it, pl).
-- Aparte de nombre_en/nombre_es para no romper nada que ya lea esas dos columnas.
CREATE TABLE IF NOT EXISTS items_nombres (
  item_id INTEGER NOT NULL REFERENCES items(id),
  idioma TEXT NOT NULL,
  nombre TEXT NOT NULL,
  PRIMARY KEY (item_id, idioma)
);
CREATE INDEX IF NOT EXISTS ix_items_nombres_idioma ON items_nombres(idioma);

-- Recetas: que pide cada objeto para fabricarse y cuanto (Magistar: 750 Ferrita, 300 Rubedo...).
-- Aparte de items.padre_id porque los recursos compartidos (Criotica, Rubedo) pierden el
-- padre al pasar a Resources, y la pestana Objetivos los necesita para marcarlos uno a uno.
CREATE TABLE IF NOT EXISTS recetas (
  padre_id INTEGER NOT NULL REFERENCES items(id),
  item_id INTEGER NOT NULL REFERENCES items(id),
  cantidad INTEGER,
  PRIMARY KEY (padre_id, item_id)
);

CREATE TABLE IF NOT EXISTS reliquia_recompensas (
  reliquia_id INTEGER NOT NULL REFERENCES items(id),
  refinamiento TEXT NOT NULL,
  item_id INTEGER NOT NULL REFERENCES items(id),
  rareza TEXT,
  probabilidad REAL,
  PRIMARY KEY (reliquia_id, refinamiento, item_id)
);

-- Lo que la ficha ensena ademas de donde sale (datos/detalles.py): estadisticas de armas,
-- efecto por rango de mods y arcanos, habilidades de warframes y el codigo de canje de los
-- glifos. Un JSON por objeto; no sirve para buscar. Los indices de antes no la tienen y
-- el codigo lo tolera.
CREATE TABLE IF NOT EXISTS detalles (
  item_id INTEGER PRIMARY KEY REFERENCES items(id),
  datos TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS busqueda USING fts5(
  texto,
  item_id UNINDEXED,
  idioma UNINDEXED,
  categoria UNINDEXED,
  tokenize = "unicode61 remove_diacritics 2 tokenchars '-'"
);
