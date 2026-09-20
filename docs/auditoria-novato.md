# Auditoría de producto: Farmadex con ojos de jugador nuevo

Fecha: 2026-09-20. Versión 0.1.3. Índice real (16.628 objetos). Interfaz arrancada
sin pantalla (`QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=C:/Windows/Fonts`), capturas
con `QWidget.grab()` y lectura de las PNG. Los objetivos de prueba (set de Rhino) que
se añadieron a `usuario.sqlite` se borraron al terminar.

Perfil simulado: MR 2-3, tercera o cuarta misión de la historia, juego en español, no
sabe qué es reliquia, refinamiento, bóveda, MR, rotación, Meso/Neo.

## Búsquedas hechas y lo que vio

| Búsqueda | Resultado | Qué entiende el novato |
|---|---|---|
| `excalibur` | Ficha. "Sindicatos: Conclave · 60000 de reputación · Común · 100%". No sale Ambulas (Plutón) | Cree que Excalibur se compra en un sindicato llamado Conclave. Falso para él. |
| `como consigo rhino` | 0 resultados, **y la ficha anterior (Plano de Excalibur) se queda pintada** | Cree que la respuesta a "cómo consigo Rhino" es "Plano de Excalibur". |
| `rino` | Rhino. Ficha: "Se construye con Plano, Chasis, Neuróptica, Sistemas". Nada más. | No sabe que el Plano se compra en el Mercado por créditos ni que las piezas las suelta el Chacal en Fossa (Venus). Tiene que pinchar pieza a pieza. |
| `chasis de rhino` | "Fossa, Venus - Asesinato · Común · 38.7%" y debajo, duplicado, "Fossa (Assassination), Venus" | Bien, pero duplicado y sin decir que el jefe es el Chacal ni qué nivel tiene. |
| `+ Set completo` de Rhino → Objetivos | Las 4 tarjetas dicen **"Sin ruta conocida: puede venir de una misión de historia o del mercado"** aunque el índice sí tiene Fossa para tres de ellas | La pestaña Objetivos contradice a la de Buscar. Para el novato, Objetivos es inútil. |
| `credits`, `platino`, `endo` | Créditos Escarlata / Plástidos / Vector endoparasitario | Las tres monedas básicas del juego no existen como concepto. |
| `mod de daño`, `arma buena`, `jefe`, `boss`, `cómo subo de rango`, `fisura`, `bóveda`, `maestría` | Ruido o cero | No hay ninguna respuesta a preguntas de concepto; solo a nombres de objeto. |
| `tierra`, `venus`, `mercurio`, `jackal` | Aspectos, glifos, "Marrón Mercurio" | Los planetas y los jefes no son entidades buscables. |
| `serration` | "Sierra" (traducción oficial). Fuentes: Espionaje rotación C 8.6% en Mercurio... | No sabe qué es "rotación C". La fuente real para él (enemigos Grineer normales) está más abajo. |
| `ferrita` | Primeras filas: "Cephalon Capture, Saturno - Conclave · 12.7%" (PvP) | Un recurso de Mercurio/Tierra le manda al PvP de Saturno. |
| `forma` | Bloque "Por dónde empezar: Reliquia Axi A22 · 20.0% en Radiante · Cerberus, Plutón · Intercepción · Rotación B · 14.3%" | Cinco términos desconocidos en una línea (Axi, Radiante, Int/Exc/Imp/Rad, Rotación B, Plutón que no tiene). |
| `neo`, `meso`, `reliquia` | 40 reliquias en orden aleatorio (Neo C7, C8, C9, A16...) | No hay explicación de qué es una reliquia ni de la diferencia entre eras. |
| `ash prime` | Etiquetas "Prime · En bóveda · Sin dominar" | No sabe qué significa "En bóveda" ni "Sin dominar". |

## Pestañas

- **Buscar**: funciona bien como diccionario de nombres. Fallos: ficha zombi con 0
  resultados; padres (Rhino) sin resumen de piezas; el Plano del Mercado no aparece
  como fuente; fuentes duplicadas (mision + otro); Conclave y Railjack se cuelan
  arriba; ninguna etiqueta (rotación, refinamiento, bóveda, Dominado) tiene ayuda
  al pasar el ratón; el filtro "Ocultar reliquias en bóveda" no dice qué es bóveda.
- **Objetivos**: "Sin ruta conocida" en piezas que sí tienen ruta. No dice qué le falta
  para poder jugar ese nodo (planeta sin desbloquear). Contadores manuales -/+.
- **Mundo**: tabla de 36 fisuras con "Lith Beacon Shield Ring, Venus · Volátil ·
  Corpus · Tormenta · 1h 5m". Para MR2: Railjack, Camino de Acero, Fortaleza Kuva,
  Zariman, Duviri, todo mezclado. No hay "solo lo que puedo jugar". Ciclos: "Duviri:
  envidia", "Zariman: Grineer", sin explicar para qué sirve saberlo. Aviso "Datos del
  mundo sin actualizar" ocupando el sitio de un título.
- **Perfil**: botón "Importar perfil (JSON)..." que no puede usar (DE cerró el acceso);
  tabla de maestría por categoría. Para él es una pestaña vacía con un botón que falla.
- **Ajustes**: bien. Aviso largo de "los datos van por detrás del parche" con fechas
  técnicas; el novato no sabe si eso le afecta.

## Lo que asume que sabe

Reliquia, era (Lith/Meso/Neo/Axi), refinamiento (Int/Exc/Imp/Rad), Radiante, bóveda,
rotación A/B/C, Dominado/Sin dominar, MR, Camino de Acero, Tormenta del Vacío, Conclave,
Escaramuza, Requiem, Omnia, Kuva, ducados, Baro. Ninguno se explica en ningún sitio.
