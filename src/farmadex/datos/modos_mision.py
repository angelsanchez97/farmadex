"""Que se hace en cada tipo de mision y como reparte sus recompensas.

Quien empieza ve "Hydron, Sedna - Defensa · Rotacion C" y no sabe que tiene que
hacer ni cuando cae esa C. Este modulo guarda, por modo, dos frases cortas (que
hacer y como van las recompensas) y, cuando la fila trae rotacion, una linea que
dice cuando llega ESA rotacion en ESE modo. La interfaz lo ensena al pasar el raton.

Fuente: wiki oficial de Warframe (https://wiki.warframe.com), paginas "Mission
Rewards" y la de cada modo (Survival, Defense, Disruption, Spy, Rescue, Void Flood,
The Circuit, Arbitrations...), consultadas el 2026-09-23. Lo que la wiki no deja
claro se dice con prudencia o se deja fuera; nunca se rellena de memoria:
- Relay y Ancient Retribution no tienen texto: el relevo es una zona social y
  "Ancient Retribution" es un texto de relleno que aparece por error en las tablas.
- En Escaramuza (Railjack) algunas tablas separan A, B y C, pero la wiki no dice
  que decide cada una; el texto lo reconoce en vez de inventarlo.
- En Arbitraje y Defensa espejo la wiki se contradice sobre cada cuanto hay premio;
  se explica el orden de rotaciones sin dar el intervalo.
- En el Circuito de Duviri la wiki dice que las etapas no tienen rotaciones A, B, C,
  aunque las tablas de drops traen alguna; no se da linea por rotacion.

Sin porcentajes ni probabilidades: esos cambian y ya salen en la propia fila. Solo
reglas del juego (cada 5 minutos, cada 3 oleadas, la tercera boveda...).

Algunas de estas reglas no coinciden con lo que supone eficiencia.py (Arbitraje va
A, A, B, B, C...); aqui manda la wiki porque es lo que lee el jugador, y la
estimacion de tiempos se revisa aparte. Disrupcion ya tiene alli su propia regla.

Disrupcion, comprobada otra vez en https://wiki.warframe.com/w/Disruption el
2026-09-24 (hace falta salvar al menos un conducto para que haya premio):
    ronda   1 conducto  2   3   4
    1       A           A   A   B
    2       A           A   B   B
    3       A           B   B   C
    4+      B           B   C   C
El texto viejo decia "cuanto mas conductos salvas, mejor", y es falso: para la A
conviene salvar pocos o salir pronto.
"""

from __future__ import annotations

import re

from ..idiomas import es_castellano, glosa, t

