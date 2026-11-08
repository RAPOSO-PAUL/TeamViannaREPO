#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROBO QUE CONFERE OS CODIGOS DO vidara.json (08/11) — roda 1x por dia
(.github/workflows/conferir_vidara.yml).

O que faz:
  • le MATRIX/vidara.json e junta os codigos de cada player
    (vidara, uqload, lulu, streamtape);
  • confere UM LOTE POR PLAYER por dia (LOTE_POR_PLAYER de cada um — o
    vidara nao fica mais esperando o lulu acabar); o lote de cada player
    anda um pouco a cada dia, entao em alguns dias todos sao conferidos;
  • 1 pedido a cada PAUSA segundos, um por vez (nunca em paralelo), um
    player de cada vez (alternando: nenhum site recebe pedidos seguidos);
  • os 3 PRIMEIROS de um player deram "nao sei" (o site bloqueou o robo):
    para de pedir aquele player HOJE — nao insiste num site que bloqueia;
  • MUITO CUIDADO PARA NAO MARCAR VIVO COMO MORTO. So vira MORTO o codigo:
      - que o site diz CLARAMENTE que foi removido (pagina 404/410 ou o
        texto "File was deleted", "File Not Found", "Video not found"...);
      - DUAS vezes, em DIAS DIFERENTES (rodar duas vezes no mesmo dia nao
        confirma);
      - e so num dia em que OUTRO codigo do mesmo player abriu normal (prova
        que o site e o endereco estao certos — site fora do ar, bloqueio ou
        endereco mudado nunca viram "removido");
    Bloqueio, desafio do Cloudflare, erro de rede, demora, 403, 429, 5xx =
    "nao sei": nao muda nada. Mais da metade de um player "removido" no
    mesmo dia = o site mudou: nada desse player muda hoje. E o codigo
    marcado que abrir de novo volta a ser vivo na hora;
  • no log, o MOTIVO de cada resultado (HTTP 403, Cloudflare, demora...);
  • grava MATRIX/vidara_status.json:
        {"mortos": {"vidara": [...], "uqload": [...], ...},
         "_suspeitos": {...}, "_conferido_em": "..."}
    O app CINE GO! le este arquivo e manda o player com codigo morto para
    o FIM da ordem (nao tira: se o robo errar, ainda e tentado).

(08/11, tarde) O lulu e o streamtape bloqueiam o servidor do GitHub: o
workflow liga o tunel WARP SO para os dominios deles (scripts/ligar_warp.sh
com WARP_HOSTS) antes de rodar este script. E, se o curl_cffi estiver
instalado, os pedidos saem com a "assinatura" de um Chrome de verdade (o
Cloudflare barra o Python puro mesmo com o tunel).

Nao precisa de segredo nenhum (so paginas publicas). Saida 0 sempre que
o arquivo foi escrito; 1 se o vidara.json nao abriu.
Uso extra: "python scripts/conferir_vidara.py --dominios lulu streamtape"
so imprime os dominios desses players (o workflow usa para o tunel).
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
LOTE_POR_PLAYER = int(os.environ.get("CONFERIR_LOTE", "20"))
PAUSA = float(os.environ.get("CONFERIR_PAUSA", "2.5"))
TEMPO = 15
# o workflow da 20 min: o script para de pedir com folga e grava o que tem
ORCAMENTO_S = int(os.environ.get("CONFERIR_ORCAMENTO", str(13 * 60)))
DESISTE_APOS = 3
AGENTE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

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
]
# a pagina tem o player montado: VIVO (vale mais que qualquer texto solto no script)
SINAIS_DE_VIVO = ["/api/stream", "jwplayer(", "sources:", "sources: [", "eval(function(p,a,c,k,e,d)",
                  "robotlink", "videolink", "<video"]
# pagina de bloqueio/desafio: "nao sei"
SINAIS_DE_BLOQUEIO = ["cf-chl", "challenge-platform", "just a moment", "attention required",
                      "captcha", "access denied", "ddos-guard"]

