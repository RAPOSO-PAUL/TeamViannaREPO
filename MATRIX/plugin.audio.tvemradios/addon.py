# -*- coding: utf-8 -*-
import os
import sys
import importlib.util

import xbmc
import xbmcaddon
import xbmcvfs

_base = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("path"))
_lib = os.path.join(_base, "resources", "lib")
_nome = "tvemradios_main_%d_%d.pyc" % sys.version_info[:2]
_caminho = os.path.join(_lib, _nome)

if not os.path.exists(_caminho):
    xbmc.log("[RADIOS] falta %s" % _nome, xbmc.LOGERROR)
    import xbmcgui
    xbmcgui.Dialog().ok(
        "RADIOS BRASIL",
        "Esta versao do Kodi usa o Python %d.%d, que nao veio neste "
        "pacote.\n\nBaixe a versao atualizada do complemento."
        % sys.version_info[:2])
else:
    if _lib not in sys.path:
        sys.path.insert(0, _lib)
    _spec = importlib.util.spec_from_file_location("tvemradios_main", _caminho)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["tvemradios_main"] = _mod
    # o modulo chama main() sozinho quando ha handle (contexto de plugin)
    _spec.loader.exec_module(_mod)
