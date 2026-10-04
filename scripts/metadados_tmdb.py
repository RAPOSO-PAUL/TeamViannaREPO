"""
ROBO DOS METADADOS — consulta o TMDB UMA VEZ por titulo, para TODOS os
aparelhos, e grava tudo num arquivo so: MATRIX/metadados.json.

O app le esse arquivo junto com o catalogo e preenche capa, fundo, nome,
ano, nota, generos e streamings SEM consultar o TMDB titulo por titulo.

Cada rodada:
  1. le os ids do catalogo (filmes.json, shows.json e os .json das series);
  2. titulo NOVO (nao esta no metadados.json)  -> consulta e ACRESCENTA;
  3. titulo que SAIU do catalogo               -> REMOVE;
  4. REVISAO: na rodada diaria, 1/14 dos titulos e consultado de novo (cada
     titulo e revisto a cada ~2 semanas). Se algo mudou, SUBSTITUI so ele;
  5. consulta que FALHOU (internet, TMDB fora) -> mantem o que ja tinha;
  6. grava o metadados.json (so se mudou) e o relatorio_tmdb.md.

Sem bibliotecas extras: so Python 3.
"""
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# ----------------------------------------------------------------------
# CONFIGURACAO (caminhos dentro do repositorio)
# ----------------------------------------------------------------------
FILMES = os.environ.get("CAMINHO_FILMES", "MATRIX/filmes.json")
SHOWS = os.environ.get("CAMINHO_SHOWS", "MATRIX/shows.json")
SERIES = os.environ.get("CAMINHO_SERIES", "MATRIX/series.json")
SAIDA = os.environ.get("CAMINHO_SAIDA", "MATRIX/metadados.json")
RELATORIO = os.environ.get("CAMINHO_RELATORIO", "MATRIX/relatorio_tmdb.md")

TOKEN = os.environ.get("TMDB_TOKEN", "").strip()
# "sim" na rodada diaria; "nao" quando disparado pelo envio do catalogo
REVISAR = os.environ.get("REVISAR", "sim") == "sim"
FATIAS = 14             # revisao: cada titulo e revisto a cada 14 dias
PARALELOS = 8           # consultas ao mesmo tempo (o TMDB aguenta bem mais)
POR_SEGUNDO = 30        # teto de consultas por segundo
API = "https://api.themoviedb.org/3"


# ----------------------------------------------------------------------
# LER O CATALOGO
# ----------------------------------------------------------------------
def ler_json_local(caminho):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def baixar_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "robo-metadados/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def lista_de(raiz, *chaves):
    if isinstance(raiz, list):
        return raiz
    if isinstance(raiz, dict):
        for k in chaves:
            if isinstance(raiz.get(k), list):
                return raiz[k]
    return []


