#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBO DO REDEMUVI (TeamViannaREPO) — monta o MAPA da conta para o CINE GO.

Grava (so quando o conteudo MUDA — nada de commit a toa):
  MATRIX/redemuvi_filmes.txt   tmdb  stream_id  ext
  MATRIX/redemuvi_series.txt   tmdb  temporada  episodio  episode_id  ext
  MATRIX/redemuvi_canais.txt   stream_id  nome  epg_channel_id  categoria

Cada arquivo comeca com "#gerado<TAB><milissegundos>". NENHUM traz usuario
ou senha: o app monta o endereco com a conta dele.

A CONTA vem dos Secrets do GitHub (nunca do codigo):
  REDEMUVI_USUARIO  e  REDEMUVI_SENHA

Regras da RedeMuvi respeitadas: so LISTAS e FICHAS (get_*), nunca link de
play; um pedido por vez por tipo, com pausa; 401/403/429 = para tudo.

As fichas (get_vod_info / get_series_info) ficam guardadas em
.robo_redemuvi/ (cache do GitHub Actions, fora do repositorio): cada rodada
so pede as NOVAS ou as que mudaram (last_modified), ate um limite por rodada.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SERVIDORES = [
    "https://api.redemuvi.lat",
    "https://api.redemuviapi.lat",
    "http://api.redemuvi.lat",
    "http://api.redemuviapi.lat",
]
AGENTE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SAIDA = os.environ.get("REDEMUVI_SAIDA", "MATRIX")
ESTADO = os.environ.get("REDEMUVI_ESTADO", ".robo_redemuvi")
MAX_FICHAS_FILMES = int(os.environ.get("REDEMUVI_MAX_FICHAS_FILMES", "1500"))
MAX_FICHAS_SERIES = int(os.environ.get("REDEMUVI_MAX_FICHAS_SERIES", "800"))
PAUSA = float(os.environ.get("REDEMUVI_PAUSA", "0.25"))

USUARIO = os.environ.get("REDEMUVI_USUARIO", "").strip()
SENHA = os.environ.get("REDEMUVI_SENHA", "").strip()


class Recusou(Exception):
    """401/403/429: a conta recusou — para tudo (nada de insistir)."""


def log(msg):
    # a senha nunca vai para o log (o GitHub tambem mascara os Secrets)
    if SENHA:
        msg = msg.replace(SENHA, "***")
    if USUARIO:
        msg = msg.replace(USUARIO, "***")
    print(msg, flush=True)


class Conta:
    def __init__(self):
        self.base = None

    def _pedir(self, base, params, prazo=90):
        q = {"username": USUARIO, "password": SENHA}
        q.update(params)
        url = base + "/player_api.php?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=prazo) as r:
            corpo = r.read()
        return json.loads(corpo.decode("utf-8", "replace") or "null")

    def conectar(self):
        for base in SERVIDORES:
            try:
                j = self._pedir(base, {}, prazo=30)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 429):
                    raise Recusou(f"o login respondeu HTTP {e.code}")
                log(f"{base}: HTTP {e.code}")
                continue
            except Exception as e:  # sem conexao, certificado...
                log(f"{base}: {type(e).__name__}")
                continue
            info = (j or {}).get("user_info") or {}
            if str(info.get("auth")) != "1":
                raise Recusou("a conta nao autenticou (auth != 1)")
            if str(info.get("status", "")).lower() != "active":
                raise Recusou(f"a conta nao esta ativa (status {info.get('status')})")
            self.base = base
            log(f"conta OK em {base} — vence {info.get('exp_date')}, conexoes {info.get('max_connections')}")
            return
        raise RuntimeError("nenhum servidor respondeu")

    def api(self, acao, prazo=120, **extra):
        params = {"action": acao}
        params.update({k: str(v) for k, v in extra.items()})
        for tentativa in range(2):
            try:
                return self._pedir(self.base, params, prazo=prazo)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 429):
                    raise Recusou(f"{acao} respondeu HTTP {e.code}")
                if tentativa == 1:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if tentativa == 1:
                    raise
            time.sleep(3)


