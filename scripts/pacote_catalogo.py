#!/usr/bin/env python3
"""
ROBO DO PACOTE DO CATALOGO (CINE GO!)

Problema: no PRIMEIRO acesso o app abre ~1.300 arquivos do catalogo um por um
(catalog.example.json -> filmes.json, series.json -> 1.260 series, novelas,
apis, metadados...). Cada pedido custa ~0,2 s: minutos de espera.

Solucao: este robo faz o caminho que o app faria, baixa TODOS esses arquivos
(16 por vez) e junta tudo num arquivo so: catalogo.zip. O app baixa o zip
(poucos MB, um pedido so) e le os arquivos de dentro dele, como se viessem da
internet. Nada muda na montagem do catalogo: os arquivos sao os MESMOS.

Dentro do zip:
  indice.json  -> {"formato": 1, "raiz": "<catalog.example.json>",
                   "gerado": "...", "assinatura": "...",
                   "arquivos": {"<endereco>": {"n": "f/00001.json", "etag": "W/..."}}}
  f/00001.json ... (o conteudo exato de cada endereco)

A "etag" e a do GitHub (com gzip, igual ao app pede). Depois de abrir pelo
pacote, o app pergunta ao GitHub "mudou?" mandando essa etag: nao mudou = 304,
nada e baixado.

O zip vai para o RELEASE "pacote" deste repositorio (nao entra no historico
do git, nao incha o repositorio). Endereco fixo:
  https://github.com/RAPOSO-PAUL/TeamViannaREPO/releases/download/pacote/catalogo.zip

Seguranca: so arquivos PUBLICOS que o app ja le. Nenhuma senha, nenhum segredo.

Uso:  python scripts/pacote_catalogo.py --saida pacote_saida
      (sai com codigo 0; escreve pacote_saida/MUDOU quando o zip novo
       deve ser publicado)
"""
import argparse
import concurrent.futures as cf
import gzip
import hashlib
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib

RAIZ = ("https://raw.githubusercontent.com/RAPOSO-PAUL/TeamViannaREPO/"
        "refs/heads/main/MATRIX/catalog.example.json")
PACOTE_ATUAL = ("https://github.com/RAPOSO-PAUL/TeamViannaREPO/releases/"
                "download/pacote/catalogo.zip")

JUNTAS = 16              # pedidos ao mesmo tempo
TENTATIVAS = 4
LIMITE_ARQUIVOS = 6000   # trava de seguranca (laco infinito de .json)
LIMITE_ZIP = 95 * 1024 * 1024   # release aceita ate 2 GB; o app nao quer mais que isso
FALHAS_TOLERADAS = 0.02  # mais de 2% de falhas (sem ser 404) = nao publica
DATA_FIXA = (2020, 1, 1, 0, 0, 0)  # zip igual para conteudo igual

# Chaves que o app NAO le como catalogo (Catalogo.kt / percorrerNo).
# Sao lidas por outras partes do app (canais, guia, tema...) quando precisam.
NAO_SEGUIR = {
    "streamings", "metadados", "metadata", "tema", "temas",
    "canais", "channels", "radios", "guia",
    "atores", "estrelas", "grandes_estrelas",
    "sites_iguais", "fontes_ignoradas", "ordem_inicial", "legendas_online",
}


def agora():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------------------
# baixar (igual ao app: aceita gzip -> a etag e a mesma que o app recebe)
# ---------------------------------------------------------------------------
class Falha(Exception):
    def __init__(self, codigo, texto):
        super().__init__(texto)
        self.codigo = codigo


def para_pedido(endereco):
    """acentos no endereco (ex.: PEDAÇO.json) viram %C3%87 — igual ao app (OkHttp)"""
    return urllib.parse.quote(endereco, safe=":/?#[]@!$&'()*+,;=%~")


