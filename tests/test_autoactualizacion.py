"""Actualizacion automatica: descarga comprobada, decision de instalar y setup silencioso.

Sin red: httpx.MockTransport hace de GitHub. Nunca se lanza ningun instalador.
"""

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from farmadex import VERSION
from farmadex.actualizador import descarga, instalacion
from farmadex.actualizador.app import Version, analizar_release

CONTENIDO = b"MZ" + bytes(range(256)) * 400  # 100 KB de "instalador"
HUELLA = hashlib.sha256(CONTENIDO).hexdigest()
URL = "https://github.com/angelsanchez97/farmadex/releases/download/v9.9.9/Farmadex-9.9.9-setup.exe"


def version(digest=f"sha256:{HUELLA}", url=URL):
    return Version(etiqueta="v9.9.9", url=url, notas="", nombre="Farmadex-9.9.9-setup.exe",
                   tamano=len(CONTENIDO), digest=digest)


class _Cortada(httpx.SyncByteStream):
    """Cuerpo que se corta a los `corte` bytes, como una conexion que se cae."""

    def __init__(self, datos: bytes, corte: int):
        self.datos, self.corte = datos, corte

    def __iter__(self):
        yield self.datos[: self.corte]
        raise httpx.ReadError("conexion cortada")


def transporte_ok(cortar_en: int | None = None, contador: list | None = None):
    """Sirve CONTENIDO con soporte de Range; `cortar_en` corta la primera respuesta."""
    peticiones = contador if contador is not None else []

    def responder(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion.headers.get("Range"))
        rango = peticion.headers.get("Range")
        if rango:
            desde = int(rango.split("=")[1].rstrip("-"))
            cuerpo = CONTENIDO[desde:]
            cabeceras = {"Content-Range": f"bytes {desde}-{len(CONTENIDO) - 1}/{len(CONTENIDO)}"}
            estado = 206
        else:
            cuerpo, cabeceras, estado = CONTENIDO, {}, 200
        if cortar_en is not None and len(peticiones) == 1:
            cabeceras["Content-Length"] = str(len(cuerpo))
            return httpx.Response(estado, stream=_Cortada(cuerpo, cortar_en), headers=cabeceras)
        return httpx.Response(estado, content=cuerpo, headers=cabeceras)

    return httpx.MockTransport(responder)


def test_analizar_release_guarda_la_huella_y_el_nombre_del_adjunto():
    v = analizar_release({
        "tag_name": "v9.9.9",
        "assets": [{
            "name": "Farmadex-9.9.9-setup.exe", "browser_download_url": URL,
            "size": 123, "digest": "sha256:" + "a" * 64,
        }],
    })
    assert (v.nombre, v.tamano, v.digest) == ("Farmadex-9.9.9-setup.exe", 123, "sha256:" + "a" * 64)
    assert descarga.huella_esperada(v) == "a" * 64


def test_solo_se_aceptan_adjuntos_del_repositorio_por_https():
    assert descarga.url_permitida(URL)
    assert not descarga.url_permitida(URL.replace("https://", "http://"))
    assert not descarga.url_permitida("https://github.com/otro/farmadex/releases/download/v1/x.exe")
    assert not descarga.url_permitida("https://evil.example/angelsanchez97/farmadex/releases/download/v1/x.exe")
    assert not descarga.url_permitida("https://github.com/angelsanchez97/farmadex/releases/download/v1/x.zip")


def test_descarga_con_huella_buena(tmp_path):
    ruta = descarga.descargar(version(), tmp_path, transporte=transporte_ok())
    assert ruta == tmp_path / "Farmadex-9.9.9-setup.exe"
    assert ruta.read_bytes() == CONTENIDO
    assert not list(tmp_path.glob("*.parcial"))
    # Ya bajada: no se vuelve a pedir.
    peticiones = []
    assert descarga.descargar(version(), tmp_path, transporte=transporte_ok(contador=peticiones)) == ruta
    assert peticiones == []


