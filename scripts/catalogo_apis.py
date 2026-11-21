#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBO DO CATALOGO DAS APIS (RedeMuvi + mgeb) — 20/11/2026

O QUE FAZ
---------
Todo filme e serie das contas (RedeMuvi e mgeb) COM tmdb entra sozinho no
CINE GO!. O JSON de voces continua valendo: magnets, embeds, kids, colecoes,
provider... SOMAM com o daqui pelo tmdb (o app ja junta titulos repetidos).

Grava (tudo em MATRIX/apis/):
    apis.json      a "porta": aponta para os outros (ponha UMA linha no JSON
                   raiz do catalogo:  "apis": ".../MATRIX/apis/apis.json")
    filmes.json    os filmes das APIs que NAO estao no seu filmes.json
    series.json    as series das APIs que NAO estao no seu shows.json/NOVELAS.json
                   (so as que ja tem episodio nos mapas)
    novelas.json   idem, as que sao NOVELA (o app poe na categoria Novelas)
    marcas.json    "so_marca": os titulos do SEU JSON que sao ANIME (o app so
                   marca; nunca cria titulo por aqui)

As FONTES nao vao nestes arquivos: o app ja poe o REDEMUVI e o MGB sozinho
(pelos mapas redemuvi_*.txt, mgeb_*.txt e mgeb_episodios.txt).

CLASSIFICACAO (TMDB, um pedido por titulo, guardado para sempre)
----------------------------------------------------------------
  • ADULTO: fica de fora ("adult" do TMDB, ou palavra de adulto no nome).
  • ANIME: genero Animacao + japones (idioma original ou pais), ou a
    palavra-chave "anime". Anime NUNCA vai para infantil.
  • NOVELA (series): genero "Soap" do TMDB, ou 1-2 temporadas com 50+
    episodios numa so, de pais de novela (BR, MX, CO, AR, TR, PT...).
  • INFANTIL (so animacao que nao e anime), pela classificacao do TMDB:
        BR L            -> Chefinhos + Prezinhos
                           (EUA TV-Y / pre-escola -> so Chefinhos;
                            EUA TV-Y7 -> so Prezinhos)
        BR 10 / 12      -> Aborrecentes
        BR 14, 16, 18   -> fora do infantil (animacao adulta)
        sem a do Brasil, a dos EUA:
            TV-Y -> Chefinhos | G, TV-G -> Chefinhos + Prezinhos
            TV-Y7, PG -> Prezinhos | TV-PG, PG-13 -> Aborrecentes
            TV-14, TV-MA, R, NC-17 -> fora
        SEM classificacao nenhuma -> fora do infantil (na duvida, nao).
    Os titulos do SEU JSON nao recebem kids/novela automaticos (so a marca
    de anime): o que voces marcam a mao continua mandando.

DATAS E FOLGA
-------------
  • Primeira carga: tudo com data antiga (2020-01-01) — nada aparece como
    novidade. Depois, o que surgir nas APIs entra com a data do dia em que o
    robo viu pela primeira vez.
  • Saiu da API: continua 7 dias (folga) e depois sai do app.

CORRECOES A MAO: MATRIX/apis_correcoes.json (ver o modelo).

SEGREDOS: TMDB_TOKEN (o token de leitura "v4") ou TMDB_KEY (a chave "v3").
Nada das contas e usado aqui (so os mapas publicos do MATRIX).