def id_de(o):
    if not isinstance(o, dict):
        return 0
    for k in ("tmdb_id", "tmdbId", "id"):
        try:
            v = int(o.get(k) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return 0


def ids_do_catalogo():
    filmes, series = set(), set()
    for o in lista_de(ler_json_local(FILMES), "movies", "filmes"):
        i = id_de(o)
        if i:
            (series if o.get("type") == "tv" else filmes).add(i)

    if os.path.exists(SHOWS):
        for o in lista_de(ler_json_local(SHOWS), "shows", "series"):
            i = id_de(o)
            if i:
                series.add(i)

    # os .json de cada serie (podem estar em outro repositorio)
    if os.path.exists(SERIES):
        raiz = ler_json_local(SERIES)
        urls = [u for u in lista_de(raiz, "series") if isinstance(u, str) and u.startswith("http")]

        def um(url):
            try:
                return id_de(baixar_json(url))
            except Exception:
                return 0
        with ThreadPoolExecutor(8) as ex:
            for i in ex.map(um, urls):
                if i:
                    series.add(i)
    return filmes, series


# ----------------------------------------------------------------------
# CONSULTAR O TMDB (com teto por segundo e nova tentativa no 429)
# ----------------------------------------------------------------------
_trava = threading.Lock()
_ultimo = [0.0]


def _esperar_vez():
    with _trava:
        espera = _ultimo[0] + 1.0 / POR_SEGUNDO - time.time()
        if espera > 0:
            time.sleep(espera)
        _ultimo[0] = time.time()


def tmdb(caminho):
    """dict | "404" (nao existe) | None (falhou — tentar outro dia)"""
    v4 = len(TOKEN) > 60 and "." in TOKEN
    sep = "&" if "?" in caminho else "?"
    url = f"{API}{caminho}{sep}language=pt-BR"
    if not v4:
        url += "&api_key=" + urllib.parse.quote(TOKEN)
    cab = {"accept": "application/json", "User-Agent": "robo-metadados/1.0"}
    if v4:
        cab["Authorization"] = "Bearer " + TOKEN
    for tentativa in range(4):
        _esperar_vez()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "404"
            if e.code == 429:
                time.sleep(float(e.headers.get("Retry-After") or 2) + tentativa)
                continue
            if e.code in (401, 403):
                print("ERRO: a chave do TMDB foi recusada (confira o segredo TMDB_TOKEN)")
                sys.exit(1)
            time.sleep(1 + tentativa)
        except Exception:
            time.sleep(1 + tentativa)
    return None


# O MESMO "limparProvedor" do app (data/Tmdb.kt)
_SUFIXOS = [re.compile(p, re.I) for p in (
    r"\s+(basic|standard|premium)?\s*with\s+ads$",
    r"\s+amazon\s+channel$",
    r"\s+apple\s+tv\s+channel$",
    r"\s+roku\s+premium\s+channel$",
    r"\s+standard$",
    r"\s+basic$",
)]


def limpar_provedor(nome):
    n = (nome or "").strip()
    mudou = True
    while mudou:
        mudou = False
        for r in _SUFIXOS:
            novo = r.sub("", n).strip()
            if novo != n and novo:
                n, mudou = novo, True
    return n or None


def ficha(tipo, tmdb_id):
    """a ficha enxuta do titulo, no formato que o app le"""
    d = tmdb(f"/{tipo}/{tmdb_id}?append_to_response=watch/providers")
    if d is None or d == "404":
        return d
    nome = d.get("name") if tipo == "tv" else d.get("title")
    data = d.get("first_air_date") if tipo == "tv" else d.get("release_date")
    f = {}
    if nome:
        f["n"] = nome
    if d.get("poster_path"):
        f["capa"] = d["poster_path"]
    if d.get("backdrop_path"):
        f["fundo"] = d["backdrop_path"]
    if data:
        f["data"] = data
    nota = d.get("vote_average") or 0
    if nota > 0:
        f["nota"] = round(float(nota), 1)   # 1 casa: o arquivo muda menos
    gen = [g.get("name") for g in d.get("genres") or [] if g.get("name")]
    if gen:
        f["gen"] = gen

    # onde passa: a REDE da serie + streamings do BRASIL (assinatura/gratis)
    redes = []
    if tipo == "tv":
        redes += [r.get("name") for r in d.get("networks") or [] if r.get("name")]
    br = ((d.get("watch/providers") or {}).get("results") or {}).get("BR") or {}
    for grupo in ("flatrate", "ads", "free"):
        for p in br.get(grupo) or []:
            n = limpar_provedor(p.get("provider_name"))
            if n:
                redes.append(n)
    redes = list(dict.fromkeys(redes))      # sem repetir, na mesma ordem
    if redes:
        f["redes"] = redes
    return f


# ----------------------------------------------------------------------
# GRAVAR (uma linha por titulo: o "diff" do GitHub fica legivel)
# ----------------------------------------------------------------------
def gravar(meta):
    def bloco(d):
        linhas = [json.dumps(str(k)) + ":" + json.dumps(d[k], ensure_ascii=False, separators=(",", ":"))
                  for k in sorted(d, key=int)]
        return "{\n" + ",\n".join(linhas) + "\n}"
    texto = ('{"versao":1,\n"movie":' + bloco(meta["movie"]) + ',\n"tv":' + bloco(meta["tv"]) + "}\n")
    antigo = open(SAIDA, encoding="utf-8").read() if os.path.exists(SAIDA) else ""
    if texto != antigo:
        with open(SAIDA, "w", encoding="utf-8") as f:
            f.write(texto)
        return True
    return False


def main():
    if not TOKEN:
        print("ERRO: falta o segredo TMDB_TOKEN")
        sys.exit(1)

    filmes, series = ids_do_catalogo()
    print(f"catalogo: {len(filmes)} filmes, {len(series)} series")

    meta = {"movie": {}, "tv": {}}
    if os.path.exists(SAIDA):
        try:
            antigo = ler_json_local(SAIDA)
            meta["movie"] = {int(k): v for k, v in (antigo.get("movie") or {}).items()}
            meta["tv"] = {int(k): v for k, v in (antigo.get("tv") or {}).items()}
        except Exception:
            print("metadados.json ilegivel — comecando do zero")

    # 3. quem saiu do catalogo sai daqui
    removidos = 0
    for tipo, ids in (("movie", filmes), ("tv", series)):
        for i in list(meta[tipo]):
            if i not in ids:
                del meta[tipo][i]
                removidos += 1

    # 2 e 4. o que consultar: os novos + a fatia de revisao do dia
    fatia = dt.date.today().toordinal() % FATIAS
    fila = []
    for tipo, ids in (("movie", filmes), ("tv", series)):
        for i in ids:
            if i not in meta[tipo] or (REVISAR and i % FATIAS == fatia):
                fila.append((tipo, i))
    novos = sum(1 for t, i in fila if i not in meta[t])
    print(f"a consultar: {len(fila)} ({novos} novos, {len(fila) - novos} revisoes); {removidos} removidos")

    resultados = {}
    feitos = [0]
    inicio = time.time()

    trava_log = threading.Lock()

    def trabalhar(item):
        r = ficha(*item)
        with trava_log:
            resultados[item] = r
            feitos[0] += 1
            if feitos[0] % 500 == 0:
                print(f"  {feitos[0]}/{len(fila)}  ({time.time() - inicio:.0f} s)", flush=True)

    with ThreadPoolExecutor(PARALELOS) as ex:
        list(ex.map(trabalhar, fila))

    falhas, nao_existe = 0, []
    for (tipo, i), r in resultados.items():
        if r is None:
            falhas += 1                       # 5. falhou: fica o que tinha
        elif r == "404":
            meta[tipo][i] = {"x": 404}        # nao existe no TMDB (o app ignora)
            nao_existe.append((tipo, i))
        else:
            meta[tipo][i] = r                 # acrescenta ou substitui

    mudou = gravar(meta)
    print(f"falhas (tenta de novo depois): {falhas}; metadados {'ATUALIZADO' if mudou else 'sem mudancas'}")

    # relatorio
    sem_capa = [(t, i) for t in ("movie", "tv") for i, v in meta[t].items()
                if "x" not in v and not v.get("capa")]
    todos_404 = [(t, i) for t in ("movie", "tv") for i, v in meta[t].items() if v.get("x") == 404]
    br = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3)))
    with open(RELATORIO, "w", encoding="utf-8") as f:
        f.write(f"# Relatório do TMDB\n\nRodada de {br:%d/%m/%Y %H:%M} (Brasília).\n\n")
        f.write(f"- Catálogo: {len(filmes)} filmes e {len(series)} séries\n")
        f.write(f"- Consultados nesta rodada: {len(fila)} ({novos} novos)\n")
        f.write(f"- Removidos (saíram do catálogo): {removidos}\n")
        f.write(f"- Falhas (o robô tenta de novo depois): {falhas}\n\n")
        f.write("## Id que não existe no TMDB\n\nConfira o `tmdb_id` destes no catálogo.\n\n")
        f.write("\n".join(f"- {t} `{i}` — https://www.themoviedb.org/{t}/{i}" for t, i in sorted(todos_404))
                or "Nenhum.")
        f.write("\n\n## Sem capa no TMDB\n\n")
        f.write("\n".join(f"- {t} `{i}` {meta[t][i].get('n', '')}" for t, i in sorted(sem_capa)[:300])
                or "Nenhum.")
        f.write("\n")


if __name__ == "__main__":
    main()