# modo (nombre ingles, como en los datos) -> (nombre castellano, nombre ingles para el
# titulo, que hay que hacer, como van las recompensas). Los dos ultimos pasan por t().
# El nombre castellano es el del glosario del indice (glosario_es.json) cuando lo hay.
MODOS: dict[str, tuple[str, str, str, str]] = {
    "Survival": (
        "Supervivencia", "Survival",
        "Aguanta oleadas de enemigos mientras baja el soporte vital; recoge las capsulas "
        "de soporte vital para que no se agote.",
        "Recompensa cada 5 minutos, en ciclos A, A, B, C que se repiten: la C cae en los "
        "minutos 20, 40, 60... Desde el minuto 5 puedes extraer cuando quieras.",
    ),
    "Conjunction Survival": (
        "Supervivencia conjunta", "Conjunction Survival",
        "Supervivencia especial de Lua: aguanta a los enemigos y manten el soporte vital "
        "como en una Supervivencia normal.",
        "Igual que en Supervivencia: recompensa cada 5 minutos, en ciclos A, A, B, C que se "
        "repiten; la C cae en los minutos 20, 40, 60...",
    ),
    "Defense": (
        "Defensa", "Defense",
        "Protege el objetivo de las oleadas de enemigos; si lo destruyen, la mision falla.",
        "Recompensa cada 3 oleadas, en ciclos A, A, B, C que se repiten: la C cae en las "
        "oleadas 12, 24, 36... En cada parada eliges salir o seguir; si sigues y fallas, "
        "pierdes lo acumulado.",
    ),
    "Mirror Defense": (
        "Defensa reflectante", "Mirror Defense",
        "Defiende dos objetivos que se van alternando; pasas de uno a otro por un tunel del Vacio.",
        "Recompensas en ciclos A, A, B, C que se repiten, como en una Defensa. La wiki no "
        "deja claro cada cuanto llegan.",
    ),
    "Mobile Defense": (
        "Defensa móvil", "Mobile Defense",
        "Lleva la masa de datos a cada terminal y defiendela mientras se descarga.",
        "Solo da premio al terminar en algunas versiones (Vacio, Zariman, Archwing); en el "
        "resto te llevas lo que sueltan los enemigos.",
    ),
    "Excavation": (
        "Excavación", "Excavation",
        "Pon en marcha excavadoras con las celulas de energia que sueltan algunos enemigos "
        "y defiendelas hasta que terminen.",
        "Una recompensa por cada excavadora que termina, en ciclos A, A, B, C que se repiten: "
        "la C llega con 4, 8, 12... excavadoras completadas.",
    ),
    "Interception": (
        "Interceptación", "Interception",
        "Captura y manten las cuatro torres (A, B, C y D) para sumar puntos antes que el enemigo.",
        "Una recompensa por ronda, en ciclos A, A, B, C que se repiten: la C es la ronda 4, "
        "8, 12... Al final de cada ronda eliges salir o seguir.",
    ),
    "Disruption": (
        "Interrupción", "Disruption",
        "Usa las llaves que sueltan algunos enemigos para activar los conductos y defiendelos "
        "de los Demolysts; hay cuatro conductos por ronda.",
        "Una recompensa por ronda si salvas al menos un conducto, pero no va en A, A, B, C: la "
        "rotacion depende de la ronda y de cuantos conductos salves. Rondas 1 y 2: A, o B si "
        "salvas los cuatro (en la 2 bastan tres). Ronda 3: A con uno, B con dos o tres, C con "
        "los cuatro. De la 4 en adelante: B con uno o dos, C con tres o cuatro. Salvar mas no "
        "siempre conviene: para la A sal tras la ronda 2 (desde la 4 ya no sale); para la B, "
        "rondas 1 y 2 salvando los cuatro; para la C, sigue desde la ronda 3 salvando tres o "
        "cuatro en cada ronda.",
    ),
    "Defection": (
        "Deserción", "Defection",
        "Escolta a los grupos de desertores Kavor hasta la nave de extraccion; si mueren "
        "demasiados, la mision falla.",
        "Recompensa cada 2 grupos rescatados, en ciclos A, A, B, C que se repiten: la C llega "
        "con 8, 16, 24... grupos.",
    ),
    "Infested Salvage": (
        "Salvamento infestado", "Infested Salvage",
        "Descifra los datos con tres consolas mientras la infestacion las corroe; si caen las "
        "tres, la mision falla.",
        "Una recompensa por cada ronda de descifrado completada, en ciclos A, A, B, C que se "
        "repiten. Tras cada ronda tienes unos segundos para decidir si sales o sigues.",
    ),
    "Sanctuary Onslaught": (
        "Masacre en el Santuario", "Sanctuary Onslaught",
        "La mision de Cefalon Simaris: mata sin parar para que no baje la eficiencia y entra "
        "en el conducto para pasar a la siguiente zona.",
        "Recompensa cada 2 zonas, en ciclos A, A, B, C que se repiten (la C, en las zonas 8, "
        "16, 24...). Si la eficiencia se agota, sales con lo que llevas.",
    ),
    "Alchemy": (
        "Alquimia", "Alchemy",
        "Llena el crisol con el elemento que pide, llevando anforas de elementos basicos, "
        "mientras aguantas a los enemigos.",
        "Una recompensa por cada crisol completado, en ciclos A, A, B, C que se repiten.",
    ),
    "Legacyte Harvest": (
        "Legacyte Harvest", "Legacyte Harvest",
        "Atrae a los Legacytes y capturalos; si se escapa el primero, la mision falla.",
        "Una recompensa por cada captura, en ciclos A, A, B, C que se repiten. Puedes extraer "
        "despues de la primera captura.",
    ),
    "Arbitration": (
        "Arbitraje", "Arbitration",
        "Un modo normal con enemigos mas duros y sin segunda oportunidad: si caes, no puedes "
        "levantarte.",
        "Recompensa al final de cada rotacion, en orden A, A, B, B y despues C en todas las "
        "siguientes; cada rotacion da ademas Esencia Vitus. Si sales a mitad no te llevas "
        "nada, pero si fallas conservas las rotaciones completadas.",
    ),
    "Spy": (
        "Espionaje", "Spy",
        "Infiltrate y hackea las tres bovedas de datos; si fallas una, esa no da premio.",
        "La rotacion depende de cuantas bovedas saques con exito, en cualquier orden: la "
        "primera da A, la segunda B y la tercera C. Hay que intentar las tres antes de extraer.",
    ),
    "Rescue": (
        "Rescate", "Rescue",
        "Encuentra al rehen, liberalo y llevalo vivo a la extraccion.",
        "Un premio al terminar, y su rotacion depende de como lo hagas: A si salta la alarma, "
        "B si lo rescatas sin alarma o matando a todos los carceleros, y C si haces las dos cosas.",
    ),
    "Sabotage": (
        "Sabotaje", "Sabotage",
        "Llega al objetivo (un reactor, una nave...), inutilizalo y ve a la extraccion.",
        "Si el nodo tiene escondites ocultos, cada uno que encuentres da un premio: el primero "
        "A, el segundo B y el tercero C.",
    ),
    "Caches": (
        "Sabotaje con escondites", "Sabotage",
        "Un sabotaje con escondites ocultos por el mapa: ademas de cumplir el objetivo, "
        "buscalos antes de extraer.",
        "Cada escondite encontrado da un premio: el primero A, el segundo B y el tercero C. "
        "Para la C hay que encontrar los tres.",
    ),
    "Capture": (
        "Captura", "Capture",
        "Persigue al objetivo, derribalo antes de que escape y capturalo.",
        "Un solo premio al terminar la mision.",
    ),
    "Exterminate": (
        "Exterminio", "Exterminate",
        "Mata a todos los enemigos que marca el contador y ve a la extraccion.",
        "Un solo premio al terminar, en las versiones que lo tienen (Vacio, Archwing...); en "
        "muchos nodos normales solo das creditos.",
    ),
    "Assassination": (
        "Asesinato", "Assassination",
        "Encuentra y mata al jefe de la mision.",
        "Al morir, el jefe suelta un objeto de su tabla (a menudo piezas de warframe); cada "
        "partida es un intento.",
    ),
    "Hijack": (
        "Usurpación", "Hijack",
        "Escolta el vehiculo por su ruta, recargandolo con tus escudos.",
        "La version normal no da premio especial al terminar.",
    ),
    "Assault": (
        "Asalto", "Assault",
        "Entra en la Fortaleza Kuva y destruye el arma Navar.",
        "No da premios de mision: solo afinidad y creditos.",
    ),
    "Arena": (
        "Arena", "Arena",
        "Combate en la arena de Kela De Thaym (Rathuum): llega a 25 muertes antes que sus verdugos.",
        "Un solo premio al terminar la partida.",
    ),
    "Rush": (
        "Persecución", "Rush",
        "Con Archwing, destruye los tres transportes Corpus antes de que escapen.",
        "El premio depende de cuantos transportes destruyas: uno da A, dos dan B y los tres dan C.",
    ),
    "Pursuit": (
        "Estampida", "Pursuit",
        "Con Archwing, persigue una nave Grineer, inutiliza su motor y sus generadores de "
        "escudo y defiende tu nave.",
        "Un solo premio al terminar la mision.",
    ),
    "Skirmish": (
        "Escaramuza", "Skirmish",
        "Mision de Railjack: destruye los cazas y las naves de tripulacion que pide el "
        "objetivo; a veces hay un objetivo extra.",
        "Un premio al completar todos los objetivos. En algunos nodos las tablas separan "
        "A, B y C, pero la wiki no explica que decide cada una.",
    ),
    "Volatile": (
        "Volátil", "Volatile",
        "Mision de Railjack: aborda una nave Corpus, sabotea su reactor y destruyela desde "
        "el Railjack.",
        "Un premio al completar todos los objetivos.",
    ),
    "Orphix": (
        "Orphix", "Orphix",
        "Destruye los Orphix (primero sus resonadores, con Necramech) antes de que el control "
        "Sentient llegue al maximo.",
        "Recompensa cada 3 Orphix destruidos, en ciclos A, A, B, C que se repiten; tras cada "
        "tanda puedes salir o seguir.",
    ),
    "Void Storm": (
        "Tormenta del Vacío", "Void Storm",
        "Fisura del Vacio en Railjack: reune reactivo matando enemigos corrompidos para abrir "
        "tu reliquia.",
        "Al terminar recibes la pieza de tu reliquia y, ademas, un premio de la tabla de la "
        "Tormenta del Vacio.",
    ),
    "Void Flood": (
        "Inundación del Vacío", "Void Flood",
        "Mision del Zariman: sella las grietas del Vacio llevandoles Vitoplast mientras "
        "aguantas a los enemigos.",
        "Recompensa cada 3 grietas selladas (con el Thrax derrotado), en ciclos A, A, B, C "
        "que se repiten; tras cada una eliges salir o seguir.",
    ),
    "Void Cascade": (
        "Cascada del Vacío", "Void Cascade",
        "Mision del Zariman: purga los Exolizadores de la infestacion del Vacio antes de que "
        "se llene el medidor de cascada, o la mision falla.",
        "Recompensa cada 4 Exolizadores purgados, en ciclos A, A, B, C que se repiten; tras "
        "cada una puedes salir o seguir.",
    ),
    "Void Armageddon": (
        "Armagedón del Vacío", "Void Armageddon",
        "Mision del Zariman: defiende los dos Exodampers, que se alternan, y protege la "
        "reliquia del Angel del Vacio.",
        "Recompensa cada 3 oleadas superadas (con el Angel derrotado), en ciclos A, A, B, C "
        "que se repiten; tras cada una eliges salir o seguir.",
    ),
    "The Circuit": (
        "Circuito", "The Circuit",
        "Modo sin fin de Duviri: encadena etapas de tipos al azar con un warframe y unas "
        "armas que eliges de un surtido al azar.",
        "Cada etapa superada da un premio y suma progreso; al llegar a ciertos niveles hay "
        "premios que solo se cobran una vez por semana. Puedes salir tras cualquier etapa.",
    ),
    # Las tablas del Circuito por nivel ("Endless: Tier N") vienen como modo Normal/Hard.
    "Normal": (
        "Circuito", "The Circuit",
        "Encadena etapas en el Circuito de Duviri para subir de nivel.",
        "Premios por nivel alcanzado en el Circuito: cada nivel se cobra una vez por semana "
        "(se reinicia el lunes a las 0:00 UTC) y, pasado el ultimo, los premios se repiten.",
    ),
    "Hard": (
        "Circuito (Camino de Acero)", "The Circuit (Steel Path)",
        "Encadena etapas en el Circuito de Duviri para subir de nivel.",
        "Premios por nivel alcanzado en el Circuito: cada nivel se cobra una vez por semana "
        "(se reinicia el lunes a las 0:00 UTC) y, pasado el ultimo, los premios se repiten.",
    ),
    "The Perita Rebellion": (
        "The Perita Rebellion", "The Perita Rebellion",
        "Cumple ordenes al azar durante 12 minutos y despues derrota al jefe que elijas.",
        "Cada 3 ordenes cumplidas dan un premio de la A; cada orden, uno de la B (segun el "
        "jefe elegido); y terminar la mision da uno de la C.",
    ),
    "Follie's Hunt": (
        "Follie's Hunt", "Follie's Hunt",
        "Lleva pintura a los tres lienzos mientras te persiguen los clones de Follie.",
        "Al terminar recibes un premio al azar de la A y uno asegurado de la B; la C solo se "
        "daba durante el evento Operacion: Atramentum.",
    ),
    "Netracells": (
        "Netraceldas", "Netracells",
        "Encuentra la boveda y baja su seguridad matando enemigos dentro de la zona marcada.",
        "Solo da premio las 5 primeras veces de cada semana, gastando un pulso de busqueda; "
        "sin pulsos se puede jugar, pero sin premio.",
    ),
    "Ascension": (
        "Ascensión", "Ascension",
        "Defiende el recolector y despues la capsula de extraccion mientras sube.",
        "Un premio al terminar la mision.",
    ),
    "Shrine Defense": (
        "Defensa del santuario", "Shrine Defense",
        "Entrega ofrendas en el santuario mientras defiendes las casas Ostron y, al final, "
        "derrota al Oni infestado.",
        "Premio al terminar la mision; no hay recompensas por oleada.",
    ),
    "Conclave": (
        "Cónclave", "Conclave",
        "Partidas contra otros jugadores (PvP).",
        "Se gana reputacion de Conclave para la tienda de Teshin; ademas, cada partida puede "
        "soltar algo de su tabla.",
    ),
}