def test_huella_mala_o_ausente_no_deja_instalador(tmp_path):
    with pytest.raises(descarga.ErrorDescarga, match="huella SHA-256"):
        descarga.descargar(version(digest="sha256:" + "0" * 64), tmp_path, transporte=transporte_ok())
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(descarga.ErrorDescarga, match="no trae la huella"):
        descarga.descargar(version(digest=""), tmp_path, transporte=transporte_ok())
    with pytest.raises(descarga.ErrorDescarga, match="no trae la huella"):
        descarga.descargar(version(digest="md5:abc"), tmp_path, transporte=transporte_ok())
    with pytest.raises(descarga.ErrorDescarga, match="repositorio"):
        descarga.descargar(version(url="https://evil.example/setup.exe"), tmp_path, transporte=transporte_ok())


def test_descarga_cortada_se_reanuda_con_range(tmp_path, monkeypatch):
    monkeypatch.setattr(descarga, "ESPERA_REINTENTO", 0)
    # httpx agrupa lo leido en trozos de TROZO bytes: con trozos de 500, los 1000 bytes
    # que llegan antes del corte se escriben en disco y el segundo intento reanuda ahi.
    monkeypatch.setattr(descarga, "TROZO", 500)
    peticiones = []
    ruta = descarga.descargar(
        version(), tmp_path, transporte=transporte_ok(cortar_en=1000, contador=peticiones), intentos=3,
    )
    assert ruta.read_bytes() == CONTENIDO
    assert peticiones[0] is None and peticiones[1] == "bytes=1000-"


def test_sin_red_falla_con_motivo_y_sin_restos(tmp_path, monkeypatch):
    def caido(peticion):
        raise httpx.ConnectError("sin red")

    monkeypatch.setattr(descarga, "ESPERA_REINTENTO", 0)
    with pytest.raises(descarga.ErrorDescarga, match="conexion"):
        descarga.descargar(version(), tmp_path, transporte=httpx.MockTransport(caido), intentos=2)
    assert not list(tmp_path.glob("*.exe"))


def test_un_404_no_se_reintenta(tmp_path):
    peticiones = []

    def no_esta(peticion):
        peticiones.append(1)
        return httpx.Response(404)

    with pytest.raises(descarga.ErrorDescarga, match="HTTP 404"):
        descarga.descargar(version(), tmp_path, transporte=httpx.MockTransport(no_esta), intentos=3)
    assert len(peticiones) == 1


def test_el_descargador_avisa_por_senales(tmp_path):
    from PySide6.QtWidgets import QApplication

    # Las senales salen del hilo de descarga y llegan por la cola de eventos de Qt.
    # QApplication y no QCoreApplication: las pruebas de despues crean widgets y
    # reutilizan la instancia que haya.
    app = QApplication.instance() or QApplication([])
    d = descarga.DescargadorApp(tmp_path, transporte=transporte_ok())
    listas, fallos, avances = [], [], []
    d.lista.connect(lambda v, r: listas.append(r))
    d.fallo.connect(lambda v, m: fallos.append(m))
    d.progreso.connect(avances.append)
    assert d.descargar(version())
    d._hilo.join(10)
    app.processEvents()
    assert listas == [tmp_path / "Farmadex-9.9.9-setup.exe"] and fallos == []
    assert avances and avances[-1] == 100

    d = descarga.DescargadorApp(tmp_path, transporte=transporte_ok())
    d.fallo.connect(lambda v, m: fallos.append(m))
    d.descargar(version(digest="sha256:" + "f" * 64))
    d._hilo.join(10)
    app.processEvents()
    assert fallos and "huella" in fallos[0]


def test_limpiar_borra_restos_pero_conserva_el_bueno(tmp_path):
    bueno = tmp_path / "Farmadex-9.9.9-setup.exe"
    for nombre in ("Farmadex-9.9.8-setup.exe", "Farmadex-9.9.7-setup.exe.parcial", bueno.name):
        (tmp_path / nombre).write_bytes(b"x")
    (tmp_path / "pendiente.json").write_text("{}")
    descarga.limpiar(tmp_path, conservar=bueno)
    assert sorted(f.name for f in tmp_path.iterdir()) == [bueno.name, "pendiente.json"]


# -- instalado o portable ---------------------------------------------------------