CODIGO_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")

# o curl_cffi (opcional): o pedido sai igual ao de um Chrome
try:
    from curl_cffi import requests as cffi
except Exception:
    cffi = None


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


def baixar(url):
    """(codigo HTTP, corpo minusculo, host final) — erro de rede vira excecao"""
    cab = {
        "User-Agent": AGENTE,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    if cffi is not None:
        r = cffi.get(url, headers={"Accept-Language": cab["Accept-Language"]},
                     impersonate="chrome", timeout=TEMPO, allow_redirects=True)
        corpo = (r.text or "")[:300_000].lower()
        host = re.sub(r"^https?://", "", str(r.url)).split("/")[0]
        return r.status_code, corpo, host
    req = urllib.request.Request(url, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=TEMPO) as r:
            corpo = r.read(300_000).decode("utf-8", "replace").lower()
            return r.status, corpo, re.sub(r"^https?://", "", r.geturl()).split("/")[0]
    except urllib.error.HTTPError as e:
        try:
            corpo = e.read(100_000).decode("utf-8", "replace").lower()
        except Exception:
            corpo = ""
        return e.code, corpo, ""


def conferir(url):
    """('morto' | 'vivo' | 'nao_sei', motivo)"""
    try:
        codigo, corpo, host = baixar(url)
    except Exception as e:
        nome = type(e).__name__
        if "timeout" in nome.lower() or "timed out" in str(e).lower():
            return "nao_sei", "demorou mais de %d s" % TEMPO
        return "nao_sei", "erro de rede (%s)" % nome
    bloqueio = next((s for s in SINAIS_DE_BLOQUEIO if s in corpo), None)
    if codigo in (404, 410):
        if bloqueio:
            return "nao_sei", "HTTP %d com página de bloqueio (%s)" % (codigo, bloqueio)
        return "morto", "HTTP %d" % codigo
    if codigo != 200:
        if bloqueio:
            return "nao_sei", "HTTP %d — bloqueio (%s)" % (codigo, bloqueio)
        return "nao_sei", "HTTP %d" % codigo
    if bloqueio:
        return "nao_sei", "página de bloqueio (%s)" % bloqueio
    vivo = next((s for s in SINAIS_DE_VIVO if s in corpo), None)
    if vivo:
        return "vivo", "player na página (%s)" % vivo + ("" if not host else " · " + host)
    removido = next((s for s in SINAIS_DE_REMOVIDO if s in corpo), None)
    if removido:
        return "morto", "o site disse \"%s\"" % removido
    return "vivo", "página abriu (sem aviso de removido)" + ("" if not host else " · " + host)


def hoje_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def teste_do_site(player, dominio):
    """uma linha para o log: o site responde ao robo? (codigo, tempo, IP)"""
    url = f"https://{dominio}/"
    t0 = time.time()
    try:
        if cffi is not None:
            r = cffi.get(url, impersonate="chrome", timeout=TEMPO, allow_redirects=True)
            ip = getattr(r, "primary_ip", "") or "?"
            return f"teste {player} ({dominio}): HTTP {r.status_code} em {time.time() - t0:.1f} s (IP {ip})"
        codigo, _, _ = baixar(url)
        return f"teste {player} ({dominio}): HTTP {codigo} em {time.time() - t0:.1f} s"
    except Exception as e:
        return f"teste {player} ({dominio}): sem resposta em {time.time() - t0:.1f} s ({type(e).__name__})"


def ler_json(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return padrao


def dominios_de(dados):
    dominios = {p: list(v) for p, v in DOMINIOS_PADRAO.items()}
    for p, lista in ((dados or {}).get("_dominios") or {}).items():
        if isinstance(lista, list) and lista:
            limpos = [str(d).strip() for d in lista if str(d).strip()]
            if limpos:
                dominios[p] = limpos
    return dominios


def main():
    dados = ler_json(ARQ_JSON, None)
    if not isinstance(dados, dict):
        print("vidara.json não abriu")
        return 1
    dominios = dominios_de(dados)

    # so os dominios (para o tunel WARP do workflow)
    if len(sys.argv) > 1 and sys.argv[1] == "--dominios":
        quais = sys.argv[2:] or PLAYERS
        hosts = []
        for p in quais:
            for d in dominios.get(p, []):
                for h in (d, "www." + d if not d.startswith("www.") else d):
                    if h not in hosts:
                        hosts.append(h)
        print(" ".join(hosts))
        return 0

    print("pedidos com " + ("curl_cffi (assinatura de Chrome)" if cffi else "urllib (Python puro)"))
    print("túnel WARP (lulu e streamtape): " + os.environ.get("CONFERIR_WARP", "?"))
    for p in ("lulu", "streamtape"):
        print("  " + teste_do_site(p, (dominios.get(p) or DOMINIOS_PADRAO[p])[0]))
    hoje = hoje_utc().strftime("%Y-%m-%d")
    achados = juntar_codigos(dados)
    status = ler_json(ARQ_STATUS, {})
    mortos = {p: set((status.get("mortos") or {}).get(p, [])) for p in PLAYERS}
    # suspeitos: {codigo: o dia em que deu "removido" pela 1a vez} (o formato antigo, lista, vira dia "")
    suspeitos = {}
    for p in PLAYERS:
        v = (status.get("_suspeitos") or {}).get(p, {})
        suspeitos[p] = dict(v) if isinstance(v, dict) else {c: "" for c in v}

    # o codigo que saiu do vidara.json sai do status tambem
    for p in PLAYERS:
        mortos[p] &= achados[p]
        suspeitos[p] = {c: d for c, d in suspeitos[p].items() if c in achados[p]}

    # a fila de cada player: os suspeitos (2a conferencia) + o lote do dia dele
    dia = datetime.date.today().toordinal()
    filas = {}
    for p in PLAYERS:
        todos = sorted(achados[p])
        fila = sorted(suspeitos[p])
        if todos:
            inicio = (dia * LOTE_POR_PLAYER) % len(todos)
            for i in range(min(LOTE_POR_PLAYER, len(todos))):
                c = todos[(inicio + i) % len(todos)]
                if c not in fila:
                    fila.append(c)
        filas[p] = fila
        print(f"{p}: {len(todos)} código(s) no json · hoje {len(fila)}")

    # alternando os players (nenhum site recebe pedidos seguidos)
    ordem = []
    maior = max((len(f) for f in filas.values()), default=0)
    for i in range(maior):
        for p in PLAYERS:
            if i < len(filas[p]):
                ordem.append((p, filas[p][i]))

    contagem = {"vivo": 0, "morto": 0, "nao_sei": 0}
    resultados = []
    seguidos_sem_saber = {p: 0 for p in PLAYERS}
    algum_ok = {p: False for p in PLAYERS}
    desistiu = set()
    comeco = time.time()
    for (p, c) in ordem:
        if p in desistiu:
            continue
        if time.time() - comeco > ORCAMENTO_S:
            print("tempo do dia esgotado — o resto fica para amanhã")
            break
        r, motivo = "nao_sei", ""
        # o dominio de agora; se nem respondeu (rede), o seguinte do json
        for dom in dominios.get(p) or DOMINIOS_PADRAO[p]:
            url = pagina_de(p, dom, c)
            if not url:
                continue
            r, motivo = conferir(url)
            if not (r == "nao_sei" and motivo.startswith(("erro de rede", "demorou"))):
                break
            time.sleep(1)
        contagem[r] += 1
        resultados.append((p, c, r))
        print(f"{p:10s} {c:20s} {r:8s} {motivo}")
        if r == "nao_sei":
            seguidos_sem_saber[p] += 1
            if not algum_ok[p] and seguidos_sem_saber[p] >= DESISTE_APOS:
                desistiu.add(p)
                print(f"   → {p}: os {DESISTE_APOS} primeiros deram 'não sei' (o site bloqueou o robô) — "
                      f"parando {p} por hoje")
        else:
            algum_ok[p] = True
            seguidos_sem_saber[p] = 0
        time.sleep(PAUSA)

    # TRAVA DE SEGURANCA 1: so vale "removido" de um player que teve pelo menos um
    # VIVO hoje (o site respondeu certo para outro codigo)
    sem_vivo = set()
    for p in PLAYERS:
        dele = [r for (q, _, r) in resultados if q == p]
        if "morto" in dele and "vivo" not in dele:
            sem_vivo.add(p)
            print(f"CUIDADO: {p} — deu 'removido' mas nenhum código de {p} abriu normal hoje: "
                  f"não dá para confiar; nada de {p} foi marcado hoje")

    # TRAVA DE SEGURANCA 2: mais da metade de um player "morto" no mesmo dia (com 4+
    # conferidos) = o site mudou a pagina, nao os videos — nada desse player muda hoje
    duvidosos = set()
    for p in PLAYERS:
        dele = [r for (q, _, r) in resultados if q == p]
        if len(dele) >= 4 and dele.count("morto") * 2 > len(dele):
            duvidosos.add(p)
            print(f"ATENÇÃO: {p} — {dele.count('morto')} de {len(dele)} deram 'removido': "
                  f"o site deve ter mudado; nada de {p} foi marcado hoje")

    for (p, c, r) in resultados:
        if r == "vivo":
            # abriu: vivo na hora (mesmo de um player "duvidoso")
            mortos[p].discard(c)
            suspeitos[p].pop(c, None)
            continue
        if p in duvidosos or p in sem_vivo:
            continue
        if r == "morto":
            if c in mortos[p]:
                continue                  # ja estava morto
            primeiro = suspeitos[p].get(c)
            if primeiro is None:
                suspeitos[p][c] = hoje    # 1a vez: so suspeito
            elif primeiro != hoje:
                mortos[p].add(c)          # 2a vez, OUTRO dia: morto
                suspeitos[p].pop(c, None)
                print(f"MORTO: {p} {c} (removido em {primeiro or 'antes'} e de novo hoje)")
            # mesmo dia: continua suspeito (rodar 2x no dia nao confirma)

    saida = {
        "_como_funciona": "Arquivo do robô (scripts/conferir_vidara.py). mortos = o site disse duas vezes "
                          "seguidas que o vídeo foi removido; o app manda esse player para o FIM da ordem.",
        "_conferido_em": hoje_utc().strftime("%Y-%m-%d %H:%M UTC"),
        "mortos": {p: sorted(mortos[p]) for p in PLAYERS if mortos[p]},
        "_suspeitos": {p: dict(sorted(suspeitos[p].items())) for p in PLAYERS if suspeitos[p]},
    }
    antes = ler_json(ARQ_STATUS, {})
    mudou = {k: v for k, v in antes.items() if k != "_conferido_em"} != \
            {k: v for k, v in saida.items() if k != "_conferido_em"}
    if mudou or not os.path.exists(ARQ_STATUS):
        with open(ARQ_STATUS, "w", encoding="utf-8") as f:
            json.dump(saida, f, ensure_ascii=False, indent=1)
            f.write("\n")

    print("")
    print("RESUMO:")
    for p in PLAYERS:
        dele = [r for (q, _, r) in resultados if q == p]
        if dele or p in desistiu:
            print(f"  {p:10s} vivo {dele.count('vivo')} · removido {dele.count('morto')} · "
                  f"não sei {dele.count('nao_sei')}" + ("  (bloqueado — parou)" if p in desistiu else ""))
    print(f"  total {len(resultados)}: {contagem} — mortos: {sum(len(v) for v in mortos.values())}, "
          f"suspeitos: {sum(len(v) for v in suspeitos.values())}{'' if mudou else ' (sem mudança)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