# Variantes del mismo modo tal como llegan de las distintas fuentes de datos.
# Nombres que Farmadex ensenaba antes y no son los del juego en castellano: se siguen
# encontrando al buscarlos ("disrupcion" lleva a Interrupcion), pero ya no se ensenan.
# Los nombres de arriba son los oficiales, de los textos del juego que publica WFCD
# (warframe-worldstate-data, data/es/missionTypes.json y solNodes.json), contrastados con
# la wiki en castellano el 2026-09-26.
NOMBRES_ANTERIORES: dict[str, tuple[str, ...]] = {
    "Disruption": ("Disrupcion",),
    "Interception": ("Intercepcion",),
    "Hijack": ("Secuestro",),
    "Infested Salvage": ("Rescate infestado",),
    "Mirror Defense": ("Defensa espejo",),
    "Sanctuary Onslaught": ("Embestida del Santuario",),
    "Conjunction Survival": ("Supervivencia de conjuncion",),
    "Rush": ("Carrera",),
}

ALIAS = {
    "Extermination": "Exterminate",
    "Arbitrations": "Arbitration",
    "Elite Sanctuary Onslaught": "Sanctuary Onslaught",
    "Orphix Venom": "Orphix",
    "Rathuum": "Arena",
}

# Modos sin fin A, A, B, C: (unidad, cuantas unidades hay por rotacion). De ahi sale la
# lista de la linea por rotacion ("la C cae en los minutos 20, 40, 60...").
AABC: dict[str, tuple[str, int]] = {
    "Survival": ("minuto", 5),
    "Conjunction Survival": ("minuto", 5),
    "Defense": ("oleada", 3),
    "Void Armageddon": ("oleada", 3),
    "Interception": ("ronda", 1),
    "Infested Salvage": ("ronda", 1),
    "Sanctuary Onslaught": ("zona", 2),
    "Excavation": ("excavadora", 1),
    "Alchemy": ("crisol", 1),
    "Legacyte Harvest": ("captura", 1),
    "Defection": ("grupo", 2),
    "Void Flood": ("grieta", 3),
    "Void Cascade": ("exolizador", 4),
    "Orphix": ("orphix", 3),
}
# Frase por unidad; {rot} es la letra y {lista}, "20, 40, 60...".
UNIDADES = {
    "minuto": "Aqui la rotacion {rot} es la recompensa de los minutos {lista}",
    "oleada": "Aqui la rotacion {rot} es la recompensa de las oleadas {lista}",
    "ronda": "Aqui la rotacion {rot} es la recompensa de las rondas {lista}",
    "zona": "Aqui la rotacion {rot} es la recompensa de las zonas {lista}",
    "excavadora": "Aqui la rotacion {rot} llega con {lista} excavadoras completadas",
    "crisol": "Aqui la rotacion {rot} llega con {lista} crisoles completados",
    "captura": "Aqui la rotacion {rot} llega con {lista} capturas",
    "grupo": "Aqui la rotacion {rot} llega con {lista} grupos de desertores rescatados",
    "grieta": "Aqui la rotacion {rot} llega con {lista} grietas selladas",
    "exolizador": "Aqui la rotacion {rot} llega con {lista} Exolizadores purgados",
    "orphix": "Aqui la rotacion {rot} llega con {lista} Orphix destruidos",
}
# En que rotaciones del ciclo de cuatro cae cada letra (1.a y 2.a son A, 3.a B, 4.a C).
_POSICIONES_AABC = {"A": (1, 2, 5, 6), "B": (3, 7, 11), "C": (4, 8, 12)}

