

def test_temporal_propio_de_cada_proceso(tmp_path):
    """Dos Farmadex descargando a la vez no deben compartir el .tmp (WinError 32)."""
    import os
    from farmadex.ficheros import temporal_de

    t = temporal_de(tmp_path / "Mods.json")
    assert t.parent == tmp_path and str(os.getpid()) in t.name and t.name.endswith(".tmp")