def inteiro(v):
    try:
        n = int(str(v).strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def ext_de(v, padrao="mp4"):
    s = str(v or "").strip().lstrip(".").lower()
    return s if 2 <= len(s) <= 5 and s.isalnum() else padrao


def tmdb_de(obj):
    if not isinstance(obj, dict):
        return None
    for k in ("tmdb", "tmdb_id"):
        n = inteiro(obj.get(k))
        if n:
            return n
    return None


def ler_estado(nome):
    try:
        with open(os.path.join(ESTADO, nome), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def gravar_estado(nome, dados):
    os.makedirs(ESTADO, exist_ok=True)
    tmp = os.path.join(ESTADO, nome + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(ESTADO, nome))


def lista_por_categoria(conta, acao_lista, acao_cats):
    """a lista inteira; se o painel nao der de uma vez, categoria por categoria"""
    try:
        tudo = conta.api(acao_lista, prazo=180)
        if isinstance(tudo, list):
            return tudo
    except Recusou:
        raise
    except Exception as e:
        log(f"{acao_lista} de uma vez falhou ({type(e).__name__}) — indo por categoria")
    cats = conta.api(acao_cats) or []
    vistos, saida = set(), []
    for c in cats:
        cid = (c or {}).get("category_id")
        if cid is None:
            continue
        try:
            parte = conta.api(acao_lista, category_id=cid) or []
        except Recusou:
            raise
        except Exception as e:
            log(f"categoria {cid}: {type(e).__name__}")
            continue
        for item in parte if isinstance(parte, list) else []:
            chave = json.dumps([item.get("stream_id"), item.get("series_id")])
            if chave not in vistos:
                vistos.add(chave)
                saida.append(item)
        time.sleep(PAUSA)
    return saida


def filmes(conta):
    lista = lista_por_categoria(conta, "get_vod_streams", "get_vod_categories")
    log(f"filmes na conta: {len(lista)}")
    fichas = ler_estado("filmes_tmdb.json")      # stream_id -> tmdb (0 = a ficha nao diz)
    linhas, sem_tmdb = {}, []
    for it in lista:
        sid = inteiro(it.get("stream_id"))
        if not sid:
            continue
        ext = ext_de(it.get("container_extension"))
        tmdb = tmdb_de(it) or inteiro(fichas.get(str(sid)))
        if tmdb:
            linhas.setdefault(tmdb, (sid, ext))
        elif str(sid) not in fichas:
            sem_tmdb.append((sid, ext))
    pedidas = 0
    for sid, ext in sem_tmdb[:MAX_FICHAS_FILMES]:
        try:
            j = conta.api("get_vod_info", prazo=30, vod_id=sid) or {}
        except Recusou:
            raise
        except Exception:
            continue
        tmdb = tmdb_de((j or {}).get("info")) or tmdb_de((j or {}).get("movie_data"))
        fichas[str(sid)] = tmdb or 0
        if tmdb:
            linhas.setdefault(tmdb, (sid, ext))
        pedidas += 1
        time.sleep(PAUSA)
    gravar_estado("filmes_tmdb.json", fichas)
    if sem_tmdb:
        log(f"fichas de filmes: {pedidas} pedidas agora, {max(0, len(sem_tmdb) - pedidas)} ficam para as proximas rodadas")
    return [f"{tmdb}\t{sid}\t{ext}" for tmdb, (sid, ext) in sorted(linhas.items())]


def series(conta):
    lista = lista_por_categoria(conta, "get_series", "get_series_categories")
    log(f"series na conta: {len(lista)}")
    estado = ler_estado("series.json")   # series_id -> {"lm": last_modified, "tmdb": n, "eps": [[t, e, id, ext]]}
    pendentes = []
    for it in lista:
        sid = inteiro(it.get("series_id"))
        if not sid:
            continue
        lm = str(it.get("last_modified") or "")
        guardado = estado.get(str(sid))
        if guardado is None or guardado.get("lm") != lm:
            pendentes.append((sid, lm, tmdb_de(it)))
        elif not guardado.get("tmdb") and tmdb_de(it):
            guardado["tmdb"] = tmdb_de(it)
    # as novas primeiro (as que mudaram depois)
    pendentes.sort(key=lambda p: str(p[0]) in estado)
    pedidas = 0
    for sid, lm, tmdb_lista in pendentes[:MAX_FICHAS_SERIES]:
        try:
            j = conta.api("get_series_info", prazo=45, series_id=sid) or {}
        except Recusou:
            raise
        except Exception:
            continue
        tmdb = tmdb_lista or tmdb_de(j.get("info"))
        eps = []
        temporadas = j.get("episodes") or {}
        if isinstance(temporadas, list):   # alguns paineis mandam lista de listas
            temporadas = {str(i + 1): v for i, v in enumerate(temporadas)}
        for chave_t, lista_eps in (temporadas.items() if isinstance(temporadas, dict) else []):
            for ep in lista_eps or []:
                eid = inteiro(ep.get("id"))
                t = inteiro(ep.get("season")) or inteiro(chave_t)
                n = inteiro(ep.get("episode_num"))
                if eid and t and n:
                    eps.append([t, n, eid, ext_de(ep.get("container_extension"))])
        estado[str(sid)] = {"lm": lm, "tmdb": tmdb or 0, "eps": eps}
        pedidas += 1
        time.sleep(PAUSA)
    # serie que saiu da conta sai do mapa
    na_conta = {str(inteiro(it.get("series_id"))) for it in lista}
    for sid in list(estado.keys()):
        if sid not in na_conta:
            del estado[sid]
    gravar_estado("series.json", estado)
    if pendentes:
        log(f"fichas de series: {pedidas} pedidas agora, {max(0, len(pendentes) - pedidas)} ficam para as proximas rodadas")
    linhas, vistos = [], set()
    for sid in sorted(estado, key=lambda s: int(s)):
        s = estado[sid]
        tmdb = inteiro(s.get("tmdb"))
        if not tmdb:
            continue
        for t, n, eid, ext in sorted(s.get("eps") or []):
            if (tmdb, t, n) in vistos:
                continue
            vistos.add((tmdb, t, n))
            linhas.append(f"{tmdb}\t{t}\t{n}\t{eid}\t{ext}")
    return linhas


def canais(conta):
    cats = {}
    try:
        for c in conta.api("get_live_categories") or []:
            cats[str((c or {}).get("category_id"))] = str((c or {}).get("category_name") or "").replace("\t", " ").strip()
    except Recusou:
        raise
    except Exception as e:
        log(f"categorias de canais: {type(e).__name__}")
    lista = lista_por_categoria(conta, "get_live_streams", "get_live_categories")
    log(f"canais na conta: {len(lista)}")
    linhas = []
    for it in lista:
        sid = inteiro(it.get("stream_id"))
        nome = str(it.get("name") or "").replace("\t", " ").replace("\n", " ").strip()
        if not sid or not nome:
            continue
        epg = str(it.get("epg_channel_id") or "").replace("\t", " ").strip()
        cat = cats.get(str(it.get("category_id")), "")
        linhas.append(f"{sid}\t{nome}\t{epg}\t{cat}")
    return linhas


def gravar(nome, linhas):
    """grava so se o conteudo mudou (fora a linha #gerado). True = gravou"""
    if not linhas:
        log(f"{nome}: lista vazia — o arquivo antigo fica")
        return False
    caminho = os.path.join(SAIDA, nome)
    novo = "\n".join(linhas) + "\n"
    try:
        with open(caminho, encoding="utf-8") as f:
            antigo = f.read()
        if antigo.split("\n", 1)[-1] == novo:
            log(f"{nome}: igual ({len(linhas)} linhas)")
            return False
    except FileNotFoundError:
        pass
    os.makedirs(SAIDA, exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"#gerado\t{int(time.time() * 1000)}\n" + novo)
    os.replace(tmp, caminho)
    log(f"{nome}: gravado ({len(linhas)} linhas)")
    return True


def main():
    if not USUARIO or not SENHA:
        log("ERRO: faltam os Secrets REDEMUVI_USUARIO e REDEMUVI_SENHA")
        return 1
    conta = Conta()
    try:
        conta.conectar()
        for nome, func in (("redemuvi_filmes.txt", filmes),
                           ("redemuvi_series.txt", series),
                           ("redemuvi_canais.txt", canais)):
            try:
                gravar(nome, func(conta))
            except Recusou:
                raise
            except Exception as e:
                log(f"{nome}: {type(e).__name__}: {e}")
    except Recusou as e:
        log(f"PAROU: a conta recusou ({e}). Nada foi insistido.")
        return 0
    except Exception as e:
        log(f"ERRO: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
