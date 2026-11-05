#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONFERE OS JSON DO CATALOGO DO CINE GO! A CADA ENVIO (05/11).

Por que existe: em 04/11 faltou o "}" no fim do filmes.json. O robo dos
metadados parou com erro e o app podia perder os filmes que vinham depois
do erro — sem ninguem perceber. Agora, a cada envio para o GitHub, este
robo abre os arquivos e, se algum estiver quebrado, AVISA NO TELEGRAM
(arquivo, linha, coluna e as linhas em volta) e o envio fica com o X
vermelho no GitHub.

O QUE ELE CONFERE
  1) se cada .json abre (o erro mais grave: o app para de ler ali);
  2) o formato que o app espera em cada arquivo conhecido:
       filmes.json            {"movies": [ ... ]}
       shows.json             {"shows":  [ ... ]}
       series.json            {"shows": "<url>", "series": ["<url>", ...]}
       SERIES-CINE-GO.json    {"series": [ {tmdb_id, episodes: [...]}, ... ]}
       vidara.json            "filme:<tmdb>" / "serie:<tmdb>:<t>:<e>"
       (os arquivos de cada serie, no SERIES-FLIX-PLAY: tmdb_id + episodes)
  3) AVISOS (nao travam): data "added_at" fora do formato aaaa-mm-dd,
     tmdb_id repetido, item sem tmdb_id, chave de API exposta no JSON
     publico.

USO
  python scripts/validar_json.py                 (a pasta MATRIX)
  python scripts/validar_json.py MATRIX outra/   (pastas ou arquivos)
Telegram: segredos TELEGRAM_TOKEN e TELEGRAM_CHAT (opcionais — sem eles,
so o X vermelho e o registro do GitHub).
Saida: 0 = tudo certo; 1 = algum arquivo com ERRO.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

RX_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}")
RX_CHAVE_VIDARA = re.compile(r"^(filme|movie|f):\d+$|^(serie|série|tv|s):\d+:\d+:\d+$", re.I)

erros = []      # (arquivo, texto)
avisos = []     # (arquivo, texto)


def erro(arq, txt):
    erros.append((arq, txt))


def aviso(arq, txt):
    avisos.append((arq, txt))


def em_volta(texto, linha, coluna):
    """as linhas em volta do erro, com a seta na coluna"""
    linhas = texto.split("\n")
    saida = []
    for i in range(max(0, linha - 3), min(len(linhas), linha + 1)):
        trecho = linhas[i].rstrip()
        if len(trecho) > 140:
            # linha enorme (magnet): mostra so o pedaco perto da coluna
            ini = max(0, (coluna - 70) if i == linha - 1 else 0)
            trecho = ("…" if ini else "") + trecho[ini:ini + 140] + "…"
        saida.append(f"  {i + 1:>7} | {trecho}")
        if i == linha - 1:
            col = min(coluna, 70) if len(linhas[i]) > 140 else coluna
            saida.append("          | " + " " * max(0, col - 1) + "^ aqui")
    return "\n".join(saida)


def abrir(caminho):
    nome = os.path.basename(caminho)
    try:
        with open(caminho, "r", encoding="utf-8-sig") as f:
            texto = f.read()
    except UnicodeDecodeError as e:
        erro(nome, f"o arquivo nao esta em UTF-8 ({e})")
        return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        dica = ""
        if "Expecting ',' delimiter" in e.msg:
            dica = " — falta uma VIRGULA antes deste ponto (ou um } / ] no fim do arquivo)"
        elif "Expecting property name" in e.msg:
            dica = " — virgula sobrando antes de um } (ou aspas faltando no nome do campo)"
        elif "Expecting value" in e.msg:
            dica = " — virgula sobrando antes de um ] ou valor vazio"
        elif "Extra data" in e.msg:
            dica = " — tem coisa depois do fim do JSON (um } ou ] a mais?)"
        fim = " (o FIM do arquivo)" if e.pos >= len(texto.rstrip()) else ""
        erro(nome, f"JSON QUEBRADO na linha {e.lineno}, coluna {e.colno}{fim}: {e.msg}{dica}\n"
                   + em_volta(texto, e.lineno, e.colno))
        return None


