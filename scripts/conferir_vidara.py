#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBO QUE CONFERE OS CODIGOS DO vidara.json (08/11) — roda 1x por dia
(.github/workflows/conferir_vidara.yml).

O que faz:
  • le MATRIX/vidara.json e junta os codigos de cada player
    (vidara, uqload, lulu, streamtape);
  • abre a pagina de UM LOTE deles por dia (no maximo LOTE codigos, 1
    pedido a cada PAUSA segundos — educado, nunca em paralelo); o lote
    anda um pouco a cada dia, entao em alguns dias todos sao conferidos;
  • so marca como MORTO o codigo que o site diz CLARAMENTE que foi
    removido (pagina 404/410 ou o texto "File was deleted", "File Not
    Found", "Video not found"...) DUAS vezes seguidas (em dias
    diferentes). Bloqueio, desafio do Cloudflare, erro de rede, 403,
    429, 5xx = "nao sei": nao muda nada;
  • grava MATRIX/vidara_status.json:
        {"mortos": {"vidara": [...], "uqload": [...], ...},
         "_suspeitos": {...}, "_conferido_em": "..."}
    O app CINE GO! le este arquivo e manda o player com codigo morto para
    o FIM da ordem (nao tira: se o robo errar, ainda e tentado).

Nao precisa de segredo nenhum (so paginas publicas). Saida 0 sempre que
o arquivo foi escrito; 1 se o vidara.json nao abriu.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQ_JSON = os.path.join(RAIZ, "MATRIX", "vidara.json")
ARQ_STATUS = os.path.join(RAIZ, "MATRIX", "vidara_status.json")