def test_deteccion_de_instalacion_por_instalador(tmp_path):
    carpeta = tmp_path / "Programs" / "Farmadex"
    carpeta.mkdir(parents=True)
    exe = carpeta / "Farmadex.exe"
    registro = lambda: str(carpeta)  # noqa: E731
    assert instalacion.es_instalacion_por_instalador(exe, leer_registro=registro)
    # Portable: mismo registro (hay otra copia instalada) pero el exe esta en otro sitio.
    assert not instalacion.es_instalacion_por_instalador(tmp_path / "portable" / "Farmadex.exe", leer_registro=registro)
    # Sin clave de desinstalacion: portable.
    assert not instalacion.es_instalacion_por_instalador(exe, leer_registro=lambda: None)
    # Registro que revienta: portable, sin propagar.
    def roto():
        raise OSError("sin registro")
    assert not instalacion.es_instalacion_por_instalador(exe, leer_registro=roto)
    # Desde el codigo (sin congelar) nunca se autoinstala.
    assert not instalacion.es_instalacion_por_instalador(None, leer_registro=registro)


def test_parametros_del_setup_silencioso(tmp_path):
    setup = tmp_path / "Farmadex-9.9.9-setup.exe"
    params = instalacion.parametros_instalador(setup, tmp_path / "instalador.log")
    assert params[0] == str(setup)
    for p in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/AUTOACTUALIZAR=1"):
        assert p in params
    assert params[-1] == f"/LOG={tmp_path / 'instalador.log'}"
    orden = instalacion._linea_de_ordenes(setup, tmp_path / "Farmadex.exe")
    assert re.match(r'^("[^"]*cmd\.exe"|\S*cmd\.exe) /d /c "', orden) and orden.endswith('"')
    assert "|| start" in orden and str(tmp_path / "Farmadex.exe") in orden
    # Los parametros del setup van sin comillas, tal y como se probaron de verdad.
    assert " /VERYSILENT " in orden and '"/VERYSILENT"' not in orden


def test_la_orden_entrecomilla_lo_que_cmd_interpretaria(tmp_path, monkeypatch):
    """Una carpeta de usuario "Ana&Luis" (sin espacios) partia la orden en dos."""
    carpeta = tmp_path / "Ana&Luis(2)"
    monkeypatch.setattr(instalacion, "DIR_LOGS", carpeta / "logs")
    orden = instalacion._linea_de_ordenes(carpeta / "setup.exe", carpeta / "Farmadex.exe")
    assert f'"{carpeta / "setup.exe"}" /VERYSILENT' in orden
    assert f'"/LOG={carpeta / "logs" / "instalador.log"}"' in orden
    assert orden.endswith(f'|| start "" "{carpeta / "Farmadex.exe"}""')


@pytest.mark.skipif(os.name != "nt", reason="la orden es para cmd.exe de Windows")
def test_la_orden_de_cmd_funciona_con_espacios_acentos_y_simbolos(tmp_path, monkeypatch):
    """Se ejecuta de verdad: un setup falso que falla relanza el "Farmadex" falso.

    Nada de esto abre ventanas: el setup es un .cmd dentro de la consola oculta y el
    relanzado un .vbs (wscript, sin consola) que deja una marca.
    """
    carpeta = tmp_path / "Ana María & Cía (2)"
    carpeta.mkdir()
    monkeypatch.setattr(instalacion, "DIR_LOGS", carpeta / "logs")
    exe = carpeta / "Farmadex.vbs"
    exe.write_text(
        'Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
        'fso.CreateTextFile(fso.GetParentFolderName(WScript.ScriptFullName) & "\\relanzado.txt", True).Close\r\n',
        encoding="utf-16",
    )
    marca = carpeta / "relanzado.txt"
    argumentos = carpeta / "args.txt"

    def correr(codigo: int) -> None:
        setup = carpeta / f"setup{codigo}.cmd"
        setup.write_text(f'@echo %*> "%~dp0args.txt"\r\n@exit /b {codigo}\r\n', encoding="ascii")
        marca.unlink(missing_ok=True)
        orden = instalacion._linea_de_ordenes(setup, exe)
        subprocess.run(orden, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)  # noqa: S603
        for _ in range(50):
            if marca.exists():
                break
            time.sleep(0.1)

    correr(1)
    assert marca.exists(), "el setup fallo y no se relanzo Farmadex"
    recibido = argumentos.read_text(encoding="utf-8", errors="replace")
    assert "/VERYSILENT" in recibido and "/AUTOACTUALIZAR=1" in recibido
    assert re.search(r'"/LOG=.*& C.*\\logs\\instalador\.log"', recibido)

    correr(0)
    assert not marca.exists(), "el setup fue bien y aun asi se relanzo el Farmadex viejo"


