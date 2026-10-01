"""Ajustes > Datos > "Precios del mercado": de cuando son los precios y cuando llegan los nuevos.

Solo lee el estado de online/precios_diarios.py; nunca toca la red desde aqui. El
reloj de la cuenta atras solo corre mientras el panel se ve: oculto no gasta nada.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QTimer

from ..idiomas import t
from ..online import precios_diarios as pd
from .estilo_c import BotonC, EtiquetaC, PanelC, fila

# Cada cuanto se repinta la cuenta atras (minutos: no hace falta mas).
REPINTAR_MS = 20_000


def texto_cuenta_atras(ahora: datetime, siguiente: datetime) -> str:
    """"HH:MM" que faltan hasta `siguiente` (sin segundos, redondeando hacia arriba)."""
    segundos = max(0, int((siguiente - ahora).total_seconds() + 59))
    return f"{segundos // 3600:02d}:{(segundos % 3600) // 60:02d}"


def texto_fecha(fecha: datetime) -> str:
    local = fecha.astimezone()  # la hora del PC del jugador, que es la que entiende
    return local.strftime("%d/%m/%Y %H:%M")


class PanelPrecios(PanelC):
    def __init__(self, precios: pd.PreciosDiarios | None = None, reloj=pd.ahora_utc, parent=None):
        super().__init__("", parent=parent)
        self._precios = precios
        self._reloj = reloj
        self._tarea: pd.Tarea | None = None
        self.fecha = EtiquetaC("", "normal", envolver=True)
        self.cuenta = EtiquetaC("", "pequeno", tinta="suave", envolver=True)
        self.estado = EtiquetaC("", "pequeno", tinta="aviso", envolver=True)
        self.boton = BotonC("", tam=11)
        self.boton.clicked.connect(self.actualizar_ahora)
        self.nota = EtiquetaC("", "pequeno", tinta="tenue", envolver=True)
        self.capa.addWidget(self.fecha)
        self.capa.addWidget(self.cuenta)
        self.capa.addWidget(self.estado)
        self.capa.addLayout(fila(self.boton, None))
        self.capa.addWidget(self.nota)
        self.reloj_pantalla = QTimer(self)
        self.reloj_pantalla.setInterval(REPINTAR_MS)
        self.reloj_pantalla.timeout.connect(self.refrescar)
        self.retraducir()
        self.p.al_actualizar(self.refrescar)
        self.destroyed.connect(lambda *_a, p=self.p, cb=self.refrescar: p.quitar_observador(cb))

    @property
    def p(self) -> pd.PreciosDiarios:
        return self._precios if self._precios is not None else pd.precios()

    def retraducir(self) -> None:
        self.poner_titulo(t("Precios del mercado"))
        self.boton.setText(t("Actualizar precios ahora"))
        self.nota.setText(t(
            "Farmadex guarda cada día los precios de warframe.market para enseñarlos al instante, "
            "sin esperar. Se actualizan solos poco después de medianoche (hora UTC)."
        ))
        self.refrescar()

    def showEvent(self, evento):  # noqa: N802 - firma de Qt
        super().showEvent(evento)
        self.refrescar()
        self.reloj_pantalla.start()

    def hideEvent(self, evento):  # noqa: N802
        super().hideEvent(evento)
        self.reloj_pantalla.stop()

    def actualizar_ahora(self) -> None:
        self._tarea = self.p.actualizar_ahora()
        self.boton.setEnabled(False)
        self.refrescar()
        # La descarga va en su hilo: aqui solo se mira de vez en cuando si ha acabado.
        QTimer.singleShot(500, self._mirar_tarea)

    def _mirar_tarea(self) -> None:
        if self._tarea is not None and not self._tarea.hecha.is_set():
            QTimer.singleShot(500, self._mirar_tarea)
            return
        self.boton.setEnabled(True)
        self.refrescar()

    def refrescar(self) -> None:
        p = self.p
        ahora = self._reloj()
        fecha = p.fecha
        if fecha is not None:
            self.fecha.setText(t("Precios de warframe.market del {fecha}", fecha=texto_fecha(fecha)))
        elif not p.cargado.is_set():
            self.fecha.setText(t("Cargando los precios guardados…"))
        else:
            self.fecha.setText(t("Todavía no hay precios guardados: mientras tanto se consultan en vivo."))
        self.cuenta.setText(t("Próxima actualización de precios en {hhmm}",
                              hhmm=texto_cuenta_atras(ahora, pd.siguiente_medianoche(ahora))))
        descargador = p.descargador
        estado = descargador.estado if descargador else ""
        if self._tarea is not None and not self._tarea.hecha.is_set():
            estado = "descargando"
        de_hoy = fecha is not None and fecha.astimezone(timezone.utc).date() == ahora.date()
        mensajes = {
            "descargando": t("Descargando los precios…"),
            "sin_red": t("Sin conexión: se usan los últimos precios guardados. Se volverá a intentar solo."),
            "error": t("No se pudieron descargar los precios. Se volverá a intentar más tarde."),
            "otra_plataforma": t("Los precios diarios son de PC: en tu plataforma se consultan en vivo."),
            "aun_no_hay": "" if de_hoy else t("Los precios de hoy aún se están preparando; se volverá a mirar en un rato."),
            "al_dia": t("Ya tienes los precios de hoy."),
            "nuevo": t("Ya tienes los precios de hoy."),
        }
        texto = mensajes.get(estado, "")
        self.estado.setText(texto)
        self.estado.poner_tinta("suave" if estado in ("al_dia", "nuevo", "descargando") else "aviso")
        self.estado.setVisible(bool(texto))
