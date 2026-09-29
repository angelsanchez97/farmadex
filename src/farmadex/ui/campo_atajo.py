"""Campo de Ajustes > Atajos que se rellena pulsando la tecla, no escribiendola.

Se pulsa el campo, dice "Pulsa una tecla…" y lo siguiente que se pulse queda como
atajo: una tecla sola (F9, G), una combinacion (Ctrl+Alt+W), un boton del raton (la
rueda o los laterales) o una combinacion del mando (se mantienen los botones y se
sueltan). Esc cancela y Retroceso lo deja sin atajo. Mientras espera, los atajos de
Farmadex no saltan (`hotkeys.pausar`).

Por dentro se guarda el mismo texto de siempre ("Ctrl+Alt+W", "F9", "Mouse4",
"Mando:View+A"), asi que la configuracion que ya tenia el usuario vale tal cual.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from .. import hotkeys
from ..hotkeys import (
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, Atajo, Mandos, formatear, interpretar,
)
from ..idiomas import t
from ..registro_log import obtener
from .estilo_c import BotonC

log = obtener("campo_atajo")

# Tecla de Qt -> codigo virtual de Windows (para cuando Qt no da el nativo: pruebas).
_QT_A_VK = {
    **{getattr(Qt, f"Key_F{i}"): 0x6F + i for i in range(1, 25)},
    Qt.Key_Space: 0x20, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D, Qt.Key_Tab: 0x09,
    Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E, Qt.Key_Home: 0x24, Qt.Key_End: 0x23,
    Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_Up: 0x26, Qt.Key_Down: 0x28,
    Qt.Key_Left: 0x25, Qt.Key_Right: 0x27, Qt.Key_Pause: 0x13, Qt.Key_CapsLock: 0x14,
    Qt.Key_Print: 0x2C, Qt.Key_ScrollLock: 0x91, Qt.Key_NumLock: 0x90,
}
_SOLO_MODIFICADOR = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr}
_BOTON_RATON = {Qt.MiddleButton: 0x04, Qt.BackButton: 0x05, Qt.ForwardButton: 0x06}


def modificadores_de(qt_mods) -> int:
    m = 0
    if qt_mods & Qt.ControlModifier:
        m |= MOD_CONTROL
    if qt_mods & Qt.AltModifier:
        m |= MOD_ALT
    if qt_mods & Qt.ShiftModifier:
        m |= MOD_SHIFT
    if qt_mods & Qt.MetaModifier:
        m |= MOD_WIN
    return m


def vk_de_evento(evento) -> int:
    """Codigo virtual de la tecla pulsada (0 si no se sabe)."""
    try:
        nativo = int(evento.nativeVirtualKey())
    except (AttributeError, TypeError):
        nativo = 0
    if 0 < nativo < 0xFF:
        return nativo
    tecla = evento.key()
    if Qt.Key_A <= tecla <= Qt.Key_Z or Qt.Key_0 <= tecla <= Qt.Key_9:
        if evento.modifiers() & Qt.KeypadModifier and Qt.Key_0 <= tecla <= Qt.Key_9:
            return 0x60 + (tecla - Qt.Key_0)
        return int(tecla)
    return _QT_A_VK.get(tecla, 0)


def _nombre_windows(vk: int) -> str:
    """Nombre de la tecla segun la distribucion del teclado ("Ñ", "´"...); '' si no se sabe."""
    try:
        user32 = ctypes.windll.user32
        escaneo = user32.MapVirtualKeyW(vk, 0)
        if not escaneo:
            return ""
        buffer = ctypes.create_unicode_buffer(32)
        if user32.GetKeyNameTextW(escaneo << 16, buffer, 32):
            return buffer.value
    except (AttributeError, OSError):
        pass
    return ""


def texto_legible(combinacion: str) -> str:
    """Como se le ensena al usuario un atajo guardado."""
    if not (combinacion or "").strip():
        return t("Sin atajo")
    try:
        atajo = interpretar(combinacion)
    except ValueError:
        return combinacion
    if atajo.tipo == "mando":
        return t("Mando") + ": " + formatear(atajo).split(":", 1)[1].replace("+", " + ")
    partes = formatear(atajo).split("+")
    if atajo.tipo == "raton":
        partes[-1] = {0x04: t("Clic de la rueda"), 0x05: t("Ratón lateral 1"),
                      0x06: t("Ratón lateral 2")}.get(atajo.codigo, partes[-1])
    elif partes[-1] == "Space":
        partes[-1] = t("Espacio")
    elif partes[-1].startswith("VK"):
        partes[-1] = _nombre_windows(atajo.codigo) or partes[-1]
    return " + ".join(partes)


def aviso_de(combinacion: str) -> str:
    """Aviso (no error) si el atajo va a estorbar jugando; '' si no."""
    if not (combinacion or "").strip():
        return ""
    try:
        atajo = interpretar(combinacion)
    except ValueError:
        return ""
    if hotkeys.choca_con_el_juego(combinacion):
        if atajo.tipo == "mando":
            return t("Ojo: un botón suelto del mando también lo usa el juego. Mejor una combinación "
                     "(por ejemplo, View + A).")
        return t("Ojo: {tecla} también la usa el juego; saltará cada vez que la pulses jugando "
                 "(o escribiendo en el chat).", tecla=texto_legible(combinacion))
    return ""


class CampoAtajo(BotonC):
    """Boton que muestra el atajo y, al pulsarlo, captura la siguiente tecla, boton o mando."""

    cambiado = Signal(str)  # el texto nuevo ("" = sin atajo)

    MANDO_MS = 30  # mientras se captura, lo que tarda en mirar el mando (solo entonces)
    capturando = False  # tambien a nivel de clase: Qt manda eventos antes de acabar __init__

    def __init__(self, combinacion: str = "", parent=None, mandos: Mandos | None = None):
        super().__init__("", principal=False, tam=11, parent=parent)
        self._texto = (combinacion or "").strip()
        self._previo = self._texto
        self.capturando = False
        self._mandos = mandos
        self._mando_max = 0
        self._reloj_mando = QTimer(self)
        self._reloj_mando.setInterval(self.MANDO_MS)
        self._reloj_mando.timeout.connect(self._mirar_mando)
        self.setFocusPolicy(Qt.StrongFocus)
        self.clicked.connect(self._alternar)
        self._pintar()

    def valor(self) -> str:
        """Lo que se guarda en la configuracion ("" = sin atajo); `text()` es lo que se ve."""
        return self._texto

    def poner_valor(self, texto: str) -> None:
        self._texto = (texto or "").strip()
        self._pintar()

    def _pintar(self) -> None:
        if self.capturando:
            visible = t("Pulsa una tecla…")
        else:
            visible = texto_legible(self._texto)
        self._ver(visible)
        self.setToolTip(t("Pulsa aquí y luego la tecla, el botón del ratón o los botones del mando. "
                          "Esc cancela; Retroceso lo deja sin atajo."))

    # -- captura --

    def _alternar(self) -> None:
        if self.capturando:
            self.cancelar()
        else:
            self.empezar()

    def empezar(self) -> None:
        self.capturando = True
        self._previo = self._texto
        self._mando_max = 0
        hotkeys.pausar(True)
        self.setFocus(Qt.MouseFocusReason)
        try:
            self.grabKeyboard()
            self.grabMouse()
        except Exception:  # noqa: BLE001 - sin agarre (plataforma rara): se captura con el foco
            pass
        if self._mandos is None:
            self._mandos = Mandos()
        self._reloj_mando.start()
        self._pintar()

    def _terminar(self) -> None:
        self.capturando = False
        self._reloj_mando.stop()
        self.releaseKeyboard()
        self.releaseMouse()
        hotkeys.pausar(False)
        self._pintar()

    def cancelar(self) -> None:
        self._texto = self._previo
        self._terminar()

    def fijar(self, atajo: Atajo | None) -> None:
        self._texto = formatear(atajo) if atajo is not None else ""
        self._terminar()
        log.info("Atajo capturado: %s", self._texto or "(ninguno)")
        self.cambiado.emit(self._texto)

    def event(self, evento):  # noqa: D102
        # Tab tambien es una tecla valida: que no la use Qt para cambiar de campo.
        if self.capturando and evento.type() == QEvent.KeyPress and evento.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(evento)
            return True
        return super().event(evento)

    def keyPressEvent(self, evento):  # noqa: N802
        if not self.capturando:
            if evento.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.empezar()
                return
            super().keyPressEvent(evento)
            return
        evento.accept()
        if evento.isAutoRepeat():
            return
        tecla = evento.key()
        mods = modificadores_de(evento.modifiers())
        if tecla == Qt.Key_Escape and not mods:
            self.cancelar()
            return
        if tecla == Qt.Key_Backspace and not mods:
            self.fijar(None)
            return
        if tecla in _SOLO_MODIFICADOR:
            nombres = [n for bit, n in hotkeys.NOMBRES_MODIFICADOR if mods & bit]
            self._ver(" + ".join(nombres) + " + …")
            return
        vk = vk_de_evento(evento)
        if not vk:
            return  # tecla que no se sabe registrar: se sigue esperando
        self.fijar(Atajo("teclado", mods, vk))

    def mousePressEvent(self, evento):  # noqa: N802
        if not self.capturando:
            super().mousePressEvent(evento)
            return
        evento.accept()
        boton = _BOTON_RATON.get(evento.button())
        if boton:
            self.fijar(Atajo("raton", modificadores_de(evento.modifiers()), boton))
        elif evento.button() in (Qt.LeftButton, Qt.RightButton):
            self.cancelar()  # el izquierdo y el derecho no valen: cancelan

    def mouseReleaseEvent(self, evento):  # noqa: N802
        if self.capturando:
            evento.accept()
            return
        super().mouseReleaseEvent(evento)

    def focusOutEvent(self, evento):  # noqa: N802
        if self.capturando and QApplication.activeWindow() is None:
            self.cancelar()  # se fue a otra ventana: no se queda esperando
        super().focusOutEvent(evento)

    def _mirar_mando(self) -> None:
        """Mando: se juntan los botones mientras hay alguno pulsado y se fija al soltarlos."""
        if not self.capturando or self._mandos is None:
            return
        try:
            botones = self._mandos.botones()
        except Exception:  # noqa: BLE001
            botones = 0
        if botones:
            self._mando_max |= botones
            self._ver(texto_legible(formatear(Atajo("mando", botones=self._mando_max))) + " …")
        elif self._mando_max:
            self.fijar(Atajo("mando", botones=self._mando_max))

    def _ver(self, texto: str) -> None:
        self.setText(texto)
        self.updateGeometry()
        self.update()

    def hideEvent(self, evento):  # noqa: N802
        if self.capturando:
            self.cancelar()
        super().hideEvent(evento)