# Modos que no van en A, A, B, C: una linea escrita a mano por rotacion.
ROTACIONES: dict[str, dict[str, str]] = {
    "Spy": {
        "A": "Aqui la rotacion A es la primera boveda que saques con exito.",
        "B": "Aqui la rotacion B es la segunda boveda que saques con exito.",
        "C": "Aqui la rotacion C es la tercera boveda: hay que sacar las tres.",
    },
    "Caches": {
        "A": "Aqui la rotacion A es el primer escondite que encuentres.",
        "B": "Aqui la rotacion B es el segundo escondite que encuentres.",
        "C": "Aqui la rotacion C es el tercer escondite: hay que encontrar los tres.",
    },
    "Rescue": {
        "A": "Aqui la rotacion A es rescatar al rehen con la alarma sonando.",
        "B": "Aqui la rotacion B es rescatarlo sin alarma, o matando a todos los carceleros.",
        "C": "Aqui la rotacion C es rescatarlo sin alarma y ademas matando a todos los carceleros.",
    },
    "Rush": {
        "A": "Aqui la rotacion A es destruir un transporte.",
        "B": "Aqui la rotacion B es destruir dos transportes.",
        "C": "Aqui la rotacion C es destruir los tres transportes.",
    },
    "Disruption": {
        "A": "Aqui la rotacion A sale en las primeras rondas salvando pocos conductos: ronda 1 "
             "con hasta tres, ronda 2 con uno o dos, ronda 3 con uno. Si buscas algo de la A, "
             "sal tras la ronda 2: desde la ronda 4 ya no sale.",
        "B": "Aqui la rotacion B sale en la ronda 1 con los cuatro conductos, en la 2 con tres "
             "o cuatro, en la 3 con dos o tres, y de la 4 en adelante con uno o dos. Lo mas "
             "rapido: rondas 1 y 2 salvando los cuatro.",
        "C": "Aqui la rotacion C sale en la ronda 3 si salvas los cuatro conductos, y de la "
             "ronda 4 en adelante si salvas tres o cuatro: sigue salvandolos en cada ronda.",
    },
    "Arbitration": {
        "A": "Aqui la rotacion A son la primera y la segunda rotacion.",
        "B": "Aqui la rotacion B son la tercera y la cuarta rotacion.",
        "C": "Aqui la rotacion C es de la quinta rotacion en adelante: todas son C.",
    },
    "The Perita Rebellion": {
        "A": "Aqui la rotacion A llega cada 3 ordenes cumplidas.",
        "B": "Aqui la rotacion B llega con cada orden cumplida y depende del jefe elegido.",
        "C": "Aqui la rotacion C es terminar la mision.",
    },
    "Follie's Hunt": {
        "A": "Aqui la rotacion A es el premio al azar de cada partida completada.",
        "B": "Aqui la rotacion B es el premio asegurado de cada partida completada.",
        "C": "Aqui la rotacion C solo se daba durante el evento Operacion: Atramentum.",
    },
}

