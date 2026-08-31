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
        sys.path.insert(0, base)
        sys.argv = ["plugin://plugin.program.tvemtemas/", "-1", "?modo=estilo"]
        import addon as _tela
        _tela.escolher_estilo()
    except Exception as exc:
        xbmc.log("[TV EMINEM Temas] escolha de estilo: %s" % exc, xbmc.LOGERROR)


run()