@pytest.mark.skipif(os.name != "nt", reason="mutex de Windows")
def test_se_detecta_otro_farmadex_abierto_y_se_recupera_el_mutex(monkeypatch):
    import ctypes

    # Con el nombre real, el Farmadex instalado que tenga abierto quien corre las
    # pruebas contaria como "otro".
    monkeypatch.setattr(instalacion, "MUTEX", f"FarmadexPrueba{os.getpid()}")
    monkeypatch.setattr(instalacion, "_mutex", None)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    instalacion.senalar_en_ejecucion()
    assert not instalacion.otra_instancia_abierta()
    otro = k32.CreateMutexW(None, False, instalacion.MUTEX)  # "el otro Farmadex"
    try:
        assert instalacion.otra_instancia_abierta()
    finally:
        k32.CloseHandle(otro)
    assert not instalacion.otra_instancia_abierta()
    # Tras mirar se vuelve a tener el mutex: el instalador seguiria esperandonos.
    assert instalacion._mutex is not None


def test_instalar_silencioso_apunta_la_version_y_no_falla_sin_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(instalacion, "DIR_LOGS", tmp_path / "logs")
    monkeypatch.setattr(instalacion, "RUTA_PENDIENTE", tmp_path / "pendiente.json")
    lanzados = []
    monkeypatch.setattr(instalacion.subprocess, "Popen", lambda orden, **k: lanzados.append(orden))
    assert not instalacion.instalar_silencioso(tmp_path / "no-existe.exe", "v9.9.9")
    assert lanzados == []
    setup = tmp_path / "Farmadex-9.9.9-setup.exe"
    setup.write_bytes(CONTENIDO)
    assert instalacion.instalar_silencioso(setup, "v9.9.9", ejecutable_actual=tmp_path / "Farmadex.exe")
    assert len(lanzados) == 1 and "/VERYSILENT" in lanzados[0]
    assert json.loads((tmp_path / "pendiente.json").read_text())["version"] == "v9.9.9"


def test_resultado_de_la_instalacion_anterior(tmp_path, monkeypatch):
    monkeypatch.setattr(instalacion, "RUTA_PENDIENTE", tmp_path / "pendiente.json")
    monkeypatch.setattr(instalacion, "RUTA_FALLIDA", tmp_path / "fallida.json")
    assert instalacion.resultado_instalacion_anterior() is None

    # Se lanzo la v9.9.9 pero seguimos en VERSION: fallo, y no se vuelve a intentar sola.
    setup = tmp_path / "Farmadex-9.9.9-setup.exe"
    setup.write_bytes(b"x")
    (tmp_path / "pendiente.json").write_text(json.dumps({"version": "v9.9.9", "setup": str(setup)}))
    assert instalacion.resultado_instalacion_anterior() == ("fallida", "v9.9.9")
    assert not setup.exists() and not (tmp_path / "pendiente.json").exists()
    assert instalacion.version_fallida() == "v9.9.9"
    assert instalacion.resultado_instalacion_anterior() is None

    # Se lanzo la version que ahora corre: instalada, y se olvida el fallo anterior.
    (tmp_path / "pendiente.json").write_text(json.dumps({"version": VERSION, "setup": str(setup)}))
    assert instalacion.resultado_instalacion_anterior() == ("instalada", VERSION)
    assert instalacion.version_fallida() is None

    # "v" delante o no, es la misma version.
    (tmp_path / "pendiente.json").write_text(json.dumps({"version": f"v{VERSION}"}))
    assert instalacion.resultado_instalacion_anterior() == ("instalada", f"v{VERSION}")