def tmdb_de(o):
    for k in ("tmdb_id", "tmdbId", "id"):
        v = o.get(k)
        if isinstance(v, int) and v > 0:
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
    return None


def conferir_data(nome, o, onde):
    d = o.get("added_at")
    if d is not None and not (isinstance(d, str) and RX_DATA.match(d.strip())):
        aviso(nome, f"{onde}: added_at \"{d}\" fora do formato aaaa-mm-dd (a ordem por data nao vale para ele)")


def conferir_lista_de_titulos(nome, lista, chave, serie):
    if not isinstance(lista, list):
        erro(nome, f"\"{chave}\" tinha de ser uma LISTA [ ... ]")
        return
    vistos = {}
    for i, o in enumerate(lista):
        onde = f"{chave}[{i}]"
        if not isinstance(o, dict):
            erro(nome, f"{onde}: cada item tem de ser um objeto {{ ... }}")
            continue
        t = tmdb_de(o)
        if t is None:
            aviso(nome, f"{onde}: sem tmdb_id (\"{str(o.get('title') or o.get('name') or '?')[:40]}\")")
        else:
            if t in vistos:
                aviso(nome, f"{onde}: tmdb_id {t} REPETIDO (o mesmo de {vistos[t]})")
            else:
                vistos[t] = onde
        conferir_data(nome, o, onde + (f" (tmdb {t})" if t else ""))
        k = o.get("kids")
        if k is not None and not isinstance(k, (list, str)):
            erro(nome, f"{onde}: \"kids\" tem de ser texto ou lista de textos")
        tipo = str(o.get("type") or "").lower()
        if serie is False and tipo in ("tv", "serie", "série", "show"):
            aviso(nome, f"{onde} (tmdb {t}): type \"{tipo}\" dentro da lista de FILMES")
        eps = o.get("episodes")
        if eps is not None:
            if not isinstance(eps, list):
                erro(nome, f"{onde}: \"episodes\" tem de ser uma lista")
            else:
                for j, e in enumerate(eps):
                    if not isinstance(e, dict):
                        erro(nome, f"{onde}.episodes[{j}]: cada episodio tem de ser um objeto")
                        continue
                    if not str(e.get("season", "")).strip().isdigit() or not str(e.get("episode", "")).strip().isdigit():
                        erro(nome, f"{onde} (tmdb {t}).episodes[{j}]: season/episode tem de ser NUMERO (ex.: 1 e 2)")
        fontes = o.get("sources")
        if fontes is not None and not isinstance(fontes, list):
            erro(nome, f"{onde}: \"sources\" tem de ser uma lista")


def conferir_vidara(nome, d):
    if not isinstance(d, dict):
        erro(nome, "o vidara.json tem de ser um objeto { ... }")
        return
    for k, v in d.items():
        if k.startswith("_"):
            continue
        if not RX_CHAVE_VIDARA.match(k.strip()):
            erro(nome, f"chave \"{k}\": o certo e filme:<tmdb> ou serie:<tmdb>:<temporada>:<episodio>")
        if not isinstance(v, (dict, str, list)):
            erro(nome, f"\"{k}\": o valor tem de ser {{ ... }}, um codigo ou uma lista")
        if isinstance(v, dict) and not any(str(v.get(p, "")).strip() for p in
                                           ("vidara", "uqload", "lulu", "streamtape", "codigo", "url")):
            aviso(nome, f"\"{k}\": nenhum codigo preenchido (a opcao nao aparece no app)")


def conferir_chaves_expostas(nome, d):
    if not isinstance(d, dict):
        return
    for k in ("legendas_online", "legendasonline", "legendas_internet", "legendas_api"):
        v = d.get(k)
        if isinstance(v, dict):
            for site in ("wyzie", "subdl", "opensubtitles"):
                if str(v.get(site, "")).strip():
                    aviso(nome, f"CHAVE EXPOSTA: \"{k}.{site}\" esta no JSON PUBLICO — "
                                f"tire daqui (o app ja tem a dele) e troque a chave no site")


