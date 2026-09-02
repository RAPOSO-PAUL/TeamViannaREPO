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


def precarregar_imagens(forcar=False):
    """Baixa antes as imagens dos temas e do menu, para abrirem na hora."""
    try:
        base = ADDON.getAddonInfo("path")
        if base not in sys.path:
            sys.path.insert(0, base)
        _mod = None
        try:
            import importlib
            lib = os.path.join(base, "resources", "lib")
            if lib not in sys.path:
                sys.path.insert(0, lib)
            _mod = importlib.import_module(
                "tvemtemas_main_%d_%d" % (sys.version_info[0],
                                          sys.version_info[1]))
        except Exception:
            _mod = None
        if _mod is None or not hasattr(_mod, "precarregar"):
            import addon as _mod
        _mod.precarregar(forcar)
    except Exception as exc:
        xbmc.log("[TV EMINEM Temas] pre-carregamento: %s" % exc, xbmc.LOGERROR)


def run():
    monitor = xbmc.Monitor()

    # Comeca JA: assim que o Kodi abre (ou logo depois de instalar o addon,
    # porque o Kodi inicia o servico na hora). Sem esperar o primeiro uso.
    if monitor.waitForAbort(3):
        return
    precarregar_imagens()

    if not ja_escolheu():
        if monitor.waitForAbort(15):    # a escolha de estilo espera a interface
            return
        _mostrar_escolha()

    # dai em diante, atualiza a cada 10 minutos
    while not monitor.abortRequested():
        if monitor.waitForAbort(600):
            break
        precarregar_imagens()


def _mostrar_escolha():
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
