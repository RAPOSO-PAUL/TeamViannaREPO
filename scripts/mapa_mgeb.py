#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBO DO MAPA DA CONTA DO PLAYER 1 (MegaEmbed / API Xtream) — 02/11/2026

O QUE FAZ
---------
Baixa UMA vez a lista de filmes e de series da conta (player_api.php,
categoria por categoria — a lista inteira de uma vez da erro 500 no painel)
e grava, na pasta MATRIX/ do repositorio:

    MATRIX/mgeb_filmes.txt
    MATRIX/mgeb_series.txt

no MESMO formato que o app CINE GO! guarda no aparelho (data/XtreamMgeb.kt):

    #gerado<TAB><milissegundos desde 1970>
    <tmdb><TAB><id do video na conta><TAB><extensao><TAB><nome><TAB>

SEM usuario e senha (o ultimo campo, o "direct_source", fica VAZIO): o
repositorio e publico, e o app monta o endereco com os dados dele:
    <servidor>/movie/<usuario>/<senha>/<id>.<extensao>

O app baixa este arquivo (rapido, do GitHub; o GitLab e a reserva) em vez de
cada TV pedir a lista inteira ao painel. Se o arquivo tiver mais de 6 h, o
app volta a pedir ao painel, como antes.

SEGURANCA DO PAINEL (ele bane o IP com falhas seguidas)
-------------------------------------------------------
  • o mesmo nome de navegador do app (um so, sempre o mesmo);
  • uma categoria por vez, com uma pausa entre elas, sem repetir;
  • 401/403/429 em qualquer pedido: PARA TUDO na hora e nao grava nada
    (o arquivo anterior continua valendo);
  • lista com muito menos titulos que a anterior (menos de 60%): nao grava
    (protege contra uma resposta pela metade).

CONFIGURAR (uma vez): em Settings > Secrets and variables > Actions do
repositorio, crie os segredos MGEB_USUARIO e MGEB_SENHA (os mesmos de
USUARIO e SENHA em data/XtreamMgeb.kt). Opcional: MGEB_SERVIDOR (padrao
https://megaembed.com).
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

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "MATRIX")

# o MESMO do app (data/LinkDireto.kt -> AGENTE)
AGENTE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

PAUSA_ENTRE_PEDIDOS = 1.0      # segundos
PRAZO = 90                     # segundos por pedido (a lista de uma categoria pode ser grande)
MINIMO_DA_ANTERIOR = 0.60      # nao grava se vier menos que 60% da lista anterior

TIPOS = [
    # (nome, acao da lista, acao das categorias, campo do id, arquivo)
    ("filmes", "get_vod_streams", "get_vod_categories", "stream_id", "mgeb_filmes.txt"),
    ("séries", "get_series", "get_series_categories", "series_id", "mgeb_series.txt"),
]


class Recusou(Exception):
    """o painel recusou (401/403/429): parar tudo"""


def api(acao, extra=None):
    q = {"username": USUARIO, "password": SENHA, "action": acao}
    if extra:
        q.update(extra)
    return SERVIDOR.rstrip("/") + "/player_api.php?" + urllib.parse.urlencode(q)


def pedir(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": AGENTE,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=PRAZO) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            raise Recusou("HTTP %d" % e.code)
        print("  aviso: HTTP %d" % e.code)
        return None
    except Exception as e:  # rede, json quebrado...
        print("  aviso: %s" % type(e).__name__)
        return None


def texto(v):
    if v is None:
        return ""
    return str(v).strip()


def ler_tipo(nome, acao_lista, acao_cats, campo_id):
    cats = pedir(api(acao_cats))
    if not isinstance(cats, list) or not cats:
        print("%s: as categorias não vieram" % nome)
        return None
    ids_cat = []
    for c in cats:
        cid = texto((c or {}).get("category_id"))
        if cid and cid not in ids_cat:
            ids_cat.append(cid)
    print("%s: %d categorias" % (nome, len(ids_cat)))
    vistos = set()
    saida = []
    falhas = 0
    for i, cid in enumerate(ids_cat):
        time.sleep(PAUSA_ENTRE_PEDIDOS)
        lista = pedir(api(acao_lista, {"category_id": cid}))
        if not isinstance(lista, list):
            falhas += 1
            continue
        for o in lista:
            if not isinstance(o, dict):
                continue
            vid = texto(o.get(campo_id))
            if not vid.isdigit() or vid in vistos:
                continue
            vistos.add(vid)
            tmdb = texto(o.get("tmdb") or o.get("tmdb_id"))
            tmdb = tmdb if tmdb.isdigit() else "0"
            ext = texto(o.get("container_extension")).lstrip(".") or "mp4"
            nm = texto(o.get("name") or o.get("title")).replace("\t", " ").replace("\n", " ")
            saida.append((tmdb, vid, ext, nm))
    print("%s: %d títulos (%d categorias falharam)" % (nome, len(saida), falhas))
    if falhas > len(ids_cat) // 2:
        print("%s: falhas demais — não grava" % nome)
        return None
    return saida


def linhas_da_anterior(caminho):
    try:
        with open(caminho, encoding="utf-8") as f:
            return sum(1 for l in f if l.strip() and not l.startswith("#"))
    except OSError:
        return 0


def gravar(caminho, itens):
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("#gerado\t%d\n" % int(time.time() * 1000))
        for tmdb, vid, ext, nm in itens:
            # ultimo campo (direct_source) VAZIO: sem usuario/senha no arquivo publico
            f.write("%s\t%s\t%s\t%s\t\n" % (tmdb, vid, ext, nm))
    os.replace(tmp, caminho)


def main():
    if not USUARIO or not SENHA:
        print("faltam os segredos MGEB_USUARIO e MGEB_SENHA")
        return 1
    os.makedirs(PASTA, exist_ok=True)
    gravou = 0
    for nome, acao_lista, acao_cats, campo_id, arquivo in TIPOS:
        caminho = os.path.join(PASTA, arquivo)
        try:
            itens = ler_tipo(nome, acao_lista, acao_cats, campo_id)
        except Recusou as e:
            print("o painel RECUSOU (%s) — parando tudo, nada gravado" % e)
            return 1
        if not itens:
            continue
        antes = linhas_da_anterior(caminho)
        if antes and len(itens) < antes * MINIMO_DA_ANTERIOR:
            print("%s: veio %d, a anterior tinha %d — não grava (resposta pela metade?)"
                  % (nome, len(itens), antes))
            continue
        gravar(caminho, itens)
        gravou += 1
        print("%s: gravado %s" % (nome, arquivo))
        time.sleep(PAUSA_ENTRE_PEDIDOS)
    return 0 if gravou else 1


if __name__ == "__main__":
    sys.exit(main())
