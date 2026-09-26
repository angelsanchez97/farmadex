"""Aviso sobre Digital Extremes: dialogo Acerca de, boton en Ajustes, guia y receta."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from farmadex.ui import acerca_de

RAIZ = Path(__file__).resolve().parents[1]


def _app():
    return QApplication.instance() or QApplication([])


def _textos(dialogo) -> str:
    return "\n".join(e.text() for e in dialogo.findChildren(QLabel))


def test_el_dialogo_lleva_el_enlace_de_de_la_imagen_y_las_citas_en_ingles():
    _app()
    dialogo = acerca_de.DialogoAcercaDe()
    textos = _textos(dialogo)
    assert acerca_de.URL_POLITICA_DE in dialogo.enlace_politica.text()
    assert dialogo.enlace_politica.openExternalLinks()
    assert "we do not endorse any use of third-party software" in textos
    assert "at your own risk" in textos
    assert "Digital Extremes" in textos
    assert dialogo.imagen.pixmap() is not None and not dialogo.imagen.pixmap().isNull()
    # Nunca se promete que no haya baneo: DE dice expresamente lo contrario.
    assert "ban" not in textos.lower()
    dialogo.close()


def test_las_citas_de_de_siguen_en_ingles_en_otro_idioma():
    from farmadex import idiomas

    _app()
    idiomas.cargar("fr")
    try:
        textos = _textos(acerca_de.DialogoAcercaDe())
        assert "we do not endorse any use of third-party software" in textos
        assert "at your own risk" in textos
        assert "Digital Extremes" in textos
    finally:
        idiomas.cargar("es")


def test_la_imagen_es_la_tapada_de_docs_y_va_en_la_receta():
    ruta = acerca_de.ruta_imagen_soporte()
    assert ruta == RAIZ / "docs" / "img" / "respuesta_soporte_de.png"
    assert ruta.exists()
    spec = (RAIZ / "empaquetado" / "farmadex.spec").read_text(encoding="utf-8")
    assert '"docs/img/respuesta_soporte_de.png"), "docs/img"' in spec


def test_ajustes_tiene_el_boton_y_abre_el_dialogo(monkeypatch, tmp_path):
    from farmadex.ui import pestana_ajustes

    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    _app()
    monkeypatch.setattr(pestana_ajustes, "guardar", lambda cfg: None)
    ajustes = pestana_ajustes.PestanaAjustes()
    assert "Farmadex" in ajustes.boton_acerca.text()
    antes = {id(w) for w in QApplication.topLevelWidgets() if isinstance(w, acerca_de.DialogoAcercaDe)}
    ajustes.boton_acerca.click()
    abiertos = [
        w for w in QApplication.topLevelWidgets()
        if isinstance(w, acerca_de.DialogoAcercaDe) and id(w) not in antes and w.isVisible()
    ]
    assert len(abiertos) == 1
    assert acerca_de.URL_POLITICA_DE in abiertos[0].enlace_politica.text()
    abiertos[0].close()


def test_el_primer_paso_de_la_guia_menciona_el_aviso():
    from farmadex.ui.guia import _pasos

    class Ventana:
        config = {}

    primero = _pasos(Ventana())[0]
    assert "DE" in primero.cuerpo
    assert "Acerca de Farmadex" in primero.cuerpo
    assert "Ajustes" in primero.cuerpo


# -- Discord de Farmadex --------------------------------------------------------------

def test_el_discord_sale_en_acerca_de_con_el_enlace_que_se_abre_al_pulsar():
    _app()
    assert acerca_de.URL_DISCORD == "https://discord.gg/7ezAmfqesS"
    dialogo = acerca_de.DialogoAcercaDe()
    assert acerca_de.URL_DISCORD in dialogo.discord.text()
    assert "Discord de Farmadex" in dialogo.discord.text()
    assert dialogo.discord.openExternalLinks()  # solo se abre al pulsarlo
    # Tambien en la pregunta "Tengo un problema o una idea", con el foro de ayuda.
    faq = dict(acerca_de.preguntas_frecuentes())
    problema = next(v for k, v in faq.items() if "problema" in k)
    assert acerca_de.URL_DISCORD in problema and "foro de ayuda del Discord" in problema
    dialogo.close()


def test_el_discord_sale_en_el_pie_de_ajustes_y_al_guardar_el_informe(monkeypatch, tmp_path):
    from farmadex.ui import pestana_ajustes

    monkeypatch.setenv("FARMADEX_DATOS", str(tmp_path))
    _app()
    monkeypatch.setattr(pestana_ajustes, "guardar", lambda cfg: None)
    ajustes = pestana_ajustes.PestanaAjustes()
    assert acerca_de.URL_DISCORD in ajustes.discord.text()
    assert ajustes.discord.openExternalLinks()
    ajustes.informe_guardado(tmp_path / "informe.zip")
    assert str(tmp_path / "informe.zip") in ajustes.estado_informe.text()
    assert acerca_de.URL_DISCORD in ajustes.estado_informe.text()
    assert "foro de ayuda" in ajustes.estado_informe.text()
    assert ajustes.estado_informe.openExternalLinks()


def test_el_discord_se_traduce(monkeypatch):
    from farmadex import idiomas

    _app()
    try:
        idiomas.cargar("en")
        assert "Farmadex Discord" in acerca_de.texto_discord()
        assert acerca_de.URL_DISCORD in acerca_de.texto_discord()
    finally:
        idiomas.cargar("es")
