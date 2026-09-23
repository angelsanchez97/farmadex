# Cambios

## 0.2.6

**Pestaña Primes, nueva**
- Marcas las piezas prime que quieres y te dice en que reliquias salen y donde
  farmearlas, ordenado por el tiempo medio hasta tener la pieza en la mano:
  conseguir la reliquia y abrirla en fisuras, todo junto. Eliges el
  refinamiento y si juegas solo o en escuadra de 4 compartiendo reliquia.
- Marcar una pieza aqui es lo mismo que añadirla a Objetivos.
- La ficha de una pieza prime dice por donde empezar: reliquia, mision y tiempo
  total.

**Donde farmear, mas claro**
- Cada fila se rellena segun lo rapido que es conseguir el objeto ahi: cuanto
  mas llena, antes lo tienes.
- Al pasar el raton por un tiempo se ve de donde sale: "~13,5 min por partida
  x ~5 partidas de media = ~70 min".
- Ritmo de juego en Ajustes (rapido, normal, tranquilo): ajusta todos los
  tiempos a como juegas tu.

**Reliquias, mas rapidas y mas exactas**
- Se lee solo la fila de nombres de las tarjetas: de ~250 ms a ~40 ms, tambien
  con el procesador ocupado. En pantallas reales anotadas a mano, los aciertos
  pasan de 29 a 43 de 44 y ya no se inventa ninguna recompensa.
- Si en la escuadra salen dos recompensas iguales, se ven las dos.

**Otros idiomas**
- Los objetos se reconocen tambien con el juego en frances, aleman y portugues
  (y, algo menos, en italiano y polaco), en la pantalla de recompensas y en la
  busqueda. El indice se reconstruye solo la primera vez.

**Guia de uso**
- Un recorrido por la ventana que se abre solo la primera vez, se puede saltar
  cuando quieras y se vuelve a lanzar con el boton "Guia". Si ya tenias
  Farmadex, solo veras un aviso.

**Farmadex y Digital Extremes**
- Nuevo "Acerca de Farmadex" en Ajustes: que hace y que no hace el programa, y
  lo que contesto el soporte de DE sobre programas de terceros.

## 0.2.5

**Reliquias en menos de un segundo**
- Se ha quitado la espera fija de 1,5 s antes de leer la pantalla. En el video
  de un usuario, los nombres de las tarjetas ya se leen en el primer fotograma,
  y el juego avisa de que tiene todas las recompensas 0,4 s despues de abrirse.
  Ahora se lee al momento, y si todavia faltan tarjetas se vuelve a mirar cada
  150 ms en vez de esperar a ciegas.
- "Plano de Chasis de Caliban Prime" se identificaba como "Caliban Prime". En
  castellano el juego pone "Plano" delante del nombre y solo sabiamos quitarlo
  cuando iba detras. Lo mismo pasaba con cualquier pieza de warframe.

**Panel de recompensas**
- Cada tarjeta queda centrada justo debajo de su recompensa.
- Los ducados salen siempre, tambien en la mejor opcion; si no hay dato, lo
  dice.
- Funciona de 1 a 4 recompensas, y con 0 no aparece.

**Estado del mundo**
- Si la API de la comunidad se queda atascada, Farmadex tira de la fuente
  oficial de DE. Hace dos dias se quedo dos horas publicando datos viejos, y
  las fisuras desaparecieron.
- Una fisura con el campo "activa" vacio ya no se da por cerrada: se decide por
  sus fechas.
- Si no hay fisuras que ensenar, se dice por que: tu filtro, datos viejos (y de
  cuando son) o que la consulta fallo.

**Actualizaciones**
- Al actualizarse, se ve la ventana de progreso del instalador, y Farmadex
  avisa antes de cerrarse.

## 0.2.4

- **Si una actualizacion automatica falla, ahora se sabe por que.** El aviso
  dice el motivo, leido del registro del propio instalador. Y si no llego a
  instalarse porque habia otro Farmadex abierto, ya no se da por fallida: se
  guarda y se reintenta al cerrar el ultimo. Antes esa version quedaba
  descartada y habia que instalarla a mano.
- **Registro a prueba de fallos**, para poder diagnosticar lo que reporta la
  gente: cualquier problema del propio registro se apunta aparte en
  `logs
egistro_errores.txt`, la primera linea dice la version y donde se esta
  escribiendo, y avisa si Windows lo esta redirigiendo a otra carpeta.

## 0.2.3

Arreglos de la pantalla de recompensas, a partir del video de un usuario que
tenia AlecaFrame abierto a la vez.

- **Ya no se lee el panel de otro overlay como si fueran recompensas.** Las
  tarjetas se buscan solo en la fila del juego, y nunca salen mas recompensas
  que jugadores hay en la partida.
- **Objetos mal identificados.** "Empuñadura De Quassus Prime" se etiquetaba
  como "Nikana Prime Empuñadura", y con ella su precio. El catalogo llama
  "Mango" a lo que el juego llama "Empuñadura"; ahora se reconocen como lo
  mismo, y si lo leido no contiene ninguna palabra propia del candidato, no se
  casa.
