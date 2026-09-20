# Cambios

## 0.1.5

- **El boton "Atras" ya funciona**. Antes el historial se borraba al pinchar
  otro resultado de la lista, asi que el boton solo servia dentro de una misma
  ficha. Ahora guarda las ultimas 50 fichas vistas y, al volver, recupera
  tambien la busqueda que las encontro y la deja seleccionada en la lista.
- **Ventana redimensionable**: se arrastra desde cualquier borde o esquina. El
  tamano se guarda por separado para el modo completo y el compacto, asi que
  Ctrl+M devuelve cada uno como lo dejaste. Minimos 760x420 y 420x190. Si
  cambias de monitor o de resolucion y la ventana no cabe, se encoge y se
  recoloca sola.
- **Platino en las recompensas de reliquia**: la etiqueta que sale encima de
  cada recompensa ya no dice solo los ducados, sino tambien lo que vale en
  platino ("Ash Prime Sistemas - 38 platino - 45 ducados"), y la mejor de las
  cuatro sale marcada en dorado.
- **El comparador ya no se queda mudo** si warframe.market no responde: avisa en
  el registro y puntua igual con ducados y rareza en vez de no decir nada.
- **Estado del mundo arreglado**. La API dejo de aceptar el parametro de idioma
  y a veces contesta con un error en vez de con el mundo; Farmadex lo tomaba por
  "no hay fisuras". Ahora distingue las dos cosas, dice el motivo del fallo y
  reintenta solo cada minuto.
- **Tema Orokin por defecto**, y los ajustes se guardan al cambiarlos.
- **Manual de usuario y guia de instalacion** incluidos en el repositorio.

## 0.1.4

- **Comparador de reliquias**: al abrir una fisura, Farmadex lee las cuatro
  recompensas y dice cual vale mas, en menos de 4 segundos (la cuenta atras del
  juego son 15). Manda lo que cubre un objetivo tuyo; luego el valor en platino o
  ducados; la rareza solo desempata. En escuadra usa el precio del vendedor mas
  barato, porque van a salir tres copias mas al mercado. Si no lo sabe, lo dice.
- **Precios de mods y arcanos arreglados**: antes mezclaba las ventas de rango 0
  con las compras de rango maximo, y el Arcano Energizar salia como "se vende por
  8p, te lo compran por 130p". Ahora separa por rango.
- **Precio para casi todo**: las piezas prime no casaban con warframe.market. Las
  que se quedaban sin precio pasan de 161 a 8, y las recompensas de reliquia sin
  precio, de 157 a 4.
- **"Sin ruta conocida" arreglado**: lo que no cae de reliquias (Rhino y
  compania) ya dice donde cae de verdad: "Fossa, Venus - Asesinato - 38,7 %".
- **Modo compacto** (Ctrl+M): 560x250 en vez de 1100x700, para consultar en
  directo sin tapar un tercio de la pantalla.
- **Pestana Mundo rediseñada**, con dos disposiciones a elegir en Ajustes: las
  fisuras terminadas ya no aparecen, lo que caduca en menos de diez minutos sale
  en naranja, y lo que sirve para tus objetivos va arriba y marcado.
- **Baro util**: cuenta atras, su inventario y que cubre un objetivo tuyo.
- **Historial de sesion**: reliquias abiertas, que ha caido y valor del dia, con
  exportacion a un fichero de texto para enseñarlo en OBS.
- **Glosario**: 16 terminos del juego explicados al pasar el raton, sin estorbar
  a quien ya los conoce.
- **Buscar sin resultados** ya no deja pintada la ficha anterior: lo dice y
  sugiere lo mas parecido.
- Regla de ducados contra platino por pieza, con umbral configurable.

## 0.1.3

- **Los recursos ya no salen como piezas de warframe**: la crioptica era un arma
  primaria, "argon" devolvia la mira Argon Scope y el nitain era una pieza de
  Vauban. Eran 152 objetos mal clasificados. Un recurso se reconoce porque
  aparece en tres o mas recetas; una pieza de verdad, nunca.
- **Cinco idiomas**: espanol, ingles, frances, aleman y portugues de Brasil, con
  la terminologia oficial del juego y cambio al vuelo desde Ajustes.
- **Tres temas de color** (Vacio, Orokin y Tenno), tambien al vuelo.
- **Pestana Perfil**: preparada para importar el perfil del jugador (maestria,
  objetos dominados, nodos, intrinsecos y sindicatos). Digital Extremes ha
  cerrado el acceso a esos datos, asi que hoy solo acepta un fichero valido;
  se esta trabajando en leerlos de las propias pantallas del juego.
- **Aguanta los parches del juego**: categorias, eras, ciclos y campos nuevos ya
  no rompen la importacion, y la aplicacion avisa cuando sus datos van por
  detras de la version del juego en vez de ensenarlos como buenos.
