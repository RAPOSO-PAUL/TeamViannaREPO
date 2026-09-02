# -*- coding: utf-8 -*-
import os, sys, importlib
import xbmc
try:
    import xbmcaddon, xbmcvfs
    _base = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('path'))
except Exception:
    _base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_base, 'resources', 'lib'))
# garante 'sem handle' pro modulo (nao roda main() no servico)
sys.argv = [sys.argv[0] if sys.argv else 'service']
_mod = 'flixplay_main_%d_%d' % (sys.version_info[0], sys.version_info[1])
try:
    _m = importlib.import_module(_mod)
except Exception:
    _m = None
_monitor = xbmc.Monitor()
# espera o Kodi assentar antes de aquecer (respeita o desligamento)
if not _monitor.waitForAbort(45):
    while not _monitor.abortRequested():
        try:
            if _m is not None and hasattr(_m, 'warm_cache'):
                _m.warm_cache()
        except Exception:
            pass
        # re-aquece a cada 6h (barato: quase tudo ja vem do cache)
        if _monitor.waitForAbort(6 * 3600):
            break