SAIDA: 0 = ok; 1 = faltou configurar.
"""

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MATRIX = os.path.join(RAIZ, "MATRIX")
PASTA = os.path.join(MATRIX, "apis")
# o que precisa durar (datas de cada titulo): no repositorio, texto pequeno,
# muda no maximo uma vez por dia por titulo
VISTOS = os.path.join(RAIZ, ".robo_apis", "vistos.txt")
# as fichas do TMDB (grandes, refeitas sozinhas se sumirem): no cache do Actions
FICHAS = os.path.join(RAIZ, ".robo_apis_cache", "fichas.json")
CORRECOES = os.path.join(MATRIX, "apis_correcoes.json")

TMDB_BASE = os.environ.get("TMDB_BASE", "").strip() or "https://api.themoviedb.org/3"
TMDB_TOKEN = os.environ.get("TMDB_TOKEN", "").strip()
TMDB_KEY = os.environ.get("TMDB_KEY", "").strip()

JUNTAS = 6                      # pedidos ao TMDB ao mesmo tempo
POR_SEGUNDO = 25                # teto de pedidos por segundo (o TMDB aguenta ~40)
PRAZO = int(os.environ.get("APIS_PRAZO", str(22 * 60)))   # segundos de TMDB por rodada
RECONFERIR_DIAS = 60            # a ficha guardada e conferida de novo depois disto
RECONFERIR_POR_RODADA = 500
FOLGA_DIAS = 7
DATA_ANTIGA = "2020-01-01"

KIDS_MENOR = "Chefinhos"
KIDS_MEDIO = "Prezinhos"
KIDS_MAIOR = "Aborrecentes"

GENERO_ANIMACAO = 16
GENERO_NOVELA = 10766           # "Soap" (series)
PAISES_DE_NOVELA = {"BR", "MX", "CO", "AR", "TR", "PT", "VE", "CL", "PE", "PH", "IN"}
PALAVRAS_ADULTO = re.compile(r"\b(xxx|porn\w*|hentai|\+18|18\+|adult[oa]s?|erotic\w*|er[oó]tic\w*)\b", re.I)
PALAVRAS_PRE_ESCOLA = ("preschool", "pre-school", "toddler", "nursery rhyme", "baby", "babies", "kindergarten")


def agora_ms():
    return int(time.time() * 1000)


def hoje():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def inteiro(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# AS ENTRADAS (arquivos do repositorio)
# ---------------------------------------------------------------------

def ler_mapa(nome, col_tmdb=0, col_nome=None):
    """tmdb -> nome (ou "") de um mapa txt do MATRIX (cabecalho #gerado)"""
    saida = {}
    caminho = os.path.join(MATRIX, nome)
    try:
        with open(caminho, encoding="utf-8") as f:
            for l in f:
                if not l.strip() or l.startswith("#"):
                    continue
                p = l.rstrip("\n").split("\t")
                t = inteiro(p[col_tmdb]) if len(p) > col_tmdb else None
                if not t or t <= 0:
                    continue
                n = p[col_nome].strip() if col_nome is not None and len(p) > col_nome else ""
                if t not in saida or (n and not saida[t]):
                    saida[t] = n
    except OSError:
        print("aviso: %s não existe" % nome)
    return saida


def ler_json(nome):
    try:
        with open(os.path.join(MATRIX, nome), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("aviso: %s não foi lido (%s)" % (nome, type(e).__name__))
        return None


def ids_do_json(nome, chave):
    d = ler_json(nome)
    lista = d.get(chave) if isinstance(d, dict) else (d if isinstance(d, list) else [])
    s = set()
    for o in lista or []:
        if isinstance(o, dict):
            t = inteiro(o.get("tmdb_id") or o.get("tmdbId") or o.get("id"))
            if t and t > 0:
                s.add(t)
    return s


def ler_correcoes():
    d = ler_json("apis_correcoes.json") if os.path.exists(CORRECOES) else None
    if not isinstance(d, dict):
        return {}
    saida = {}
    for k in ("bloquear", "tirar_infantil", "tirar_anime", "tirar_novela", "anime", "novela"):
        s = set()
        for item in d.get(k) or []:
            m = re.match(r"^\s*(filme|serie|série|movie|tv)\s*:\s*(\d+)\s*$", str(item), re.I)
            if m:
                s.add(("t" if m.group(1).lower() in ("serie", "série", "tv") else "m") + m.group(2))
        saida[k] = s
    infantil = {}
    for item, pastas in (d.get("infantil") or {}).items():
        m = re.match(r"^\s*(filme|serie|série|movie|tv)\s*:\s*(\d+)\s*$", str(item), re.I)
        if m and isinstance(pastas, list):
            infantil[("t" if m.group(1).lower() in ("serie", "série", "tv") else "m") + m.group(2)] = [str(x) for x in pastas]
    saida["infantil"] = infantil
    return saida


# ---------------------------------------------------------------------
# TMDB
# ---------------------------------------------------------------------

class Ritmo:
    """no maximo POR_SEGUNDO pedidos por segundo, entre todas as linhas"""
    def __init__(self, por_segundo):
        self.intervalo = 1.0 / por_segundo
        self.trava = threading.Lock()
        self.proximo = 0.0

    def esperar(self):
        with self.trava:
            agora = time.monotonic()
            if self.proximo > agora:
                time.sleep(self.proximo - agora)
                agora = self.proximo
            self.proximo = agora + self.intervalo


RITMO = Ritmo(POR_SEGUNDO)


def tmdb(caminho, extra):
    q = {"language": "pt-BR"}
    q.update(extra)
    if TMDB_KEY and not TMDB_TOKEN:
        q["api_key"] = TMDB_KEY
    url = TMDB_BASE.rstrip("/") + caminho + "?" + urllib.parse.urlencode(q)
    cab = {"Accept": "application/json", "User-Agent": "CineGo-robo-apis/1.0"}
    if TMDB_TOKEN:
        cab["Authorization"] = "Bearer " + TMDB_TOKEN
    for tentativa in range(4):
        RITMO.esperar()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"_nao_existe": True}
            if e.code == 401:
                raise SystemExit("o TMDB recusou a chave (401) — confira o segredo TMDB_TOKEN/TMDB_KEY")
            if e.code == 429:
                espera = inteiro(e.headers.get("Retry-After")) or 2
                time.sleep(min(espera, 10))
                continue
            time.sleep(1 + tentativa)
        except Exception:
            time.sleep(1 + tentativa)
    return None


def ficha(chave):
    """a ficha resumida de um titulo ("m123" filme / "t456" serie), ou None (tente depois)"""
    serie = chave[0] == "t"
    id_ = chave[1:]
    if serie:
        d = tmdb("/tv/%s" % id_, {"append_to_response": "content_ratings,keywords"})
    else:
        d = tmdb("/movie/%s" % id_, {"append_to_response": "release_dates,keywords"})
    if d is None:
        return None
    if d.get("_nao_existe"):
        return {"nao_existe": True, "conferido": agora_ms()}
    generos = [g.get("id") for g in d.get("genres") or [] if isinstance(g, dict)]
    kw = d.get("keywords") or {}
    palavras = [str(k.get("name", "")).lower() for k in (kw.get("results") or kw.get("keywords") or []) if isinstance(k, dict)]
    br = us = ""
    if serie:
        for r in (d.get("content_ratings") or {}).get("results") or []:
            if r.get("iso_3166_1") == "BR":
                br = str(r.get("rating") or "")
            elif r.get("iso_3166_1") == "US":
                us = str(r.get("rating") or "")
        paises = list(d.get("origin_country") or [])
        temporadas = [s for s in d.get("seasons") or [] if isinstance(s, dict) and (s.get("season_number") or 0) > 0]
        max_eps = max([inteiro(s.get("episode_count")) or 0 for s in temporadas] or [0])
        n_temp = len(temporadas)
    else:
        for r in (d.get("release_dates") or {}).get("results") or []:
            certs = [str(x.get("certification") or "").strip() for x in r.get("release_dates") or []]
            certs = [c for c in certs if c]
            if r.get("iso_3166_1") == "BR" and certs:
                br = certs[0]
            elif r.get("iso_3166_1") == "US" and certs:
                us = certs[0]
        paises = [p.get("iso_3166_1") for p in d.get("production_countries") or [] if isinstance(p, dict)]
        max_eps = n_temp = 0
    nome = d.get("name") if serie else d.get("title")
    data = d.get("first_air_date") if serie else d.get("release_date")
    return {
        "nome": nome or d.get("original_name") or d.get("original_title") or "",
        "ano": (data or "")[:4],
        "adulto": bool(d.get("adult")),
        "generos": generos,
        "idioma": d.get("original_language") or "",
        "paises": paises,
        "br": br.strip().upper(),
        "us": us.strip().upper(),
        "palavras": palavras[:40],
        "temporadas": n_temp,
        "max_eps": max_eps,
        "conferido": agora_ms(),
    }


# ---------------------------------------------------------------------
# A CLASSIFICACAO
# ---------------------------------------------------------------------

PALAVRAS_CHAVE_ADULTO = {"hentai", "pornography", "porn", "softcore", "erotic movie", "erotica", "sex film"}


def eh_adulto(f, nome_no_painel=""):
    if f.get("adulto"):
        return True
    if any(p in PALAVRAS_CHAVE_ADULTO for p in (f.get("palavras") or [])):
        return True
    return bool(PALAVRAS_ADULTO.search(f.get("nome") or "") or PALAVRAS_ADULTO.search(nome_no_painel or ""))


def eh_anime(f):
    animacao = GENERO_ANIMACAO in (f.get("generos") or [])
    japones = f.get("idioma") == "ja" or "JP" in (f.get("paises") or [])
    return (animacao and japones) or ("anime" in (f.get("palavras") or []))


def eh_novela(f, serie):
    if not serie or eh_anime(f):
        return False
    if GENERO_NOVELA in (f.get("generos") or []):
        return True
    return ((f.get("temporadas") or 0) in (1, 2) and (f.get("max_eps") or 0) >= 50
            and bool(set(f.get("paises") or []) & PAISES_DE_NOVELA))


def idade_br(r):
    r = (r or "").upper().replace("ANOS", "").strip()
    if r in ("L", "AL", "LIVRE", "ER"):
        return 0
    m = re.search(r"(\d+)", r)
    return int(m.group(1)) if m else None


def pastas_infantis(f):
    """as pastas do infantil (lista vazia = nao e infantil)"""
    if eh_anime(f) or GENERO_ANIMACAO not in (f.get("generos") or []):
        return []
    us = (f.get("us") or "").upper()
    pre_escola = any(p in pal for pal in (f.get("palavras") or []) for p in PALAVRAS_PRE_ESCOLA)
    br = idade_br(f.get("br"))
    if br is not None:
        if br == 0:
            if us == "TV-Y" or pre_escola:
                return [KIDS_MENOR]
            if us in ("TV-Y7", "TV-Y7-FV"):
                return [KIDS_MEDIO]
            return [KIDS_MENOR, KIDS_MEDIO]
        if br in (10, 12):
            return [KIDS_MAIOR]
        return []
    if us == "TV-Y":
        return [KIDS_MENOR]
    if us in ("G", "TV-G"):
        return [KIDS_MENOR] if pre_escola else [KIDS_MENOR, KIDS_MEDIO]
    if us in ("TV-Y7", "TV-Y7-FV", "PG"):
        return [KIDS_MEDIO]
    if us in ("TV-PG", "PG-13"):
        return [KIDS_MAIOR]
    return []


# ---------------------------------------------------------------------
# ESTADO
# ---------------------------------------------------------------------

def dias_entre(a, b):
    """dias de a ate b ("YYYY-MM-DD")"""
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days
    except ValueError:
        return 9999


def ler_vistos():
    """chave -> {"desde": data em que entrou, "ultimo": ultimo dia visto nas APIs}; None = nunca rodou"""
    if not os.path.exists(VISTOS):
        return None
    saida = {}
    with open(VISTOS, encoding="utf-8") as f:
        for l in f:
            if not l.strip() or l.startswith("#"):
                continue
            p = l.rstrip("\n").split("\t")
            if len(p) >= 3:
                saida[p[0]] = {"desde": p[1], "ultimo": p[2]}
    return saida


def gravar_vistos(vistos):
    os.makedirs(os.path.dirname(VISTOS), exist_ok=True)
    tmp = VISTOS + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("# chave\tdesde\tultimo dia nas APIs  (robo catalogo_apis.py — nao edite)\n")
        for k in sorted(vistos):
            v = vistos[k]
            f.write("%s\t%s\t%s\n" % (k, v["desde"], v["ultimo"]))
    os.replace(tmp, VISTOS)


def ler_fichas():
    try:
        with open(FICHAS, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_fichas(fichas):
    os.makedirs(os.path.dirname(FICHAS), exist_ok=True)
    tmp = FICHAS + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(fichas, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, FICHAS)


def gravar_se_mudou(nome, conteudo):
    """grava MATRIX/apis/<nome> so se o conteudo mudou (o "gerado" nao conta)"""
    caminho = os.path.join(PASTA, nome)
    try:
        with open(caminho, encoding="utf-8") as f:
            antigo = json.load(f)
        antigo.pop("gerado", None)
    except (OSError, ValueError):
        antigo = None
    novo = dict(conteudo)
    if antigo == novo:
        return False
    novo["gerado"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(PASTA, exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(novo, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, caminho)
    return True


# ---------------------------------------------------------------------

def main():
    if not TMDB_TOKEN and not TMDB_KEY:
        print("faltam os segredos TMDB_TOKEN (ou TMDB_KEY)")
        return 1
    comeco = time.time()
    fichas = ler_fichas()
    vistos = ler_vistos()
    primeira_carga = vistos is None
    if vistos is None:
        vistos = {}
        print("PRIMEIRA CARGA: tudo entra com a data %s (nada aparece como novidade)" % DATA_ANTIGA)
    correcoes = ler_correcoes()
    bloqueados = correcoes.get("bloquear", set())

    # ---- o que as APIs tem agora (os mapas do MATRIX) ----
    nomes_painel = {}
    filmes_api = {}
    # (um mapa vazio/ausente nao apaga nada de uma vez: quem nao aparece hoje
    # so sai depois dos 7 dias de folga)
    for nome, col_nome in (("redemuvi_filmes.txt", None), ("mgeb_filmes.txt", 3)):
        for t, n in ler_mapa(nome, 0, col_nome).items():
            filmes_api["m%d" % t] = True
            if n:
                nomes_painel["m%d" % t] = n
    series_com_ep = set()
    for nome in ("redemuvi_series.txt", "mgeb_episodios.txt"):
        for t in ler_mapa(nome, 0).keys():
            series_com_ep.add("t%d" % t)
    series_api = {}
    for nome, col_nome in (("redemuvi_series.txt", None), ("mgeb_series.txt", 3)):
        for t, n in ler_mapa(nome, 0, col_nome).items():
            series_api["t%d" % t] = True
            if n:
                nomes_painel.setdefault("t%d" % t, n)

    # um mapa vazio (robo do mapa falhou) nao pode apagar tudo: so conta o que veio
    agora = agora_ms()
    hoje_txt = hoje()
    for k in list(filmes_api) + list(series_api):
        v = vistos.get(k)
        if v is None:
            vistos[k] = {"desde": DATA_ANTIGA if primeira_carga else hoje_txt, "ultimo": hoje_txt}
        else:
            v["ultimo"] = hoje_txt
    print("nas APIs agora: %d filmes · %d séries (%d com episódio)" % (len(filmes_api), len(series_api), len(series_com_ep)))

    # ---- o que ja esta no SEU JSON ----
    json_filmes = {"m%d" % t for t in ids_do_json("filmes.json", "movies")}
    json_series = {"t%d" % t for t in ids_do_json("shows.json", "shows")} | {"t%d" % t for t in ids_do_json("NOVELAS.json", "series")} | {"t%d" % t for t in ids_do_json("NOVELAS.json", "shows")}
    print("no seu JSON: %d filmes · %d séries" % (len(json_filmes), len(json_series)))

    # ---- quem precisa de ficha do TMDB ----
    em_jogo = set(k for k, v in vistos.items() if dias_entre(v["ultimo"], hoje_txt) <= FOLGA_DIAS) | json_filmes | json_series
    sem_ficha = [k for k in em_jogo if k not in fichas]
    velhas = sorted((k for k in em_jogo if k in fichas and agora - fichas[k].get("conferido", 0) > RECONFERIR_DIAS * 86400000),
                    key=lambda k: fichas[k].get("conferido", 0))[:RECONFERIR_POR_RODADA]
    # as das APIs primeiro (sao as que entram no app)
    sem_ficha.sort(key=lambda k: (k in json_filmes or k in json_series, k))
    fila = sem_ficha + velhas
    print("fichas do TMDB: %d guardadas · %d a buscar · %d a reconferir" % (len(fichas), len(sem_ficha), len(velhas)))

    feitas = 0
    falhas = 0
    if fila:
        with ThreadPoolExecutor(max_workers=JUNTAS) as ex:
            futuros = {}
            i = 0
            while i < len(fila) or futuros:
                while i < len(fila) and len(futuros) < JUNTAS * 3 and time.time() - comeco < PRAZO:
                    futuros[ex.submit(ficha, fila[i])] = fila[i]
                    i += 1
                if not futuros:
                    break
                for fut in as_completed(list(futuros)):
                    k = futuros.pop(fut)
                    try:
                        r = fut.result()
                    except SystemExit:
                        raise
                    except Exception:
                        r = None
                    if r is None:
                        falhas += 1
                    else:
                        fichas[k] = r
                        feitas += 1
                        if feitas % 1000 == 0:
                            gravar_fichas(fichas)
                            print("  %d fichas..." % feitas)
                    break
                if time.time() - comeco >= PRAZO and i < len(fila):
                    print("prazo da rodada — o resto fica para a próxima")
                    i = len(fila)
    print("fichas novas: %d · falharam (tenta depois): %d" % (feitas, falhas))

    # ---- montar os arquivos ----
    filmes, series, novelas = [], [], []
    marcas_filmes, marcas_series = [], []
    contagem = {"adulto": 0, "anime": 0, "novela": 0, "infantil": 0, "sem_ficha": 0, "sem_episodio": 0, "bloqueado": 0}

    def classificar(k):
        f = fichas.get(k)
        if not f or f.get("nao_existe"):
            return None
        anime = (eh_anime(f) and k not in correcoes.get("tirar_anime", set())) or k in correcoes.get("anime", set())
        novela = (eh_novela(f, k[0] == "t") and k not in correcoes.get("tirar_novela", set())) or (k[0] == "t" and k in correcoes.get("novela", set()))
        if anime:
            novela = False
        kids = correcoes.get("infantil", {}).get(k)
        if kids is None:
            kids = [] if (anime or k in correcoes.get("tirar_infantil", set())) else pastas_infantis(f)
        return f, anime, novela, kids

    def entrada(k, f, anime, kids, data):
        o = {"tmdb_id": int(k[1:]), "type": "tv" if k[0] == "t" else "movie",
             "title": f.get("nome") or "", "added_at": data}
        if kids:
            o["kids"] = kids
        if anime:
            o["anime"] = True
        return o

    for k in sorted(vistos, key=lambda x: (vistos[x].get("desde", ""), x), reverse=True):
        v = vistos[k]
        if dias_entre(v["ultimo"], hoje_txt) > FOLGA_DIAS:
            continue                                   # saiu da API ha mais de 7 dias
        if k in json_filmes or k in json_series:
            continue                                   # ja esta no seu JSON (so marca, abaixo)
        if k in bloqueados:
            contagem["bloqueado"] += 1
            continue
        c = classificar(k)
        if c is None:
            contagem["sem_ficha"] += 1
            continue
        f, anime, novela, kids = c
        if eh_adulto(f, nomes_painel.get(k, "")):
            contagem["adulto"] += 1
            continue
        if k[0] == "t" and k not in series_com_ep:
            contagem["sem_episodio"] += 1
            continue
        contagem["anime"] += int(anime)
        contagem["novela"] += int(novela)
        contagem["infantil"] += int(bool(kids))
        o = entrada(k, f, anime, kids, v.get("desde", DATA_ANTIGA))
        (novelas if novela else series if k[0] == "t" else filmes).append(o)

    # os animes do SEU JSON: so a marca
    for k in sorted(json_filmes | json_series):
        if k in bloqueados:
            continue
        c = classificar(k)
        if c is None or not c[1]:
            continue
        o = {"tmdb_id": int(k[1:]), "type": "tv" if k[0] == "t" else "movie", "anime": True, "so_marca": True}
        (marcas_series if k[0] == "t" else marcas_filmes).append(o)

    mudou = []
    if gravar_se_mudou("filmes.json", {"movies": filmes}):
        mudou.append("filmes")
    if gravar_se_mudou("series.json", {"shows": series}):
        mudou.append("series")
    if gravar_se_mudou("novelas.json", {"shows": novelas}):
        mudou.append("novelas")
    if gravar_se_mudou("marcas.json", {"movies": marcas_filmes, "shows": marcas_series}):
        mudou.append("marcas")
    gravar_se_mudou("apis.json", {
        "sobre": "CINE GO! — os titulos das APIs (robo catalogo_apis.py). Nao edite: e refeito sozinho.",
        "filmes": "filmes.json",
        "series": "series.json",
        "novelas": "novelas.json",
        "marcas": "marcas.json",
    })

    # quem saiu da API ha muito tempo sai da lista (a ficha fica: pode voltar)
    for k in [k for k, v in vistos.items() if dias_entre(v["ultimo"], hoje_txt) > FOLGA_DIAS * 4]:
        del vistos[k]
    gravar_vistos(vistos)
    gravar_fichas(fichas)

    print("no app: %d filmes · %d séries · %d novelas · marcas de anime no seu JSON: %d filmes, %d séries"
          % (len(filmes), len(series), len(novelas), len(marcas_filmes), len(marcas_series)))
    print("de fora: adultos %(adulto)d · sem ficha ainda (ou não existe no TMDB) %(sem_ficha)d · séries sem episódio ainda %(sem_episodio)d · bloqueados %(bloqueado)d" % contagem)
    print("classificados: animes %(anime)d · novelas %(novela)d · infantis %(infantil)d" % contagem)
    print("arquivos que mudaram: %s" % (", ".join(mudou) or "nenhum"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
