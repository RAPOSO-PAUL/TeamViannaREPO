#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_estado.py - descobre quem esta ao vivo e publica num arquivo so.

POR QUE ISTO EXISTE
    Sem ele, cada aparelho consulta os canais um por um. Com 500 canais
    sao ate 1500 requisicoes POR USUARIO, e todos chegam ao mesmo
    resultado. Alem de lento, o YouTube comeca a estrangular quem faz
    isso em volume.

    Aqui o trabalho e feito UMA VEZ, num lugar so, e o resultado vai
    para um arquivo de poucos kilobytes. O addon baixa esse arquivo e
    abre na hora, com 50 ou com 5000 canais.

USO
    python gerar_estado.py lives.json estado.json

    Sem argumentos, procura lives.json na pasta atual e grava
    estado.json ao lado.

A logica de deteccao e a mesma do addon (lockupViewModel, abas
/streams e /featured, filtro de recomendacoes). Aqui ela roda fora do
Kodi, sem pressa e sem limite de tempo.
"""

import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# Aqui pode ser generoso: nao ha usuario esperando na frente da TV.
TRABALHADORES = 8
TEMPO_LIMITE = 20
LIMITE_HTML = 3 * 1024 * 1024
PAUSA_ENTRE_LOTES = 1.0     # respira entre os lotes, para nao irritar o YouTube
VALIDADE = 600              # o addon considera o arquivo bom por 10 min

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

RE_CANONICA = re.compile(
    r'<link\s+rel="canonical"\s+href="[^"]*?/channel/(UC[\w-]{20,})"')

# Caixas de recomendacao: nao sao conteudo do canal
CAIXAS_RECOMENDACAO = frozenset([
    'secondaryResults', 'watchNextSecondaryResultsRenderer',
    'watchNextEndScreenRenderer', 'compactVideoRenderer',
    'compactRadioRenderer', 'endScreenVideoRenderer', 'playerOverlayRenderer',
    'playlistPanelRenderer', 'playlistPanelVideoRenderer', 'engagementPanels',
    'relatedChipCloudRenderer', 'shortsLockupViewModel', 'reelShelfRenderer',
    'horizontalCardListRenderer', 'gridChannelRenderer', 'channelRenderer',
    'miniChannelRenderer',
])


# --------------------------------------------------------------------- rede

def baixar(endereco, timeout=TEMPO_LIMITE):
    req = urllib.request.Request(endereco, headers={
        'User-Agent': UA,
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        'Cookie': 'CONSENT=YES+cb; SOCS=CAI',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(LIMITE_HTML).decode('utf-8', 'ignore')


# ------------------------------------------------------- leitura do JSON

def _extrair_json(html, marcador):
    """Pega o objeto JSON depois do marcador, contando chaves."""
    pos = -1
    for m in re.finditer(re.escape(marcador) + r'["\]]?\s*=\s*', html):
        pos = m.end()
        break
    if pos < 0:
        pos = html.find(marcador)
        if pos < 0:
            return None

    inicio = html.find('{', pos)
    if inicio < 0:
        return None

    nivel = 0
    dentro_texto = False
    escapado = False
    for i in range(inicio, min(len(html), inicio + 4000000)):
        c = html[i]
        if dentro_texto:
            if escapado:
                escapado = False
            elif c == '\\':
                escapado = True
            elif c == '"':
                dentro_texto = False
            continue
        if c == '"':
            dentro_texto = True
        elif c == '{':
            nivel += 1
        elif c == '}':
            nivel -= 1
            if nivel == 0:
                try:
                    return json.loads(html[inicio:i + 1])
                except Exception:
                    return None
    return None


def _id_do_no(no):
    """videoRenderer usa videoId; lockupViewModel (layout novo) usa contentId."""
    vid = no.get('videoId')
    if isinstance(vid, str) and len(vid) == 11:
        return vid
    cid = no.get('contentId')
    if isinstance(cid, str) and len(cid) == 11:
        tipo = str(no.get('contentType') or '').upper()
        if not tipo or 'VIDEO' in tipo:
            return cid
    return None


def _estilos_de_selo(no):
    selos = []
    for overlay in (no.get('thumbnailOverlays') or []):
        if not isinstance(overlay, dict):
            continue
        st = overlay.get('thumbnailOverlayTimeStatusRenderer') or {}
        if st.get('style'):
            selos.append(str(st['style']).upper())
        txt = st.get('text') or {}
        if isinstance(txt, dict) and txt.get('simpleText'):
            selos.append(str(txt['simpleText']).upper())

    for badge in (no.get('badges') or []):
        if isinstance(badge, dict):
            mb = badge.get('metadataBadgeRenderer') or {}
            if mb.get('style'):
                selos.append(str(mb['style']).upper())
            if mb.get('label'):
                selos.append(str(mb['label']).upper())

    try:
        ov = (((no.get('contentImage') or {})
               .get('thumbnailViewModel') or {}).get('overlays') or [])
        for o in ov:
            badges = ((o.get('thumbnailOverlayBadgeViewModel') or {})
                      .get('thumbnailBadges') or [])
            for b in badges:
                bv = b.get('thumbnailBadgeViewModel') or {}
                if bv.get('badgeStyle'):
                    selos.append(str(bv['badgeStyle']).upper())
                if bv.get('text'):
                    selos.append(str(bv['text']).upper())
    except Exception:
        pass
    return selos


def _classificar(no):
    """Devolve 'live', 'breve' ou None."""
    if no.get('upcomingEventData'):
        return 'breve'

    texto = ' '.join(_estilos_de_selo(no))
    if 'UPCOMING' in texto or 'EM BREVE' in texto:
        return 'breve'
    if 'LIVE' in texto or 'AO VIVO' in texto or 'DIRETO' in texto:
        return 'live'

    for campo in ('viewCountText', 'shortViewCountText'):
        v = no.get(campo) or {}
        if isinstance(v, dict):
            t = v.get('simpleText') or ''
            if not t:
                runs = v.get('runs') or []
                t = ''.join(r.get('text', '') for r in runs
                            if isinstance(r, dict))
            t = t.upper()
            if 'ASSISTINDO' in t or 'WATCHING' in t:
                return 'live'

    try:
        blob = json.dumps(no, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        return None

    if any(m in blob for m in ('"style":"UPCOMING"', '"iconType":"UPCOMING"',
                               '"upcomingEventData"', '"text":"EM BREVE"')):
        return 'breve'
    if any(m in blob for m in ('"style":"LIVE"', '"iconType":"LIVE"',
                               '"isLiveNow":true', '"text":"AO VIVO"',
                               'BADGE_STYLE_TYPE_LIVE_NOW',
                               'THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE')):
        return 'live'
    return None


def _titulo_do_no(no):
    t = no.get('title') or {}
    if isinstance(t, dict):
        if t.get('simpleText'):
            return t['simpleText']
        if t.get('content'):
            return t['content']
        runs = t.get('runs') or []
        if runs and isinstance(runs[0], dict):
            return runs[0].get('text', '')
    try:
        meta = (no.get('metadata') or {}).get('lockupMetadataViewModel') or {}
        titulo = meta.get('title') or {}
        if titulo.get('content'):
            return titulo['content']
    except Exception:
        pass
    return ''


def _thumb(vid):
    return "https://i.ytimg.com/vi/%s/hqdefault.jpg" % vid


def _dono_diferente(no, dono):
    """True se o item cita OUTRO canal como origem (recomendacao)."""
    if not dono:
        return False
    try:
        blob = json.dumps(no, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        return False
    for campo in ('shortBylineText', 'longBylineText', 'ownerText'):
        i = blob.find('"%s"' % campo)
        if i < 0:
            continue
        m = re.search(r'"browseId":"(UC[\w-]{20,})"', blob[i:i + 1200])
        if m and m.group(1) != dono:
            return True
    return False


def _coletar(no, achados=None, vistos=None, dono=''):
    if achados is None:
        achados = {'live': [], 'breve': []}
    if vistos is None:
        vistos = set()

    if isinstance(no, dict):
        vid = _id_do_no(no)
        if vid and vid not in vistos and not _dono_diferente(no, dono):
            tipo = _classificar(no)
            if tipo:
                vistos.add(vid)
                inicio = 0
                ev = no.get('upcomingEventData') or {}
                if isinstance(ev, dict) and ev.get('startTime'):
                    try:
                        inicio = int(ev['startTime'])
                    except Exception:
                        inicio = 0
                achados[tipo].append({
                    'video_id': vid,
                    'titulo': _titulo_do_no(no),
                    'thumb': _thumb(vid),
                    'inicio': inicio,
                })
        for chave, valor in no.items():
            if chave in CAIXAS_RECOMENDACAO:
                continue
            _coletar(valor, achados, vistos, dono)
    elif isinstance(no, list):
        for v in no:
            _coletar(v, achados, vistos, dono)
    return achados


def _analisar_canal(html):
    m = RE_CANONICA.search(html)
    dono = m.group(1) if m else ''
    dados = _extrair_json(html, 'ytInitialData')
    if not dados:
        return {'live': [], 'breve': []}
    return _coletar(dados, dono=dono)


def _analisar_assistir(html):
    """Pagina de assistir: fala de UM video, e o resto e recomendacao."""
    pr = _extrair_json(html, 'ytInitialPlayerResponse')
    vd = (pr or {}).get('videoDetails') or {}
    vid = vd.get('videoId')
    if not vid:
        return None

    ps = (pr or {}).get('playabilityStatus') or {}
    agendado = (vd.get('isUpcoming') is True
                or ps.get('status') == 'LIVE_STREAM_OFFLINE')

    evento = {'video_id': vid, 'titulo': vd.get('title', ''),
              'thumb': _thumb(vid), 'inicio': 0}

    if agendado:
        try:
            slate = (((ps.get('liveStreamability') or {})
                      .get('liveStreamabilityRenderer') or {})
                     .get('offlineSlate') or {})
            marcado = ((slate.get('liveStreamOfflineSlateRenderer') or {})
                       .get('scheduledStartTime'))
            if marcado:
                evento['inicio'] = int(marcado)
        except Exception:
            pass
        return {'live': [], 'breve': [evento]}

    if vd.get('isLive') is True:
        return {'live': [evento], 'breve': []}
    return {'live': [], 'breve': []}


# ------------------------------------------------------- um canal por vez

def enderecos(canal):
    """(paginas de canal, paginas de assistir), na ordem de tentativa."""
    canal_urls, assistir_urls = [], []

    handle = (canal.get('handle') or canal.get('usuario') or '').strip()
    if handle:
        if not handle.startswith('@'):
            handle = '@' + handle
        h = urllib.parse.quote(handle)
        canal_urls.append("https://www.youtube.com/%s/streams" % h)
        canal_urls.append("https://www.youtube.com/%s/featured" % h)
        assistir_urls.append("https://www.youtube.com/%s/live" % h)

    cid = (canal.get('channel_id') or '').strip()
    if cid.startswith('UC'):
        canal_urls.append("https://www.youtube.com/channel/%s/streams" % cid)
        canal_urls.append("https://www.youtube.com/channel/%s/featured" % cid)
        assistir_urls.append("https://www.youtube.com/channel/%s/live" % cid)

    return canal_urls, assistir_urls


def chave_do_canal(canal):
    """Como o addon vai encontrar este canal no arquivo publicado."""
    handle = (canal.get('handle') or canal.get('usuario') or '').strip()
    if handle:
        if not handle.startswith('@'):
            handle = '@' + handle
        return handle.lower()
    cid = (canal.get('channel_id') or '').strip()
    if cid:
        return cid
    return (canal.get('nome') or '').strip().lower()


def apurar(canal):
    """Descobre o que este canal tem no ar. Devolve o registro publicavel."""
    canal_urls, assistir_urls = enderecos(canal)
    somados = {'live': [], 'breve': []}
    vistos = set()
    erro = ''

    def somar(achados):
        for tipo in ('live', 'breve'):
            for ev in achados.get(tipo) or []:
                if ev['video_id'] in vistos:
                    continue
                vistos.add(ev['video_id'])
                somados[tipo].append(ev)

    for endereco in canal_urls:
        try:
            html = baixar(endereco)
        except Exception as e:
            erro = str(e)[:60]
            continue
        if 'consent.youtube.com' in html[:4000]:
            erro = 'pagina de consentimento'
            continue
        somar(_analisar_canal(html))
        if len(somados['live']) >= 2:
            break

    if not somados['live'] and not somados['breve']:
        for endereco in assistir_urls:
            try:
                html = baixar(endereco)
            except Exception as e:
                erro = str(e)[:60]
                continue
            achado = _analisar_assistir(html)
            if achado:
                somar(achado)
                break

    if somados['live']:
        return {'live': True, 'em_breve': False, 'inicio': 0,
                'eventos': somados['live']}

    if somados['breve']:
        agendados = sorted(somados['breve'],
                           key=lambda e: e['inicio'] or 9999999999)
        return {'live': False, 'em_breve': True,
                'inicio': agendados[0]['inicio'], 'eventos': agendados}

    return {'live': False, 'em_breve': False, 'inicio': 0, 'eventos': [],
            'erro': erro}


# ------------------------------------------------------------------ geracao

def carregar_catalogo(caminho):
    with io.open(caminho, encoding='utf-8') as f:
        dados = json.load(f)

    canais = []
    for cat in (dados.get('categorias') or []):
        for canal in (cat.get('canais') or []):
            if canal.get('handle') or canal.get('channel_id'):
                canais.append(canal)

    # o mesmo canal pode estar em duas categorias: apura uma vez so
    unicos = {}
    for canal in canais:
        unicos.setdefault(chave_do_canal(canal), canal)
    return list(unicos.values())


def gerar(catalogo, saida):
    canais = carregar_catalogo(catalogo)
    total = len(canais)
    print("Canais a apurar: %d" % total)

    resultado = {}
    prontos = 0
    inicio = time.time()

    # em lotes, com uma pausa entre eles: 500 requisicoes seguidas fazem
    # o YouTube comecar a responder devagar ou recusar
    lote = TRABALHADORES * 4
    for comeco in range(0, total, lote):
        parte = canais[comeco:comeco + lote]
        with ThreadPoolExecutor(max_workers=TRABALHADORES) as pool:
            tarefas = {pool.submit(apurar, c): c for c in parte}
            for tarefa in as_completed(tarefas):
                canal = tarefas[tarefa]
                try:
                    resultado[chave_do_canal(canal)] = tarefa.result()
                except Exception as e:
                    resultado[chave_do_canal(canal)] = {
                        'live': False, 'em_breve': False, 'inicio': 0,
                        'eventos': [], 'erro': str(e)[:60]}
                prontos += 1
                print("  %3d/%d  %s" % (prontos, total,
                                        canal.get('nome', '')[:40]))
        if comeco + lote < total:
            time.sleep(PAUSA_ENTRE_LOTES)

    no_ar = sum(1 for v in resultado.values() if v.get('live'))
    agendados = sum(1 for v in resultado.values() if v.get('em_breve'))

    saida_dados = {
        'gerado_em': int(time.time()),
        'validade': VALIDADE,
        'total': total,
        'ao_vivo': no_ar,
        'em_breve': agendados,
        'canais': resultado,
    }

    with io.open(saida, 'w', encoding='utf-8') as f:
        json.dump(saida_dados, f, ensure_ascii=False, separators=(',', ':'))

    tamanho = os.path.getsize(saida)
    print("")
    print("Gerado: %s" % saida)
    print("  %d canais, %d ao vivo, %d agendados" % (total, no_ar, agendados))
    print("  %.1f KB, em %.0f segundos" % (tamanho / 1024.0,
                                           time.time() - inicio))
    return 0


def main():
    catalogo = sys.argv[1] if len(sys.argv) > 1 else 'lives.json'
    saida = sys.argv[2] if len(sys.argv) > 2 else 'estado.json'

    if not os.path.exists(catalogo):
        print("ERRO: nao achei %s" % catalogo)
        return 1
    return gerar(catalogo, saida)


if __name__ == '__main__':
    sys.exit(main())
