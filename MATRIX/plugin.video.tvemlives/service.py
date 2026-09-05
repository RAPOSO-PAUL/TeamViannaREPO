# -*- coding: utf-8 -*-
import os
import sys
import importlib.util

import xbmc
import xbmcaddon
import xbmcvfs

_base = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("path"))
_lib = os.path.join(_base, "resources", "lib")
_nome = "tvemlives_main_%d_%d.pyc" % sys.version_info[:2]
_caminho = os.path.join(_lib, _nome)

_m = None
if os.path.exists(_caminho):
    if _lib not in sys.path:
        sys.path.insert(0, _lib)
    try:
        _spec = importlib.util.spec_from_file_location("tvemlives_main", _caminho)
        _m = importlib.util.module_from_spec(_spec)
        sys.modules["tvemlives_main"] = _m
        # sem handle nos argumentos, o modulo NAO roda main() ao importar
        _spec.loader.exec_module(_m)
    except Exception as e:
        xbmc.log("[AO VIVO] service nao carregou: %s" % e, xbmc.LOGERROR)
else:
    xbmc.log("[AO VIVO] service: falta %s" % _nome, xbmc.LOGERROR)


if __name__ == "__main__":
    # o laco (pre-carregamento + sincronia) vive no modulo compilado
    if _m:
        _m.rodar_servico()
