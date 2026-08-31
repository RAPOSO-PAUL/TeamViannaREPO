# -*- coding: utf-8 -*-
import os, sys, importlib
try:
    import xbmcaddon, xbmcvfs
    _base = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('path'))
except Exception:
    _base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_base, 'resources', 'lib'))
_mod = 'tvemtemas_main_%d_%d' % (sys.version_info[0], sys.version_info[1])
try:
    _m = importlib.import_module(_mod)
    _modo = ''
    try:
        if len(sys.argv) > 2 and 'estilo' in sys.argv[2].lower():
            _modo = 'estilo'
    except Exception:
        pass
    if _modo == 'estilo' and hasattr(_m, 'escolher_estilo'):
        _m.escolher_estilo()
    elif hasattr(_m, 'menu_principal'):
        _m.menu_principal()
    elif hasattr(_m, 'escolher'):
        _m.escolher()
except Exception:
    try:
        import xbmcgui
        xbmcgui.Dialog().ok('TV EMINEM - Temas',
            'Sem bytecode para Python %d.%d neste pacote. '
            'Recompile incluindo essa versao.'
            % (sys.version_info[0], sys.version_info[1]))
    except Exception:
        pass
    raise