def test_un_apunte_viejo_o_ilegible_no_es_un_fallo(tmp_path, monkeypatch):
    """Se instalo a mano una version mas nueva con un apunte pendiente: ni exito ni
    fallo, y sobre todo no se veta nada. Un apunte sin version tampoco."""
    monkeypatch.setattr(instalacion, "RUTA_PENDIENTE", tmp_path / "pendiente.json")
    monkeypatch.setattr(instalacion, "RUTA_FALLIDA", tmp_path / "fallida.json")
    for apunte in ({"version": "v0.0.1"}, {"version": ""}, {"version": "beta"}, {}):
        (tmp_path / "pendiente.json").write_text(json.dumps(apunte))
        assert instalacion.resultado_instalacion_anterior() is None
        assert not (tmp_path / "pendiente.json").exists()
        assert instalacion.version_fallida() is None


def test_un_trozo_viejo_que_no_cuadra_se_baja_de_cero(tmp_path):
    """El adjunto se volvio a subir con otro contenido y quedaba un .parcial de antes:
    reanudar daba huella mala y se ofrecia el enlace; ahora se baja entero una vez."""
    peticiones: list = []
    (tmp_path / "Farmadex-9.9.9-setup.exe.parcial").write_bytes(b"basura" * 200)
    ruta = descarga.descargar(version(), tmp_path, transporte=transporte_ok(contador=peticiones))
    assert ruta.read_bytes() == CONTENIDO
    assert peticiones == ["bytes=1200-", None]
    assert not list(tmp_path.glob("*.parcial"))


# -- la ventana decide -------------------------------------------------------------


def _ventana_falsa(monkeypatch, auto=True, instalado=True, fallida=None, otra=False):
    import types

    from farmadex.ui.overlay import VentanaOverlay

    avisos, ajustes, descargas, lanzados = {}, [], [], []
    monkeypatch.setattr(instalacion, "es_instalacion_por_instalador", lambda *a, **k: instalado)
    monkeypatch.setattr(instalacion, "otra_instancia_abierta", lambda: otra)
    monkeypatch.setattr(instalacion, "version_fallida", lambda: fallida)
    monkeypatch.setattr(instalacion, "instalar_silencioso", lambda ruta, etiqueta, **k: lanzados.append((ruta, etiqueta)) or True)
    falso = types.SimpleNamespace(
        _aviso=lambda clave, texto: avisos.__setitem__(clave, texto),
        estado=types.SimpleNamespace(setText=lambda s: None),
        ajustes=types.SimpleNamespace(anunciar_version=lambda v, **k: ajustes.append(k), estado_version=lambda s: None),
        nueva_version=None, actualizacion_lista=None, _fallo_actualizacion=None, _instalador_lanzado=False,
        config={"actualizar_automaticamente": auto},
        descargador=types.SimpleNamespace(descargar=lambda v: descargas.append(v) or True, cancelar=lambda: None),
        cerrar_programa=types.SimpleNamespace(emit=lambda: None),
    )
    for nombre in ("_avisar_descarga_manual", "_conviene_autoactualizar", "_descargar_actualizacion",
                   "_actualizacion_lista", "_fallo_descarga", "_reiniciar_y_actualizar",
                   "_lanzar_instalacion_pendiente", "_hay_version_nueva", "_progreso_descarga"):
        setattr(falso, nombre, (lambda n: lambda *a, **k: getattr(VentanaOverlay, n)(falso, *a, **k))(nombre))
    return falso, avisos, ajustes, descargas, lanzados


def test_con_auto_y_instalado_se_descarga_y_se_instala_al_cerrar(monkeypatch):
    falso, avisos, ajustes, descargas, lanzados = _ventana_falsa(monkeypatch)
    v = version()
    falso._hay_version_nueva(v)
    assert descargas == [v] and "Descargando" in avisos["version"]
    falso._progreso_descarga(42)
    assert "42%" in avisos["version"]

    falso._actualizacion_lista(v, Path("C:/x/setup.exe"))
    assert "farmadex:actualizar" in avisos["version"] and "Reiniciar y actualizar" in avisos["version"]
    assert ajustes[-1] == {"lista": True}
    # Al cambiar de idioma se vuelve a pasar por aqui: no se descarga otra vez.
    falso._hay_version_nueva(v)
    assert len(descargas) == 1 and "farmadex:actualizar" in avisos["version"]

    # Al cerrar (o al pulsar) se lanza una sola vez.
    assert falso._lanzar_instalacion_pendiente()
    assert not falso._lanzar_instalacion_pendiente()
    assert lanzados == [(Path("C:/x/setup.exe"), "v9.9.9")]