# Disrupcion: letra de cada ronda segun los conductos salvados (1, 2, 3 y 4), la misma
# tabla del principio del modulo. La ficha de mision la pinta tal cual.
TABLA_DISRUPCION = (
    ("1", ("A", "A", "A", "B")),
    ("2", ("A", "A", "B", "B")),
    ("3", ("A", "B", "B", "C")),
    ("4+", ("B", "B", "C", "C")),
)

# Forma corta de cuando cae cada letra, para ponerla a la vista junto a "Rotacion C"
# sin pasar el raton: "Rotacion C (min 20)". Por unidad de los modos A, A, B, C, la
# plantilla con una posicion (B y C: la primera vez que salen) y con dos (A: las dos
# primeras rotaciones del ciclo). Cortas a proposito; la frase larga sigue en el tooltip.
CORTAS_UNIDAD = {
    "minuto": ("min {n}", "min {n} y {m}"),
    "oleada": ("oleada {n}", "oleadas {n} y {m}"),
    "ronda": ("{n}a ronda", "{n}a y {m}a ronda"),
    "zona": ("zona {n}", "zonas {n} y {m}"),
    "excavadora": ("{n}a excavadora", "{n}a y {m}a excavadora"),
    "crisol": ("crisol {n}", "crisoles {n} y {m}"),
    "captura": ("captura {n}", "capturas {n} y {m}"),
    "grupo": ("{n} grupos", "{n} y {m} grupos"),
    "grieta": ("{n} grietas", "{n} y {m} grietas"),
    "exolizador": ("{n} Exolizadores", "{n} y {m} Exolizadores"),
    "orphix": ("{n} Orphix", "{n} y {m} Orphix"),
}
# Modos que no van en A, A, B, C: la forma corta escrita a mano, de las mismas reglas
# que ROTACIONES. Los modos sin regla clara (Escaramuza, Defensa espejo, el Circuito)
# no estan: mejor no poner nada que inventar.
CORTAS: dict[str, dict[str, str]] = {
    "Spy": {"A": "1a boveda", "B": "2a boveda", "C": "3a boveda"},
    "Caches": {"A": "1 escondite", "B": "2 escondites", "C": "3 escondites"},
    "Rescue": {"A": "con alarma", "B": "sin alarma o carceleros muertos",
               "C": "sin alarma y carceleros muertos"},
    "Rush": {"A": "1 transporte", "B": "2 transportes", "C": "3 transportes"},
    "Disruption": {"A": "rondas 1-2 con 1-2 conductos", "B": "rondas 1-2 con 4 conductos",
                   "C": "ronda 3+ con 4 conductos"},
    "Arbitration": {"A": "rotaciones 1 y 2", "B": "rotaciones 3 y 4", "C": "de la 5a en adelante"},
    "The Perita Rebellion": {"A": "cada 3 ordenes", "B": "cada orden", "C": "al terminar"},
    "Follie's Hunt": {"A": "premio al azar", "B": "premio asegurado", "C": "solo en evento"},
}
_PRIMERAS_AABC = {"A": (1, 2), "B": (3,), "C": (4,)}

