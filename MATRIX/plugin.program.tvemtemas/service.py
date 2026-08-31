# -*- coding: utf-8 -*-
"""TV EMINEM - Temas: na PRIMEIRA vez que o aplicativo abre, mostra as telas
de exemplo dos estilos de menu para a pessoa escolher o que preferir."""
import os
import sys

import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
FLAG_ESTILO = "estilo_escolhido.txt"


def ja_escolheu():
    caminho = os.path.join(xbmcvfs.translatePath("special://profile/"),
                           FLAG_ESTILO)
    return os.path.exists(caminho)


def run():
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(25):        # deixa o Kodi assentar
        return
    if ja_escolheu():
        return
    try:
        base = ADDON.getAddonInfo("path")
        sys.argv = ["plugin://plugin.program.tvemtemas/", "-1", "?modo=estilo"]
        _tela = None
        # pacote COMPILADO: o codigo fica em resources/lib/tvemtemas_main_X_Y.pyc
        try:
            import importlib
            sys.path.insert(0, os.path.join(base, "resources", "lib"))
            _tela = importlib.import_module(
                "tvemtemas_main_%d_%d" % (sys.version_info[0],
                                          sys.version_info[1]))
        except Exception:
            _tela = None
        # pacote NAO compilado: o codigo esta no proprio addon.py
        if _tela is None or not hasattr(_tela, "escolher_estilo"):
            sys.path.insert(0, base)
            import addon as _tela
        _tela.escolher_estilo()
    except Exception as exc:
        xbmc.log("[TV EMINEM Temas] escolha de estilo: %s" % exc, xbmc.LOGERROR)


run()