def conferir(caminho):
    nome = os.path.basename(caminho)
    d = abrir(caminho)
    if d is None:
        return
    n = nome.lower()
    if n == "filmes.json":
        if not isinstance(d, dict) or "movies" not in d:
            erro(nome, "tinha de ser {\"movies\": [ ... ]}")
        else:
            conferir_lista_de_titulos(nome, d["movies"], "movies", False)
    elif n == "shows.json":
        lista = d.get("shows") if isinstance(d, dict) else d
        conferir_lista_de_titulos(nome, lista, "shows", True)
    elif n == "series.json":
        if not isinstance(d, dict) or not isinstance(d.get("series"), list):
            erro(nome, "tinha de ser {\"shows\": \"<url>\", \"series\": [\"<url>\", ...]}")
        else:
            for i, u in enumerate(d["series"]):
                if not (isinstance(u, str) and u.startswith("http")):
                    erro(nome, f"series[{i}]: tinha de ser o endereco (https://...) do arquivo da serie")
            repetidos = {u for u in d["series"] if d["series"].count(u) > 1}
            for u in sorted(repetidos)[:10]:
                aviso(nome, f"link repetido: {u}")
    elif n == "vidara.json":
        conferir_vidara(nome, d)
    elif n in ("metadados.json", "tema-pronto.json", "canais.json", "guia.json"):
        pass   # so precisa abrir (o formato e do robo / tem o seu proprio)
    elif isinstance(d, dict) and isinstance(d.get("series"), list):
        conferir_lista_de_titulos(nome, d["series"], "series", True)       # SERIES-CINE-GO.json
    elif isinstance(d, dict) and "episodes" in d:
        conferir_lista_de_titulos(nome, [d], "serie", True)                # arquivo de UMA serie
    conferir_chaves_expostas(nome, d)


def avisar_telegram(texto):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT", "").strip()
    if not token or not chat:
        print("(sem TELEGRAM_TOKEN / TELEGRAM_CHAT: aviso so no GitHub)")
        return
    dados = urllib.parse.urlencode({"chat_id": chat, "text": texto[:3900],
                                    "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", dados, timeout=20).read()
        print("aviso enviado no Telegram")
    except Exception as e:
        print(f"nao consegui avisar no Telegram: {e}")


def main():
    alvos = sys.argv[1:] or ["MATRIX"]
    arquivos = []
    for a in alvos:
        if os.path.isdir(a):
            for raiz, _, nomes in os.walk(a):
                arquivos += [os.path.join(raiz, x) for x in sorted(nomes) if x.lower().endswith(".json")]
        elif a.lower().endswith(".json") and os.path.isfile(a):
            arquivos.append(a)
    print(f"conferindo {len(arquivos)} arquivo(s) .json")
    for c in arquivos:
        conferir(c)

    for arq, txt in avisos[:200]:
        print(f"AVISO  {arq}: {txt}")
    if len(avisos) > 200:
        print(f"... e mais {len(avisos) - 200} aviso(s)")
    for arq, txt in erros:
        print(f"ERRO   {arq}: {txt}")

    if erros:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        commit = os.environ.get("GITHUB_SHA", "")[:7]
        cab = f"⚠ CINE GO — JSON com ERRO no {repo or 'catálogo'}" + (f" (envio {commit})" if commit else "")
        corpo = "\n\n".join(f"• {a}: {t}" for a, t in erros[:6])
        if len(erros) > 6:
            corpo += f"\n\n... e mais {len(erros) - 6} erro(s) — veja o registro no GitHub (Actions)."
        avisar_telegram(cab + "\n\nO app pode parar de ler o arquivo no ponto do erro. Conserte e envie de novo.\n\n" + corpo)
        sys.exit(1)
    print(f"tudo certo ({len(avisos)} aviso(s), nenhum erro)")


if __name__ == "__main__":
    main()