# Recompensas especiales (transitorias) que son un modo de los de arriba.
_ORIGENES = ((re.compile(r"^Arbitrations?\b", re.I), "Arbitration"),
             (re.compile(r"^Void Storm\b", re.I), "Void Storm"))


def normalizar(modo_en: str | None) -> str:
    """El nombre del modo tal como esta en MODOS; vacio si no se conoce."""
    modo = (modo_en or "").strip()
    modo = ALIAS.get(modo, modo)
    return modo if modo in MODOS else ""


def modo_de_origen(origen_texto: str | None) -> str:
    """Modo de una recompensa sin nodo ('Arbitrations', 'Void Storm (Earth)'); vacio si no."""
    for patron, modo in _ORIGENES:
        if patron.match(origen_texto or ""):
            return modo
    return ""


def nombre(modo_en: str | None) -> str:
    """Nombre del modo en el idioma de la interfaz (castellano, o el ingles del juego)."""
    modo = normalizar(modo_en)
    if not modo:
        return ""
    es, en = MODOS[modo][:2]
    if not es_castellano():
        # Los catalogos de otros idiomas tienen las claves sin tildes ("Tormenta del Vacio").
        llana = _sin_tildes(es)
        traducido = t(llana)
        if traducido != llana:
            return traducido
    return glosa(es, en)


