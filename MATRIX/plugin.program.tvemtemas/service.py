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


def tirar_clima():
    """Tira o clima do cabecalho e desliga a busca da previsao.

    Aquele "Ocupado" com a nuvem no arranque e o Kodi buscando a previsao
    do tempo — e isso atrasa o carregamento inicial. Feito UMA vez."""
    marca = os.path.join(xbmcvfs.translatePath("special://profile/"),
                         "clima_desligado.txt")
    if os.path.exists(marca):
        return
    try:
        # 1) esconde o clima no cabecalho (opcao que a propria skin tem)
        xbmc.executebuiltin("Skin.SetBool(disable.weatherheader)")
        # 2) desliga o servico de previsao: sem isso o Kodi continua buscando
        import json
        xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "Settings.SetSettingValue",
            "params": {"setting": "weather.addon", "value": ""}}))
        with open(marca, "w", encoding="utf-8") as f:
            f.write("ok")
        log("clima removido do cabecalho e busca desligada")
    except Exception as exc:
        log("nao consegui tirar o clima: %s" % exc)


def run():
    monitor = xbmc.Monitor()

    # Comeca JA: assim que o Kodi abre (ou logo depois de instalar o addon,
    # porque o Kodi inicia o servico na hora). Sem esperar o primeiro uso.
    if monitor.waitForAbort(3):
        return
    tirar_clima()
    precarregar_imagens()

    # a escolha de ESTILO so existe na TV EMINEM (a Estuary nao tem estilos)
    try:
        with open(os.path.join(xbmcvfs.translatePath("special://profile/"),
                               "app_escolhido.txt"), encoding="utf-8") as f:
            _app = f.read().strip()
    except Exception:
        _app = ""
    if _app == "estuary":
        return

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
