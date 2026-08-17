# -*- coding: utf-8 -*-
import os, sys, importlib
try:
    import xbmcaddon, xbmcvfs
    _base = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('path'))
except Exception:
    _base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_base, 'resources', 'lib'))
_mod = 'flixplay_main_%d_%d' % (sys.version_info[0], sys.version_info[1])
try:
    importlib.import_module(_mod)  # executa ao importar
except Exception:
    try:
        import xbmcgui
        xbmcgui.Dialog().ok('FLIX PLAY',
            'Sem bytecode para Python %d.%d neste pacote. '
            'Recompile incluindo essa versao.'
            % (sys.version_info[0], sys.version_info[1]))
    except Exception:
        pass
    raise