def baixar(endereco, timeout=40):
    ultimo = None
    for t in range(TENTATIVAS):
        try:
            req = urllib.request.Request(para_pedido(endereco), headers={
                "User-Agent": "TVEminem/1.0",
                "accept": "application/json",
                "Accept-Encoding": "gzip",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                corpo = r.read()
                if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                    corpo = gzip.decompress(corpo)
                return corpo, r.headers.get("ETag")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise Falha(e.code, "nao existe")
            ultimo = Falha(e.code, "HTTP %d" % e.code)
        except Exception as e:  # rede, tempo, gzip quebrado
            ultimo = Falha(0, str(e)[:120])
        time.sleep(1.5 * (t + 1))
    raise ultimo


# ---------------------------------------------------------------------------
# as regras do app (Catalogo.kt): o que e titulo, o que e outro .json
# ---------------------------------------------------------------------------
def numero(v):
    """JSONObject.optInt: aceita 123, 123.0 e "123"."""
    if isinstance(v, bool) or v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(float(str(v).strip()))
    except Exception:
        return 0


def texto(o, *chaves):
    for c in chaves:
        v = o.get(c)
        if v is None:
            continue
        s = str(v).strip() if not isinstance(v, (dict, list)) else "x"
        if s and s != "null":
            return s
    return None


def eh_titulo(o):
    if numero(o.get("tmdb_id")) > 0 or numero(o.get("tmdbId")) > 0 or numero(o.get("id")) > 0:
        return True
    tem_nome = texto(o, "title", "name", "titulo", "nome") is not None
    tem_fonte = (texto(o, "magnet", "stream_url", "url", "link", "file", "src",
                       "embed", "iframe", "quadro") is not None
                 or isinstance(o.get("sources"), list) or isinstance(o.get("episodes"), list)
                 or isinstance(o.get("fontes"), list) or isinstance(o.get("iframes"), list))
    return tem_nome and tem_fonte


def parece_json(s):
    v = s.strip().split("?")[0].split("#")[0]
    return v.lower().endswith(".json") and not v.lower().startswith("magnet:")


def resolver(base, rel):
    r = rel.strip()
    if not r:
        return None
    if r.startswith("http://") or r.startswith("https://"):
        return r
    try:
        return urllib.parse.urljoin(base, r)
    except Exception:
        return None


def filhos(no, base, saida, extras):
    """os .json que o app abriria a partir deste no"""
    if isinstance(no, list):
        for x in no:
            filhos(x, base, saida, extras)
    elif isinstance(no, dict):
        if eh_titulo(no):
            return
        for chave, valor in no.items():
            k = chave.lower()
            if k in ("metadados", "metadata") and isinstance(valor, str) and parece_json(valor):
                u = resolver(base, valor)
                if u:
                    extras.setdefault("metadados", u)
                continue
            if k in NAO_SEGUIR:
                continue
            filhos(valor, base, saida, extras)
    elif isinstance(no, str):
        if parece_json(no):
            u = resolver(base, no)
            if u:
                saida.append(u)


def interpretar(corpo):
    try:
        t = corpo.decode("utf-8-sig", errors="replace")
        return json.loads(t)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# o passeio (como o app, mas 16 por vez)
# ---------------------------------------------------------------------------
def montar():
    arquivos = {}        # endereco -> (bytes, etag)
    sumidos = []         # 404: o app tambem nao acha (fica de fora)
    falhas = []          # outras falhas
    vistos = set()
    extras = {}
    trava = threading.Lock()

    def tarefa(endereco):
        corpo, etag = baixar(endereco)
        lista = []
        filhos(interpretar(corpo), endereco, lista, extras)
        return endereco, corpo, etag, lista

    with cf.ThreadPoolExecutor(JUNTAS) as pool:
        pendentes = {}

        def mandar(u):
            with trava:
                if u in vistos or len(vistos) >= LIMITE_ARQUIVOS:
                    return
                vistos.add(u)
            pendentes[pool.submit(tarefa, u)] = u

        mandar(RAIZ)
        while pendentes:
            prontos, _ = cf.wait(list(pendentes), return_when=cf.FIRST_COMPLETED)
            for f in prontos:
                u = pendentes.pop(f)
                try:
                    endereco, corpo, etag, lista = f.result()
                except Falha as e:
                    (sumidos if e.codigo in (404, 410) else falhas).append((u, str(e)))
                    continue
                except Exception as e:
                    falhas.append((u, str(e)[:120]))
                    continue
                arquivos[endereco] = (corpo, etag)
                for filho in lista:
                    mandar(filho)
            # os metadados (lidos pelo Metadados.kt) tambem vao no pacote
            m = extras.get("metadados")
            if m and m not in vistos:
                mandar(m)

    if "metadados" not in extras:
        # o app tambem procura <pasta do filmes.json>/metadados.json
        log("aviso: o JSON principal nao tem a chave metadados")

    return arquivos, sumidos, falhas, len(vistos) >= LIMITE_ARQUIVOS


def assinatura(arquivos):
    h = hashlib.sha256()
    for u in sorted(arquivos):
        corpo, etag = arquivos[u]
        h.update(u.encode())
        h.update(b"\0")
        h.update(hashlib.sha256(corpo).digest())
        h.update((etag or "").encode())
        h.update(b"\n")
    return h.hexdigest()


def assinatura_anterior():
    """a do pacote publicado agora (None = nao tem / nao deu para ler)"""
    try:
        req = urllib.request.Request(PACOTE_ATUAL, headers={"User-Agent": "TVEminem/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            dados = r.read()
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            return json.loads(z.read("indice.json")).get("assinatura")
    except Exception as e:
        log("pacote anterior: nao lido (%s)" % str(e)[:80])
        return None


def gravar_zip(arquivos, destino, assin):
    ordem = sorted(arquivos)
    nomes = {u: "f/%05d.json" % (i + 1) for i, u in enumerate(ordem)}
    indice = {
        "formato": 1,
        "raiz": RAIZ,
        "gerado": agora(),
        "assinatura": assin,
        "arquivos": {u: {"n": nomes[u], "etag": arquivos[u][1]} for u in ordem},
    }
    tmp = destino + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def por(nome, dados):
            zi = zipfile.ZipInfo(nome, DATA_FIXA)
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, dados, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        # o indice PRIMEIRO (o app le ele antes de tudo)
        por("indice.json", json.dumps(indice, ensure_ascii=False, separators=(",", ":")).encode())
        for u in ordem:
            por(nomes[u], arquivos[u][0])
    # confere o zip inteiro antes de entregar
    with zipfile.ZipFile(tmp) as z:
        ruim = z.testzip()
        if ruim:
            raise SystemExit("zip com defeito em %s" % ruim)
        lido = json.loads(z.read("indice.json"))
        for u, info in lido["arquivos"].items():
            if zlib.crc32(z.read(info["n"])) != zlib.crc32(arquivos[u][0]):
                raise SystemExit("conteudo diferente em %s" % u)
    os.replace(tmp, destino)
    return indice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="pacote_saida")
    ap.add_argument("--sempre", action="store_true", help="publica mesmo sem mudanca")
    a = ap.parse_args()
    os.makedirs(a.saida, exist_ok=True)
    marca = os.path.join(a.saida, "MUDOU")
    if os.path.exists(marca):
        os.remove(marca)

    t0 = time.time()
    arquivos, sumidos, falhas, estourou = montar()
    bruto = sum(len(c) for c, _ in arquivos.values())
    log("arquivos: %d (%.1f MB) em %.0f s | nao existem (404): %d | falhas: %d"
        % (len(arquivos), bruto / 1e6, time.time() - t0, len(sumidos), len(falhas)))
    for u, e in (sumidos[:15] + falhas[:15]):
        log("  - %s  (%s)" % (u, e))

    # ---- travas: na duvida NAO publica (o pacote anterior continua valendo)
    if RAIZ not in arquivos:
        log("ERRO: o JSON principal nao baixou — nada publicado")
        return 1
    if estourou:
        log("ERRO: mais de %d arquivos (laco?) — nada publicado" % LIMITE_ARQUIVOS)
        return 1
    total = len(arquivos) + len(falhas)
    if falhas and len(falhas) / max(1, total) > FALHAS_TOLERADAS:
        log("ERRO: falhas demais (%d de %d) — nada publicado" % (len(falhas), total))
        return 1
    if len(arquivos) < 3:
        log("ERRO: quase nada baixado — nada publicado")
        return 1

    assin = assinatura(arquivos)
    antes = assinatura_anterior()
    if antes == assin and not a.sempre:
        log("nada mudou desde o ultimo pacote — nao publica")
        return 0

    destino = os.path.join(a.saida, "catalogo.zip")
    gravar_zip(arquivos, destino, assin)
    tam = os.path.getsize(destino)
    log("catalogo.zip: %.1f MB (%d arquivos)" % (tam / 1e6, len(arquivos)))
    if tam > LIMITE_ZIP:
        log("ERRO: zip grande demais — nada publicado")
        return 1
    open(marca, "w").write(assin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
