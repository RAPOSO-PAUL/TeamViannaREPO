#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBO DOS EPISODIOS DO MGB (PLAYER 1 / conta do MegaEmbed) — 17/11/2026

(20/11) AGORA TODAS AS SERIES DA CONTA (com tmdb): as do catalogo na frente
da fila; as outras viram titulos novos no app pelo robo catalogo_apis.py
(quando ja tiverem episodio). As que so estao na conta: reconferidas a cada
7 dias (as do catalogo, 3).

O QUE FAZ
---------
Para cada SERIE (e novela) do catalogo do CINE GO! que esta na conta do
mgeb, le a ficha dela (player_api.php?action=get_series_info) e grava:

    MATRIX/mgeb_episodios.txt

    #gerado<TAB><milissegundos desde 1970>
    <tmdb><TAB><temporada><TAB><episodios, ex.: 1-8,10>

O app (data/MgebNoCatalogo.kt) le este arquivo e poe o MGB em cada episodio
da lista — o episodio que o catalogo nao tinha passa a existir na serie.
SEM usuario, senha ou endereco de video: so os numeros (o repositorio e
publico; no clique o app pega o video pela conta, como sempre).

DE ONDE VEM CADA COISA (tudo do proprio repositorio, sem pedir ao painel)
------------------------------------------------------------------------
  • as series do catalogo: MATRIX/shows.json e MATRIX/NOVELAS.json (tmdb_id);
  • o numero de cada serie na conta: MATRIX/mgeb_series.txt (do robo
    mapa_mgeb.py) — o PRIMEIRO de cada tmdb, igual ao app.
So a FICHA de cada serie e pedida ao painel.

SEGURANCA DO PAINEL (ele bane o IP com 3 falhas em 10 min)
----------------------------------------------------------
  • UM pedido por vez, com pausa entre eles, o mesmo nome de navegador do app;
  • no maximo LIMITE fichas por rodada (e PRAZO minutos): a primeira leitura
    completa leva algumas rodadas, e depois so o que precisa:
      1. serie nova no catalogo (ou que mudou de numero na conta) — na hora;
      2. serie "ativa" (ganhou episodio nos ultimos 21 dias) — a cada 6 h;
      3. as outras — a cada 3 dias;
  • 401/403/429 ou "auth 0": PARA TUDO na hora (sem repetir);
  • qualquer outra falha (520-524, prazo, rede...): para ESTA rodada na
    hora (sem repetir) — a proxima rodada continua de onde parou;
  • o progresso fica em .robo_mgeb/episodios.json (gravado no repositorio:
    nada se perde se a rodada for cortada);
  • ficha que vem vazia de uma serie que tinha episodios: mantem os de antes.

CONFIGURAR: os MESMOS segredos do mapa_mgeb.py (MGEB_USUARIO, MGEB_SENHA e,
opcional, MGEB_SERVIDOR). Nada novo.

SAIDA: 0 = ok; 1 = recusou / faltou configurar; 2 = o painel nao respondeu
       e nada foi lido (o workflow tenta pelo tunel WARP).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SERVIDOR = os.environ.get("MGEB_SERVIDOR", "").strip() or "https://megaembed.com"
USUARIO = os.environ.get("MGEB_USUARIO", "").strip()
SENHA = os.environ.get("MGEB_SENHA", "").strip()

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MATRIX = os.path.join(RAIZ, "MATRIX")
SAIDA = os.path.join(MATRIX, "mgeb_episodios.txt")
ESTADO = os.path.join(RAIZ, ".robo_mgeb", "episodios.json")

# o MESMO do app (data/LinkDireto.kt -> AGENTE) e do mapa_mgeb.py
AGENTE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

LIMITE = int(os.environ.get("MGEB_EPISODIOS_LIMITE", "200"))   # fichas por rodada
PAUSA = 2.5                    # segundos entre um pedido e outro
PRAZO_PEDIDO = 30              # segundos por ficha
PRAZO = 12 * 60                # segundos de pedidos por rodada
HORA = 3600 * 1000
ATIVA_MS = 21 * 24 * HORA      # ganhou episodio ha menos disto = "ativa"
RELER_ATIVA_MS = 6 * HORA
RELER_MS = 3 * 24 * HORA
RELER_FORA_MS = 7 * 24 * HORA  # (20/11) as que so estao na conta (nao no seu JSON)


class Recusou(Exception):
    """o painel recusou: parar tudo"""


class NaoRespondeu(Exception):
    """falha que nao e recusa (52x, prazo, rede, JSON quebrado): parar esta rodada"""


def agora_ms():
    return int(time.time() * 1000)


