"""Avisos de Windows para lo que pasa en el mundo: el usuario elige que le interesa.

La pestana Mundo es pasiva: para enterarse de una fisura de Cascada o de que ha
llegado Baro habia que abrirla. Aqui se decide, con el mismo `Mundo` que ya se
pinta, que merece un aviso segun lo que el usuario ha marcado. Todo nace apagado:
un aviso que nadie ha pedido es ruido y acaba con el usuario quitandolos todos.

Cada aviso lleva una clave unica (la fisura concreta, la visita de Baro de esa
fecha...) y el `Avisador` recuerda las ya enviadas hasta que caducan, asi que la
misma fisura no avisa dos veces aunque el estado del mundo se pida cada minuto, ni
al volver a abrir Farmadex.

Referencia de que avisan otras herramientas: browse.wf/live (Baro, alertas nuevas,
incursion y arcontes nuevos, reinicio semanal de vendedores, noche en Cetus) y los
bots de Discord de fisuras (por era, tipo de mision y Camino de Acero).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..idiomas import glosa, t

CLAVE_CONFIG = "avisos_mundo"
CLAVE_ENVIADOS = "avisos_mundo_enviados"

# Tipos de mision de las fisuras: clave de la API (ingles) -> nombre en la interfaz.
TIPOS_FISURA = (
    ("Void Cascade", "Cascada del Vacío"),
    ("Void Flood", "Inundación del Vacío"),
    ("Void Armageddon", "Armagedón del Vacío"),
    ("Capture", "Captura"),
    ("Exterminate", "Exterminio"),
    ("Rescue", "Rescate"),
    ("Sabotage", "Sabotaje"),
    ("Spy", "Espionaje"),
    ("Hijack", "Usurpación"),
    ("Assassination", "Asesinato"),
    ("Mobile Defense", "Defensa móvil"),
    ("Disruption", "Interrupción"),
    ("Excavation", "Excavación"),
    ("Survival", "Supervivencia"),
    ("Defense", "Defensa"),
    ("Interception", "Interceptación"),
    ("Alchemy", "Alquimia"),
    ("Infested Salvage", "Salvamento infestado"),
)
# La API no siempre escribe igual el mismo tipo.
_ALIAS_MISION = {"extermination": "exterminate"}
ERAS_AVISO = ("Lith", "Meso", "Neo", "Axi", "Requiem", "Omnia")
TIPOS_ARBITRAJE = (
    ("Defense", "Defensa"),
    ("Survival", "Supervivencia"),
    ("Excavation", "Excavación"),
    ("Interception", "Interceptación"),
    ("Disruption", "Interrupción"),
    ("Mobile Defense", "Defensa móvil"),
    ("Exterminate", "Exterminio"),
    ("Capture", "Captura"),
    ("Rescue", "Rescate"),
    ("Sabotage", "Sabotaje"),
    ("Spy", "Espionaje"),
    ("Alchemy", "Alquimia"),
    ("Infested Salvage", "Salvamento infestado"),
)
DIFICULTADES = (
    ("cualquiera", "Normal o Camino de Acero"),
    ("normal", "Solo normales"),
    ("acero", "Solo Camino de Acero"),
)

# La recompensa rotatoria de Teshin (Camino de Acero), en el orden del juego. Es la
# misma cuenta que usa browse.wf/live: una semana por puesto desde el lunes 10/02/2014
# (con un puesto de desfase respecto a esa fecha, comprobado contra warframestat).
ROTACION_TESHIN = (
    "Umbra Forma Blueprint", "50,000 Kuva", "Kitgun Riven Mod", "3x Forma",
    "Zaw Riven Mod", "30,000 Endo", "Rifle Riven Mod", "Shotgun Riven Mod",
)
_EPOCA_SEMANAS = datetime(2014, 2, 10, tzinfo=timezone.utc)
_DESFASE_TESHIN = -1
NOMBRES_TESHIN = {
    "Umbra Forma Blueprint": "Plano de Forma Umbra",
    "50,000 Kuva": "50.000 de Kuva",
    "Kitgun Riven Mod": "Mod Agrietado de kitgun",
    "3x Forma": "3 Formas",
    "Zaw Riven Mod": "Mod Agrietado de zaw",
    "30,000 Endo": "30.000 de Endo",
    "Rifle Riven Mod": "Mod Agrietado de fusil",
    "Shotgun Riven Mod": "Mod Agrietado de escopeta",
}

# Lo que se guarda en la configuracion. Todo apagado.
POR_DEFECTO: dict = {
    "fisuras": False,
    "fisuras_tipos": [],        # claves de TIPOS_FISURA; vacio = no avisa (evita el aluvion)
    "fisuras_eras": [],         # vacio = cualquier era
    "fisuras_dificultad": "cualquiera",
    "fisuras_solo_facciones": False,  # respetar las facciones preferidas de la pestana
    "baro": False,
    "baro_objetivo": False,
    "teshin_kuva": False,
    "teshin_umbra": False,
    "teshin_cambio": False,
    "palladino": False,
    "arbitraje": False,
    "arbitraje_tipos": [],      # vacio = cualquiera
    "invasiones": False,
    "invasiones_palabras": "Orokin, Forma, Exilus",
    "alertas": False,
    "incursion": False,
    "arcontes": False,
    "noche_cetus": False,
}

# Cuantos avisos se juntan como mucho en uno: el resto se resume con "y N mas".
MAX_LINEAS = 4


@dataclass
class Aviso:
    clave: str
    texto: str
    # Hasta cuando hay que recordarlo para no repetirlo (su fin, o una semana).
    caduca: datetime


def normalizar(prefs) -> dict:
    """Las preferencias guardadas, completas y con los tipos correctos."""
    salida = dict(POR_DEFECTO)
    if isinstance(prefs, dict):
        for clave, defecto in POR_DEFECTO.items():
            valor = prefs.get(clave, defecto)
            if isinstance(defecto, bool):
                salida[clave] = bool(valor)
            elif isinstance(defecto, list):
                salida[clave] = [str(x) for x in valor] if isinstance(valor, (list, tuple)) else []
            else:
                salida[clave] = str(valor) if valor is not None else defecto
    if salida["fisuras_dificultad"] not in {c for c, _ in DIFICULTADES}:
        salida["fisuras_dificultad"] = "cualquiera"
    return salida


def alguno_activo(prefs: dict) -> bool:
    return any(v is True for v in normalizar(prefs).values())


def _plano(texto: str) -> str:
    texto = "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


def clave_mision(mision: str) -> str:
    plano = _plano(mision)
    return _ALIAS_MISION.get(plano, plano)


def semana(ahora: datetime) -> int:
    return int((ahora - _EPOCA_SEMANAS).total_seconds() // (7 * 86400))


def inicio_semana(ahora: datetime) -> datetime:
    return _EPOCA_SEMANAS + timedelta(weeks=semana(ahora))


def teshin_de_la_semana(ahora: datetime) -> str:
    # Calibrado con warframestat: la semana del lunes 14/09/2026 tocaba Forma Umbra.
    return ROTACION_TESHIN[(semana(ahora) + _DESFASE_TESHIN) % len(ROTACION_TESHIN)]


def recompensa_teshin(mundo, ahora: datetime) -> tuple[str, datetime]:
    """(nombre en ingles, fin) de lo que ofrece Teshin esta semana.

    De la API si lo trae; si no (el respaldo de DE no lo trae), de la rotacion fija.
    """
    for r in getattr(mundo, "acero", None) or []:
        if r.texto:
            return r.texto, r.expira or inicio_semana(ahora) + timedelta(weeks=1)
    return teshin_de_la_semana(ahora), inicio_semana(ahora) + timedelta(weeks=1)


def nombre_teshin(nombre_en: str) -> str:
    return t(NOMBRES_TESHIN.get(nombre_en, nombre_en))


def palabras(texto: str) -> list[str]:
    return [p for p in (_plano(x) for x in (texto or "").replace(";", ",").split(",")) if p]


def _iso(momento: datetime | None) -> str:
    return momento.isoformat(timespec="minutes") if momento else "?"


def _nombre_mision(clave_api: str, traducida: str) -> str:
    for clave, texto in TIPOS_FISURA:
        if clave_mision(clave) == clave_mision(clave_api):
            # Nombre del juego: en castellano el nuestro; en otro idioma, el del catalogo o el ingles.
            return glosa(texto, clave)
    return traducida or clave_api


def calcular(mundo, prefs, ahora: datetime | None = None, facciones: set[str] | None = None,
             objetivos_baro: bool = True) -> list[Aviso]:
    """Todos los avisos que el mundo de ahora merece segun `prefs` (sin quitar repetidos).

    `facciones`: las preferidas de la pestana (claves en minusculas); solo cuentan si el
    usuario lo pide en `fisuras_solo_facciones`.
    """
    prefs = normalizar(prefs)
    ahora = ahora or datetime.now(timezone.utc)
    avisos: list[Aviso] = []
    semana_despues = ahora + timedelta(days=7)

    def vigente(expira) -> bool:
        return expira is None or expira > ahora

    if prefs["fisuras"] and prefs["fisuras_tipos"]:
        tipos = {clave_mision(x) for x in prefs["fisuras_tipos"]}
        eras = set(prefs["fisuras_eras"])
        dificultad = prefs["fisuras_dificultad"]
        for f in getattr(mundo, "fisuras", []):
            if not vigente(f.expira) or getattr(f, "tormenta", False):
                continue
            if clave_mision(f.modo or f.mision) not in tipos:
                continue
            if eras and f.era not in eras:
                continue
            if dificultad == "normal" and f.acero or dificultad == "acero" and not f.acero:
                continue
            if prefs["fisuras_solo_facciones"] and facciones:
                if _plano(getattr(f, "faccion", "") or f.enemigo) not in facciones:
                    continue
            acero = f" ({t('Camino de Acero')})" if f.acero else ""
            avisos.append(Aviso(
                f"fisura|{f.era}|{f.nodo}|{clave_mision(f.modo or f.mision)}|{f.acero}|{_iso(f.expira)}",
                t("Fisura {era} de {mision} en {nodo}{acero}", era=f.era,
                  mision=_nombre_mision(f.modo, f.mision), nodo=f.nodo, acero=acero),
                f.expira or ahora + timedelta(hours=2),
            ))

    baro = getattr(mundo, "baro_detalle", None)
    if baro is not None and baro.activo and vigente(baro.expira):
        fin = baro.expira or semana_despues
        if prefs["baro"]:
            avisos.append(Aviso(
                f"baro|{_iso(baro.llegada)}",
                t("Ha llegado Baro Ki'Teer a {lugar}", lugar=baro.lugar or "?"),
                fin,
            ))
        if prefs["baro_objetivo"] and objetivos_baro:
            for o in baro.inventario:
                if o.objetivo:
                    avisos.append(Aviso(
                        f"baro_objetivo|{_iso(baro.llegada)}|{o.unique_name or o.nombre}",
                        t("Baro Ki'Teer trae algo de tus objetivos: {nombre}", nombre=o.nombre_mostrar),
                        fin,
                    ))

    if prefs["teshin_kuva"] or prefs["teshin_umbra"] or prefs["teshin_cambio"]:
        nombre, fin = recompensa_teshin(mundo, ahora)
        plano = _plano(nombre)
        if (prefs["teshin_cambio"] or prefs["teshin_kuva"] and "kuva" in plano
                or prefs["teshin_umbra"] and "umbra" in plano):
            avisos.append(Aviso(
                f"teshin|{_iso(fin)}|{nombre}",
                t("Teshin (Camino de Acero) ofrece esta semana: {nombre}", nombre=nombre_teshin(nombre)),
                fin,
            ))

    if prefs["palladino"]:
        inicio = inicio_semana(ahora)
        avisos.append(Aviso(
            f"palladino|{semana(ahora)}",
            t("Nueva semana: ya puedes cambiar Fragmentos de Agrietado por Kuva con Palladino "
              "en Estela de Hierro"),
            inicio + timedelta(weeks=1),
        ))

    arbitraje = getattr(mundo, "arbitracion", None)
    if prefs["arbitraje"] and arbitraje is not None and vigente(arbitraje.expira):
        tipos = {clave_mision(x) for x in prefs["arbitraje_tipos"]}
        if not tipos or clave_mision(arbitraje.tipo) in tipos:
            detalle = f" ({arbitraje.detalle})" if arbitraje.detalle else ""
            avisos.append(Aviso(
                f"arbitraje|{arbitraje.texto}|{_iso(arbitraje.expira)}",
                t("Arbitraje en {nodo}{detalle}", nodo=arbitraje.texto, detalle=detalle),
                arbitraje.expira or ahora + timedelta(hours=1),
            ))

    buscadas = palabras(prefs["invasiones_palabras"])
    if prefs["invasiones"] and buscadas:
        for i in getattr(mundo, "invasiones", []):
            nombres = [o.nombre_mostrar for o in i.objetos] + [o.nombre_en for o in i.objetos]
            if not nombres:
                nombres = [i.recompensas]
            plano = _plano(" | ".join(nombres))
            if any(p in plano for p in buscadas):
                premio = ", ".join(dict.fromkeys(
                    (f"{o.cantidad}x " if o.cantidad > 1 else "") + o.nombre_mostrar for o in i.objetos
                )) or i.recompensas
                avisos.append(Aviso(
                    f"invasion|{i.nodo}|{i.recompensas}",
                    t("Invasion en {nodo}: {premio}", nodo=i.nodo, premio=premio),
                    ahora + timedelta(days=3),
                ))

    if prefs["alertas"]:
        for a in getattr(mundo, "alertas", []):
            if vigente(a.expira):
                avisos.append(Aviso(f"alerta|{a.texto}|{_iso(a.expira)}",
                                    t("Alerta: {detalle}", detalle=a.texto), a.expira or semana_despues))

    sortie = getattr(mundo, "sortie", []) or []
    if prefs["incursion"] and sortie and vigente(sortie[0].expira):
        avisos.append(Aviso(f"incursion|{_iso(sortie[0].expira)}",
                            t("Hay una incursion nueva"), sortie[0].expira or ahora + timedelta(days=1)))
    arcontes = getattr(mundo, "arcontes", []) or []
    if prefs["arcontes"] and arcontes and vigente(arcontes[0].expira):
        avisos.append(Aviso(f"arcontes|{_iso(arcontes[0].expira)}",
                            t("Hay una caza de arcontes nueva"), arcontes[0].expira or semana_despues))

    if prefs["noche_cetus"]:
        for c in getattr(mundo, "ciclos", []):
            if c.clave == "cetusCycle" and c.estado_en == "night" and vigente(c.expira):
                avisos.append(Aviso(f"cetus|{_iso(c.expira)}",
                                    t("Es de noche en las Llanuras de Eidolon (Cetus)"),
                                    c.expira or ahora + timedelta(hours=1)))
    return avisos


def juntar(avisos: list[Aviso]) -> str:
    """Un solo texto para el globo de Windows: una linea por aviso, como mucho MAX_LINEAS."""
    lineas = [a.texto for a in avisos[:MAX_LINEAS]]
    if len(avisos) > MAX_LINEAS:
        lineas.append(t("y {n} avisos mas en la pestana Mundo", n=len(avisos) - MAX_LINEAS))
    return "\n".join(lineas)


class Avisador:
    """Recuerda que se ha avisado ya (clave -> hasta cuando) para no repetir nada."""

    def __init__(self, enviados: dict | None = None):
        self.enviados: dict[str, str] = {}
        if isinstance(enviados, dict):
            self.enviados = {str(k): str(v) for k, v in enviados.items()}

    def _limpiar(self, ahora: datetime) -> None:
        vivos = {}
        for clave, hasta in self.enviados.items():
            try:
                momento = datetime.fromisoformat(hasta)
            except ValueError:
                continue
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=timezone.utc)
            if momento > ahora:
                vivos[clave] = hasta
        self.enviados = vivos

    def nuevos(self, avisos: list[Aviso], ahora: datetime | None = None) -> list[Aviso]:
        """Los que no se han enviado todavia; quedan apuntados como enviados."""
        ahora = ahora or datetime.now(timezone.utc)
        self._limpiar(ahora)
        salida = []
        for a in avisos:
            if a.clave in self.enviados:
                continue
            self.enviados[a.clave] = (max(a.caduca, ahora + timedelta(minutes=5))).isoformat()
            salida.append(a)
        return salida