- **Lo que no se identifica se dice.** Sale como "Sin identificar" con el texto
  leido, y nunca lleva la marca de mejor opcion.
- **El precio dice de donde sale**: "1 platino (venta mas barata)". Si no hay
  precio, pone "Sin precio" en vez de parecer que vale 0.
- **Panel de recompensas opcional** (Ajustes > Recompensas de reliquia): una
  tarjeta por recompensa con miniatura, precio, ducados, boveda, si te sirve
  para un objetivo, cuantas tienes, tiempo medio de farmeo y maestria. Por
  defecto siguen las etiquetas pequeñas.

## 0.2.2

**Farmadex se entera solo de lo que tienes**
- Cuando abres Perfil > Equipamiento en el juego, lo lee solo y apunta lo que
  tienes dominado, sin que pulses nada. F9 sigue funcionando.
- Tambien lee el inventario y la fundicion, pero esa parte es experimental y
  viene apagada: los iconos de cantidad se confunden con cifras y preferimos no
  apuntar un numero falso. Se enciende en Ajustes.
- Objetivos y las fichas dicen ahora "tienes 3 de 5" y marcan las piezas que ya
  tienes.
- Al abrir una reliquia en solitario, lo que te toca se suma solo a tus
  objetivos.
- Solo mira la pantalla con Warframe delante, cada segundo y medio, y con una
  comprobacion que cuesta un 3 % de un nucleo; el OCR solo entra cuando la
  pantalla cambia y se queda quieta.

**Reliquias**
- Las recompensas que el juego anota en su registro se usan como fuente
  principal: el veredicto sale en un milisegundo en vez de dos segundos, y no
  hay nombres mal leidos.
- Farmadex apunta en su registro cuanto tarda cada paso al abrir una reliquia,
  para poder ver donde se va el tiempo en cada equipo.
- Si una lectura llega tarde, con la pantalla ya cerrada, ya no pinta etiquetas
  encima de otra cosa: lo anota y espera a la siguiente.
- Los hilos del OCR se ajustan a los nucleos del procesador.

**Otros**
- Opcion "Iniciar con Windows": arranca en la bandeja, sin ventana y sin pedir
  administrador. Apagada por defecto.

## 0.2.1

Segunda revision: el codigo nuevo de la 0.2.0, y el programa usado de
principio a fin como un jugador novato y como uno veterano.

**Actualizacion automatica, mas robusta**
- Con Farmadex abierto dos veces, la actualizacion fallaba y esa version ya no
  se volvia a intentar nunca. Ahora espera a que cierres el ultimo.
- Funciona en carpetas de usuario con acentos o simbolos como "&" o parentesis.
- Si desactivas "Actualizar automaticamente" despues de que se descargue, ya no
  se instala sola al cerrar.

**Datos y fichas**
- La rareza de cada pieza en una reliquia es la real (la del 10 % es la rara),
  igual en la ficha y en la vista compacta.
- Las reliquias en boveda dicen que ya no caen y hay que comprarlas, en vez de
  "puede venir de una mision de historia".
- Los contratos se leen en tu idioma: "Contratos de Cetus - nivel 10-30 -
  etapa 4 de 5".
- Los contratos de evento (Ghoul, Plague Star) y la Archimedea semanal ya no
  aparecen como la forma mas rapida de conseguir algo.
- Ajustes ya no avisa en naranja de que los datos van por detras cuando tienes
  lo ultimo que DE ha publicado: DE puede tardar meses en actualizar sus tablas
  de drops, y eso no es un fallo.

## 0.2.0

**Se actualiza solo**
- Cuando sale una version nueva, Farmadex la descarga en segundo plano,
  comprueba que es la autentica (su huella SHA-256 contra la que publica
  GitHub) y la instala al cerrar el programa, o cuando pulses "Reiniciar y
  actualizar". Se instala en silencio y se vuelve a abrir sola. Nunca en mitad
  de una partida.
- Ajuste "Actualizar automaticamente", activado por defecto. Desactivado, o en
  la version portable, sigue avisando con un enlace como hasta ahora.
- Si la descarga o la instalacion fallan, se sigue con la version actual y el
  aviso dice el motivo.

**Donde farmear, ordenado por lo que de verdad cuesta**
- Las fuentes de cada objeto se ordenan por el tiempo medio estimado hasta
  conseguirlo, no por el porcentaje: un 10 % en una mision de 10 minutos va
  antes que un 20 % en una de 40. Cuenta las rotaciones de las misiones sin
  fin (una recompensa de rotacion C en Supervivencia cuesta 20 minutos, no 5).
- Los jefes de asesinato dicen donde estan (Alad V en Temisto, Jupiter) y
  cuentan como una mision mas. Buscar "Sensores neuronales" ya lleva a Temisto,
  no a un "Raptor 50 %" sin sitio.
- Los recursos de planeta dicen en que planeta caen y que misiones rapidas
  hacer alli.