- **Funciona con el juego en ventana**, no solo sin bordes. En pantalla completa
  exclusiva lo detecta, lo dice y saca el overlay al segundo monitor si lo hay.
- El mapa pasa de 269 a 504 nodos: Railjack, eventos y los retirados, que DE no
  publica.
- La base de datos baja de 282.766 a 75.223 filas quitando duplicados, y el
  indice se construye en 4 segundos en vez de 12.

## 0.1.2

- **Los resultados salen ordenados por lo que de verdad buscas**: primero la
  coincidencia exacta, luego lo que empieza por lo escrito, y a igualdad lo que
  se farmea antes que aspectos, glifos, sigilos y adornos.
- **Aguanta las erratas**: "rino prime", "seracion" o "exkalibur" encuentran lo
  que toca. La busqueda difusa ya no espera a que la exacta se quede en blanco.
- **Tres temas visuales** elegibles en Ajustes (Vacio, Orokin y Tenno), con
  cambio al vuelo.
- La lista de resultados ensena la imagen del objeto, el nombre grande y su
  categoria; las reliquias y los objetivos pasan a ser tarjetas, con color por
  rareza y por estado de boveda.
- **Bloque "Version" en Ajustes**, siempre visible, con la version instalada y
  un boton para comprobar si hay una mas nueva.
- Arreglado: 33 recursos (Nitain, Neurodos, Celula orokin, Argon...) aparecian
  solo como pieza de la primera warframe que los usaba, en vez de como recurso
  propio. El indice se reconstruye solo al abrir esta version (unos 13 segundos,
  sin descargar nada).
- Un fallo del lector de pantalla ya no saca un dialogo de error: se avisa en la
  barra de estado y el resto sigue funcionando.

## 0.1.1

- Arreglado el lector de pantalla en el ejecutable: faltaban piezas de RapidOCR
  al empaquetar, y el atajo de leer bajo el cursor daba error.
- Las versiones nuevas se detectan desde la carpeta de actualizaciones del
  equipo y se instalan desde Ajustes.

## 0.1.0 — primera versión

### Buscar

- Descarga automática del catálogo de WFCD y de las tablas de drops oficiales de
  Digital Extremes, con barra de progreso y espejo por si una fuente cae.
- De los ~50 MB de traducciones solo se guarda el castellano.
- Índice SQLite con FTS5 sin acentos: busca en español o en inglés, con
  respaldo difuso para las erratas. La búsqueda responde en milisegundos.
- Ficha completa: la pieza, con qué se construye, en qué reliquias cae y con qué
  probabilidad por refinamiento, si están en bóveda, y en qué misiones se
  consiguen esas reliquias, con nodo, planeta y tipo de misión en español
  (nombres oficiales del Public Export de DE).
- Bloque «Por dónde empezar» con la mejor ruta disponible hoy, y filtro para
  ocultar lo que está en bóveda.
- Traducción de las piezas («Systems» → «Sistemas»), que el catálogo no trae.

### Objetivos

- Lista de lo que estás farmeando, con progreso manual y el set completo de un
  prime en un clic.
- Cada objetivo enseña su mejor ruta actual, o avisa de que solo se consigue
  comprándolo si está todo en bóveda.

### Mundo

- Fisuras con filtro por era y por Normal / Camino de Acero / Tormenta del Vacío,
  ciclos, invasiones con sus recompensas, alertas, arbitración, incursión, caza
  de arcontes, Nightwave, Baro con su inventario y la oferta del Camino de Acero.
- Cuenta atrás en vivo, calculada en el equipo: no se pide nada para refrescar el
  reloj. Si se cae la conexión se mantiene lo último conocido, avisando.

### Precios

- Precio en platino de warframe.market en la ficha de cada objeto, priorizando a
  quien está dentro del juego, con caché de 10 minutos y 2 peticiones por segundo.

### Overlay

- Ventana sin marco, translúcida y siempre encima, con `Ctrl+Alt+W`; `Escape` la
  cierra. Icono en la bandeja y pestaña de ajustes con los atajos, la opacidad y
  el estado de los datos.

### Leer la pantalla

- Al abrir una reliquia (detectado en `EE.log`) se leen las recompensas y se pinta
  encima de cada una su precio, sus ducados, si está en bóveda y si te sirve para
  un objetivo. Se puede desactivar.
- `Ctrl+Alt+Q` lee lo que haya bajo el cursor y abre su ficha.
- El casado del OCR aguanta que el juego escriba «Chasis de Ash Prime» donde el
  catálogo dice «Ash Prime Chasis», que el OCR pegue las palabras y que se cuele
  alguna letra cambiada.

### Actualizaciones y empaquetado

- Los datos se comprueban cada 6 horas y se reconstruyen en segundo plano, con
  intercambio del índice al final para no dejarlo a medias.
- Aviso (nunca instalación automática) de versiones nuevas publicadas en GitHub.
- `empaquetado\construir.ps1` genera el ejecutable, el zip portable y el
  instalador, con su SHA-256.