def _sin_tildes(texto: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def linea_rotacion(modo_en: str | None, rotacion: str | None) -> str:
    """Cuando llega esa rotacion en ese modo, ya traducido; vacio si no se sabe."""
    modo, letra = normalizar(modo_en), (rotacion or "").strip().upper()
    if not modo or letra not in _POSICIONES_AABC:
        return ""
    if modo in ROTACIONES:
        return t(ROTACIONES[modo][letra])
    if modo in AABC:
        unidad, cada = AABC[modo]
        lista = ", ".join(str(n * cada) for n in _POSICIONES_AABC[letra]) + "..."
        return t(UNIDADES[unidad], rot=letra, lista=lista)
    return ""


def rotacion_corta(modo_en: str | None, rotacion: str | None) -> str:
    """Cuando cae esa letra en ese modo, en corto y traducido ('min 20', '3a boveda').

    Vacio si el modo no se conoce o no tiene una regla clara para esa letra.
    """
    modo, letra = normalizar(modo_en), (rotacion or "").strip().upper()
    if not modo or letra not in _PRIMERAS_AABC:
        return ""
    if modo in CORTAS:
        return t(CORTAS[modo][letra])
    if modo in AABC:
        unidad, cada = AABC[modo]
        una, dos = CORTAS_UNIDAD[unidad]
        posiciones = [n * cada for n in _PRIMERAS_AABC[letra]]
        if len(posiciones) == 1:
            return t(una, n=posiciones[0])
        return t(dos, n=posiciones[0], m=posiciones[1])
    return ""


def rotaciones_del_modo(modo_en: str | None) -> list[str]:
    """Las letras que tienen regla en ese modo (las que la ficha de mision explica)."""
    modo = normalizar(modo_en)
    if modo in ROTACIONES or modo in AABC:
        return ["A", "B", "C"]
    return []


def explicacion(modo_en: str | None, rotacion: str | None = None) -> str:
    """Texto del tooltip del tipo de mision: titulo, que hacer, recompensas y rotacion.

    Una linea por salto de linea (la primera es el titulo). Vacio si el modo no se conoce:
    la interfaz entonces no pone tooltip en vez de uno que no dice nada.
    """
    modo = normalizar(modo_en)
    if not modo:
        return ""
    _, _, que, recompensas = MODOS[modo]
    lineas = [
        nombre(modo),
        t("Que hacer: {detalle}", detalle=t(que)),
        t("Recompensas: {detalle}", detalle=t(recompensas)),
    ]
    especifica = linea_rotacion(modo, rotacion)
    if especifica:
        lineas.append(especifica)
    return "\n".join(lineas)


def explicacion_rotacion(modo_en: str | None, rotacion: str | None) -> str:
    """Tooltip de la rotacion de una fila: como van los premios en ese modo y cuando cae esa.

    Vacio si el modo no se conoce, y la interfaz ensena la explicacion generica.
    """
    modo = normalizar(modo_en)
    if not modo:
        return ""
    lineas = [t("En {modo}: {detalle}", modo=nombre(modo), detalle=t(MODOS[modo][3]))]
    especifica = linea_rotacion(modo, rotacion)
    if especifica:
        lineas.append(especifica)
    return "\n".join(lineas)


def textos() -> list[str]:
    """Todo lo que este modulo pasa por t() desde constantes (para comprobar los catalogos)."""
    salida = [texto for _, _, que, rec in MODOS.values() for texto in (que, rec)]
    salida += list(UNIDADES.values())
    salida += [texto for letras in ROTACIONES.values() for texto in letras.values()]
    salida += [texto for par in CORTAS_UNIDAD.values() for texto in par]
    salida += [texto for letras in CORTAS.values() for texto in letras.values()]
    return salida