- Lo que no se puede medir en tiempo (enemigos comunes, sindicatos,
  incursiones, Conclave) lo dice en vez de fingir, y va al final. Los modos de
  Conclave ocupan una sola linea.
- Las duraciones son estimaciones para un jugador medio, y la ficha lo avisa.

## 0.1.9

Revision completa del programa, parte por parte.

**Reliquias**
- Farmadex sabe que reliquia llevas equipada (lo escribe el propio juego en su
  registro unos minutos antes de abrirla) y consulta los precios de sus
  recompensas durante la mision. Al abrirse, la marca de "mejor opcion" sale a
  la vez que las etiquetas, en vez de 1,5 s despues.
- Cuando el juego anota que le ha tocado a un companero, ese precio se pide
  antes incluso de leer la pantalla.

**Busqueda y datos**
- Los nombres ya no muestran etiquetas internas del juego (`<ARCHWING>`,
  `<Shard_red_simple>`), y los fragmentos de Arconte tienen ahora sus fuentes.
- La busqueda entiende "chasis de mesa prime", "plano del rhino" o "wu kong".
- Las piezas de adornos que salen de reliquias (Kavasa Prime) aparecen donde
  toca, y el plano de un recurso va en la misma categoria que el recurso.
- Si un parche trae probabilidades escritas como texto, las fichas ya no se
  rompen.
- El indice cambia de version: la primera vez que abras esta version se
  reconstruye solo.

**Interfaz**
- Si al arrancar no hay conexion, Farmadex sigue funcionando entero con los
  datos anteriores. Antes Objetivos, Mundo, Perfil y la lectura de pantalla se
  quedaban apagados hasta reiniciar.
- El aviso de version nueva ya no tapa el resultado en la vista compacta:
  ocupa una linea y la ventana le hace sitio.
- Al cambiar de idioma o de tema se actualizan tambien los avisos, la linea de
  version y varios paneles que se quedaban con el color o el idioma anterior.
- Mientras escribes, el precio que llega es el de lo que buscas: antes se
  pedian todos los intermedios, uno por tecla, y el bueno llegaba el ultimo.
- Mundo ya no dice "se va en terminado" cuando Baro se ha ido.

**Red, ajustes e instalacion**
- El buscador, el comparador y el indice comparten la conexion con
  warframe.market: la mitad de peticiones y nunca por encima del limite.
- Cuando una web falla, el aviso dice el motivo en claro, y no se insiste en
  errores que no van a cambiar.
- Los ajustes ya no se pueden corromper al guardarse desde varios sitios a la
  vez.
- Si un atajo de teclado global lo tiene otro programa, se avisa con el motivo.
- El instalador incluye siempre el runtime de Visual C++: en un Windows recien
  instalado el programa podia no llegar a abrir.

## 0.1.8

- **El aviso de version nueva ya se ve.** Se comprobaba al arrancar desde la
  0.1.6, pero el aviso iba a la linea de estado del pie, la misma que usan la
  carga de datos y las busquedas: salia y a los dos segundos lo pisaba otro
  mensaje. Ahora sale en el recuadro de avisos, que no se borra solo, se ve
  tambien en modo compacto y lleva un enlace para bajar el instalador.
- **La primera reliquia de la sesion tarda menos.** Pagaba ella sola la carga
  del modelo de OCR (~300 ms), su primera lectura (~500 ms) y la creacion del
  cliente de precios (~220 ms). Ahora todo eso se hace al arrancar el programa,
  cuando no hay nadie esperando: los nombres salen en ~1,9 s en vez de ~2,3 s y
  el veredicto en ~3,5 s en vez de ~3,9 s. Las reliquias siguientes ya iban a
  esa velocidad.

## 0.1.7

- **Los ajustes ya se guardan.** El tema, el idioma, la opacidad, la
  disposicion de Mundo y los atajos volvian a su valor anterior en cuanto
  cerrabas el programa. La causa: la ventana, la pestana de Ajustes y el
  buscador pedian la configuracion cada uno por su cuenta y se quedaban con su
  propia copia; como al guardar se escribe el fichero entero, el ultimo en
  escribir borraba los cambios de los demas. Y el ultimo siempre era la ventana,
  guardando su posicion al cerrar con el tema de antes. Ahora hay una sola
  configuracion compartida.

## 0.1.6

- **El boton "Comprobar ahora" ya comprueba de verdad.** Solo miraba una carpeta
  del propio PC donde se dejan las compilaciones sin publicar; como en un equipo
  normal esa carpeta esta vacia, contestaba siempre "estas en la ultima version"
  aunque hubiera uno nueva en GitHub. Ahora mira las dos cosas, no se queda con
  la respuesta guardada de hace un rato, y contesta pase lo que pase: si no hay
  nada nuevo lo dice, y si la consulta falla dice por que.
- **Se ofrece el instalador, no el zip portable.** GitHub devuelve los ficheros
  por orden alfabetico y el enlace que salia era el del zip.

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