PLAYERS = ["vidara", "uqload", "lulu", "streamtape"]
LOTE = int(os.environ.get("CONFERIR_LOTE", "80"))
PAUSA = float(os.environ.get("CONFERIR_PAUSA", "2.5"))
TEMPO = 20
AGENTE = ("Mozilla/5.0 (Linux; Android 10; TV) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

DOMINIOS_PADRAO = {
    "vidara": ["vidara.so"],
    "uqload": ["uqload.vc"],
    "lulu": ["luluvido.com"],
    "streamtape": ["streamtape.com"],
}

# o texto que o site mostra quando o video foi REMOVIDO (minusculo)
SINAIS_DE_REMOVIDO = [
    "file was deleted",
    "file not found",
    "file is no longer available",
    "video not found",
    "video was deleted",
    "this video has been removed",
    "the file you were looking for could not be found",
    "no longer available",
]
# a pagina tem o player montado: VIVO (vale mais que qualquer texto solto no script)
SINAIS_DE_VIVO = ["/api/stream", "jwplayer(", "sources:", "sources: [", "eval(function(p,a,c,k,e,d)",
                  "robotlink", "videolink", "<video"]
# pagina de bloqueio/desafio: "nao sei"
SINAIS_DE_BLOQUEIO = ["cf-chl", "challenge-platform", "just a moment", "attention required",
                      "captcha", "access denied", "ddos-guard"]

CODIGO_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")


def codigo_de(valor):
    """o codigo (aceita o link inteiro, como o app)"""
    v = (valor or "").strip()
    if not v:
        return None
    if "://" in v or "/" in v:
        v = v.split("#")[0].split("?")[0].rstrip("/")
        v = v.rsplit("/", 1)[-1]
        if v.startswith("embed-"):
            v = v[len("embed-"):]
        if v.endswith(".html"):
            v = v[:-len(".html")]
    return v if CODIGO_RE.match(v) else None


def pagina_de(player, dominio, codigo):
    if player == "vidara":
        return f"https://{dominio}/v/{codigo}"
    if player == "uqload":
        return f"https://{dominio}/embed-{codigo}.html"
    if player in ("lulu", "streamtape"):
        return f"https://{dominio}/e/{codigo}"
    return None


def juntar_codigos(dados):
    """{player: set(codigos)} de todas as opcoes do json"""
    achados = {p: set() for p in PLAYERS}

    def olhar(x):
        if isinstance(x, dict):
            for p in PLAYERS:
                if isinstance(x.get(p), str):
                    c = codigo_de(x[p])
                    if c:
                        achados[p].add(c)
        elif isinstance(x, list):
            for y in x:
                olhar(y)

    for chave, valor in dados.items():
        if str(chave).startswith("_"):
            continue
        olhar(valor)
    return achados


def conferir(url):
    """'morto', 'vivo' ou 'nao_sei'"""
    req = urllib.request.Request(url, headers={
        "User-Agent": AGENTE,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=TEMPO) as r:
            corpo = r.read(300_000).decode("utf-8", "replace").lower()
            codigo = r.status
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            try:
                corpo = e.read(100_000).decode("utf-8", "replace").lower()
            except Exception:
                corpo = ""
            # 404 de uma pagina de bloqueio nao vale
            if any(s in corpo for s in SINAIS_DE_BLOQUEIO):
                return "nao_sei"
            return "morto"
        return "nao_sei"          # 401/403/429/5xx: nunca conta
    except Exception:
        return "nao_sei"
    if codigo != 200:
        return "nao_sei"
    if any(s in corpo for s in SINAIS_DE_BLOQUEIO):
        return "nao_sei"
    if any(s in corpo for s in SINAIS_DE_VIVO):
        return "vivo"
    if any(s in corpo for s in SINAIS_DE_REMOVIDO):
        return "morto"
    return "vivo"


def ler_json(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return padrao


def main():
    dados = ler_json(ARQ_JSON, None)
    if not isinstance(dados, dict):
        print("vidara.json não abriu")
        return 1
    dominios = dict(DOMINIOS_PADRAO)
    for p, lista in (dados.get("_dominios") or {}).items():
        if isinstance(lista, list) and lista:
            dominios[p] = [str(d).strip() for d in lista if str(d).strip()]

    achados = juntar_codigos(dados)
    status = ler_json(ARQ_STATUS, {})
    mortos = {p: set((status.get("mortos") or {}).get(p, [])) for p in PLAYERS}
    suspeitos = {p: set((status.get("_suspeitos") or {}).get(p, [])) for p in PLAYERS}

    # o codigo que saiu do vidara.json sai do status tambem
    for p in PLAYERS:
        mortos[p] &= achados[p]
        suspeitos[p] &= achados[p]

    # a fila de hoje: primeiro os suspeitos (a 2a conferencia), depois o lote do dia
    todos = sorted((p, c) for p in PLAYERS for c in achados[p])
    primeiro = [(p, c) for p in PLAYERS for c in sorted(suspeitos[p])]
    fila = list(primeiro)
    if todos:
        dia = datetime.date.today().toordinal()
        inicio = (dia * LOTE) % len(todos)
        for i in range(min(LOTE, len(todos))):
            par = todos[(inicio + i) % len(todos)]
            if par not in fila:
                fila.append(par)
    fila = fila[:LOTE + len(primeiro)]

    contagem = {"vivo": 0, "morto": 0, "nao_sei": 0}
    resultados = []
    for n, (p, c) in enumerate(fila):
        dom = (dominios.get(p) or DOMINIOS_PADRAO[p])[0]
        url = pagina_de(p, dom, c)
        if not url:
            continue
        r = conferir(url)
        contagem[r] += 1
        resultados.append((p, c, r))
        print(f"{p:10s} {c:20s} {r}")
        if n < len(fila) - 1:
            time.sleep(PAUSA)

    # TRAVA DE SEGURANCA: mais da metade de um player "morto" no mesmo dia (com 4+
    # conferidos) = o site mudou a pagina, nao os videos — nada desse player muda hoje
    duvidosos = set()
    for p in PLAYERS:
        dele = [r for (q, _, r) in resultados if q == p]
        if len(dele) >= 4 and dele.count("morto") * 2 > len(dele):
            duvidosos.add(p)
            print(f"ATENÇÃO: {p} — {dele.count('morto')} de {len(dele)} deram 'removido': "
                  f"o site deve ter mudado; nada de {p} foi marcado hoje")

    for (p, c, r) in resultados:
        if p in duvidosos:
            continue
        if r == "vivo":
            mortos[p].discard(c)
            suspeitos[p].discard(c)
        elif r == "morto":
            if c in suspeitos[p] or c in mortos[p]:
                mortos[p].add(c)          # 2a vez seguida: morto
                suspeitos[p].discard(c)
            else:
                suspeitos[p].add(c)       # 1a vez: so suspeito

    saida = {
        "_como_funciona": "Arquivo do robô (scripts/conferir_vidara.py). mortos = o site disse duas vezes "
                          "seguidas que o vídeo foi removido; o app manda esse player para o FIM da ordem.",
        "_conferido_em": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "mortos": {p: sorted(mortos[p]) for p in PLAYERS if mortos[p]},
        "_suspeitos": {p: sorted(suspeitos[p]) for p in PLAYERS if suspeitos[p]},
    }
    antes = ler_json(ARQ_STATUS, {})
    mudou = {k: v for k, v in antes.items() if k != "_conferido_em"} != \
            {k: v for k, v in saida.items() if k != "_conferido_em"}
    if mudou or not os.path.exists(ARQ_STATUS):
        with open(ARQ_STATUS, "w", encoding="utf-8") as f:
            json.dump(saida, f, ensure_ascii=False, indent=1)
            f.write("\n")
    print(f"conferidos {len(fila)}: {contagem} — mortos: "
          f"{sum(len(v) for v in mortos.values())}, suspeitos: {sum(len(v) for v in suspeitos.values())}"
          f"{'' if mudou else ' (sem mudança)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