def test_sin_auto_o_en_portable_solo_se_avisa_con_enlace(monkeypatch):
    for auto, instalado in ((False, True), (True, False)):
        falso, avisos, ajustes, descargas, _ = _ventana_falsa(monkeypatch, auto=auto, instalado=instalado)
        falso._hay_version_nueva(version())
        assert descargas == []
        assert URL in avisos["version"] and "Descargala" in avisos["version"]
        assert ajustes == [{}]


def test_si_esa_version_ya_fallo_al_instalarse_no_se_insiste(monkeypatch):
    falso, avisos, _, descargas, _ = _ventana_falsa(monkeypatch, fallida="v9.9.9")
    falso._hay_version_nueva(version())
    assert descargas == [] and URL in avisos["version"]


def test_si_la_descarga_falla_se_sigue_con_la_actual_y_se_dice_por_que(monkeypatch):
    falso, avisos, _, descargas, lanzados = _ventana_falsa(monkeypatch)
    v = version()
    falso._hay_version_nueva(v)
    falso._fallo_descarga(v, "la huella SHA-256 del instalador no coincide con la publicada")
    assert "huella SHA-256" in avisos["version"] and URL in avisos["version"]
    assert falso.actualizacion_lista is None
    assert not falso._lanzar_instalacion_pendiente() and lanzados == []
    # Al regenerar el aviso (idioma, tema) se conserva el motivo sin volver a descargar.
    falso._hay_version_nueva(v)
    assert len(descargas) == 1 and "huella SHA-256" in avisos["version"]


def test_con_otro_farmadex_abierto_se_deja_la_instalacion_para_el_ultimo(monkeypatch):
    falso, avisos, _, _, lanzados = _ventana_falsa(monkeypatch, otra=True)
    v = version()
    falso._actualizacion_lista(v, Path("C:/x/setup.exe"))
    assert not falso._lanzar_instalacion_pendiente() and lanzados == []
    assert "otro Farmadex abierto" in avisos["version"]
    # La descarga sigue lista: cuando el otro se cierre, este la instala al salir.
    assert falso.actualizacion_lista == (v, Path("C:/x/setup.exe")) and not falso._instalador_lanzado
    monkeypatch.setattr(instalacion, "otra_instancia_abierta", lambda: False)
    assert falso._lanzar_instalacion_pendiente() and len(lanzados) == 1


def test_si_se_desactiva_la_casilla_tras_descargar_no_se_instala_al_cerrar(monkeypatch):
    falso, _, _, _, lanzados = _ventana_falsa(monkeypatch)
    v = version()
    falso._actualizacion_lista(v, Path("C:/x/setup.exe"))
    falso.config["actualizar_automaticamente"] = False
    assert not falso._lanzar_instalacion_pendiente() and lanzados == []
    # Pulsar "Reiniciar y actualizar" es una orden expresa: eso si.
    assert falso._lanzar_instalacion_pendiente(a_mano=True) and len(lanzados) == 1


# -- el instalador -----------------------------------------------------------------


def test_el_instalador_relanza_farmadex_solo_en_actualizaciones_automaticas():
    iss = (Path(__file__).resolve().parents[1] / "empaquetado" / "instalador.iss").read_text(encoding="utf-8")
    assert "EsActualizacionAutomatica" in iss and "{param:AUTOACTUALIZAR|0}" in iss
    assert "PrepareToInstall" in iss and f"'{instalacion.MUTEX}'" in iss
    assert instalacion.APP_ID in iss.replace("{{", "{")
    entradas = re.findall(r'^Filename: "\{app\}\\\{#NombreApp\}\.exe".*$', iss, re.M)
    assert len(entradas) == 2
    manual = next(e for e in entradas if "postinstall" in e)
    automatica = next(e for e in entradas if "EsActualizacionAutomatica" in e)
    assert "skipifsilent" in manual
    assert "skipifsilent" not in automatica and "postinstall" not in automatica