def api(acao, extra=None):
    q = {"username": USUARIO, "password": SENHA, "action": acao}
    if extra:
        q.update(extra)
    return SERVIDOR.rstrip("/") + "/player_api.php?" + urllib.parse.urlencode(q)


def pedir(url):
    """um pedido, SEM repetir"""
    req = urllib.request.Request(url, headers={
        "User-Agent": AGENTE,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=PRAZO_PEDIDO) as r:
            dados = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            raise Recusou("HTTP %d" % e.code)
        raise NaoRespondeu("HTTP %d" % e.code)
    except ValueError as e:
        raise NaoRespondeu("resposta não é JSON (%s)" % type(e).__name__)
    except Exception as e:
        raise NaoRespondeu(type(e).__name__)
    if isinstance(dados, dict):
        ui = dados.get("user_info")
        if isinstance(ui, dict) and str(ui.get("auth", "1")) == "0":
            raise Recusou("auth 0")
    return dados


def inteiro(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# O CATALOGO E A CONTA (arquivos do repositorio)
# ---------------------------------------------------------------------

def series_do_catalogo():
    """tmdb -> added_at ('' se nao tiver)"""
    saida = {}
    for arquivo, chave in (("shows.json", "shows"), ("NOVELAS.json", "series")):
        try:
            with open(os.path.join(MATRIX, arquivo), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            print("aviso: %s não foi lido (%s)" % (arquivo, type(e).__name__))
            continue
        lista = d.get(chave) if isinstance(d, dict) else d
        for o in lista or []:
            if not isinstance(o, dict):
                continue
            t = inteiro(o.get("tmdb_id") or o.get("tmdbId") or o.get("id"))
            if t and t > 0:
                saida.setdefault(t, str(o.get("added_at") or ""))
    return saida


def series_da_conta():
    """tmdb -> series_id (o PRIMEIRO de cada tmdb, como o app)"""
    saida = {}
    try:
        with open(os.path.join(MATRIX, "mgeb_series.txt"), encoding="utf-8") as f:
            for l in f:
                if not l.strip() or l.startswith("#"):
                    continue
                p = l.rstrip("\n").split("\t")
                t, sid = inteiro(p[0]), inteiro(p[1]) if len(p) > 1 else None
                if t and t > 0 and sid and sid > 0 and t not in saida:
                    saida[t] = sid
    except OSError:
        pass
    return saida


# ---------------------------------------------------------------------
# A FICHA
# ---------------------------------------------------------------------

def episodios_da_ficha(dados):
    """{temporada: [episodios]} da ficha (episodes = dict por temporada ou lista)"""
    todos = []
    eps = dados.get("episodes") if isinstance(dados, dict) else None
    if isinstance(eps, dict):
        for k, lista in eps.items():
            for o in lista or []:
                if isinstance(o, dict):
                    todos.append((o.get("season", k), o))
    elif isinstance(eps, list):
        for item in eps:
            if isinstance(item, list):
                todos.extend((o.get("season"), o) for o in item if isinstance(o, dict))
            elif isinstance(item, dict):
                todos.append((item.get("season"), item))
    saida = {}
    for temporada, o in todos:
        t = inteiro(temporada)
        e = inteiro(o.get("episode_num", o.get("episode")))
        if t is None or t < 0 or e is None or e < 1:
            continue
        saida.setdefault(t, set()).add(e)
    return {t: sorted(v) for t, v in saida.items()}


def faixas(numeros):
    """[1,2,3,5] -> '1-3,5'"""
    partes = []
    i = 0
    while i < len(numeros):
        j = i
        while j + 1 < len(numeros) and numeros[j + 1] == numeros[j] + 1:
            j += 1
        partes.append(str(numeros[i]) if i == j else "%d-%d" % (numeros[i], numeros[j]))
        i = j + 1
    return ",".join(partes)


# ---------------------------------------------------------------------
# ESTADO E SAIDA
# ---------------------------------------------------------------------

def ler_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("series", {}) if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_estado(series):
    os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"versao": 1, "series": series}, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    os.replace(tmp, ESTADO)


def corpo_da_saida(series, alvo):
    linhas = []
    for t in sorted(alvo):
        s = series.get(str(t))
        if not s:
            continue
        eps = s.get("eps") or {}
        for temporada in sorted(eps, key=lambda x: int(x)):
            if eps[temporada]:
                linhas.append("%d\t%s\t%s\n" % (t, temporada, eps[temporada]))
    return "".join(linhas)


def gravar_saida(corpo):
    """grava so se mudou (o #gerado novo faz o app baixar de novo)"""
    try:
        with open(SAIDA, encoding="utf-8") as f:
            antes = "".join(l for l in f if not l.startswith("#"))
    except OSError:
        antes = None
    if antes == corpo:
        print("mgeb_episodios.txt: igual — não grava")
        return False
    os.makedirs(MATRIX, exist_ok=True)
    tmp = SAIDA + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("#gerado\t%d\n" % agora_ms())
        f.write(corpo)
    os.replace(tmp, SAIDA)
    print("mgeb_episodios.txt: gravado (%d linhas)" % corpo.count("\n"))
    return True


# ---------------------------------------------------------------------

def fila(alvo, conta, catalogo, series, agora):
    novas, ativas, outras = [], [], []
    for t in alvo:
        s = series.get(str(t))
        if not s or s.get("id") != conta[t]:
            novas.append(t)
            continue
        lido = s.get("lido", 0)
        if agora - s.get("mudou", 0) < ATIVA_MS:
            if agora - lido >= RELER_ATIVA_MS:
                ativas.append(t)
        elif agora - lido >= (RELER_MS if t in catalogo else RELER_FORA_MS):
            outras.append(t)
    # (20/11) as do catalogo primeiro (as mais novas dele na frente); depois as
    # que so estao na conta (robo catalogo_apis.py), as de numero maior antes
    novas.sort(key=lambda t: (t in catalogo, catalogo.get(t, ""), conta[t]), reverse=True)
    ativas.sort(key=lambda t: series[str(t)].get("lido", 0))
    outras.sort(key=lambda t: series[str(t)].get("lido", 0))
    return novas, ativas, outras


def main():
    if not USUARIO or not SENHA:
        print("faltam os segredos MGEB_USUARIO e MGEB_SENHA")
        return 1
    catalogo = series_do_catalogo()
    conta = series_da_conta()
    # (20/11) TODAS as series da conta com tmdb (as do catalogo vao na frente da
    # fila): o robo catalogo_apis.py poe no app as que tem episodio
    no_catalogo = [t for t in catalogo if t in conta]
    alvo = no_catalogo + [t for t in conta if t not in catalogo]
    print("séries no catálogo: %d · na conta do mgeb: %d (do catálogo: %d)" % (len(catalogo), len(alvo), len(no_catalogo)))
    if not conta:
        print("MATRIX/mgeb_series.txt vazio ou ausente — nada a fazer (o mapa_mgeb.py ainda não rodou?)")
        return 0
    series = ler_estado()
    # (20/11) fora da conta: sai do estado (fora do catalogo continua: o robo
    # catalogo_apis.py poe no app as series da conta que tem episodio)
    for k in [k for k in series if inteiro(k) not in conta]:
        del series[k]

    agora = agora_ms()
    novas, ativas, outras = fila(alvo, conta, catalogo, series, agora)
    pendentes = novas + ativas + outras
    print("na fila: %d novas · %d ativas · %d para reconferir (lê até %d)"
          % (len(novas), len(ativas), len(outras), LIMITE))

    lidas = mudaram = 0
    codigo = 0
    comeco = time.time()
    try:
        for n, t in enumerate(pendentes[:LIMITE]):
            if time.time() - comeco > PRAZO:
                print("prazo da rodada — o resto fica para a próxima")
                break
            if n:
                time.sleep(PAUSA)
            sid = conta[t]
            dados = pedir(api("get_series_info", {"series_id": str(sid)}))
            eps = episodios_da_ficha(dados)
            novo = {str(k): faixas(v) for k, v in eps.items()}
            s = series.get(str(t)) or {}
            velho = s.get("eps") if s.get("id") == sid else None
            if not novo and velho:
                print("  %d: ficha veio sem episódios — mantém os de antes" % t)
                novo = velho
            mudou = novo != (velho or {})
            series[str(t)] = {
                "id": sid,
                "lido": agora_ms(),
                "mudou": agora_ms() if (mudou and velho is not None) else s.get("mudou", 0),
                "eps": novo,
            }
            lidas += 1
            if mudou:
                mudaram += 1
            if lidas % 25 == 0:
                gravar_estado(series)
                print("  %d fichas lidas..." % lidas)
    except Recusou as e:
        print("o painel RECUSOU (%s) — parando tudo" % e)
        codigo = 1
    except NaoRespondeu as e:
        print("o painel não respondeu (%s) — parando esta rodada (sem repetir)" % e)
        if lidas == 0:
            codigo = 2

    gravar_estado(series)
    gravar_saida(corpo_da_saida(series, alvo))
    faltam = len([t for t in alvo if str(t) not in series])
    print("fichas lidas: %d · mudaram: %d · ainda nunca lidas: %d" % (lidas, mudaram, faltam))
    return codigo


if __name__ == "__main__":
    sys.exit(main())
