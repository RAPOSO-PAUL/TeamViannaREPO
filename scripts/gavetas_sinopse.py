"""
ROBO DAS SINOPSES PARA O APP — as GAVETAS.

O app nao tinha a sinopse de todos os titulos: ela so vinha do TMDB quando a
pagina do titulo abria (e as vezes a resposta guardada no aparelho estava
vazia). O robo ja tem a sinopse de TODOS no MATRIX/sinopses.json (gravado
pelo scripts/metadados_tmdb.py — em portugues e, quando falta, em ingles).

Um arquivo unico com tudo seria leve para baixar (~2-3 MB compactado), mas
PESADO PARA A MEMORIA da TV Box: para achar uma sinopse o app teria que ler
o arquivo inteiro. Entao o robo divide em GAVETAS (sharding por numero, o
mesmo jeito de CDN/banco distribuido):

    MATRIX/sinopse/movie/<id % 256>.json   e   MATRIX/sinopse/tv/<id % 256>.json
    {"969681":"É um novo dia para Peter Parker...","123":"...",...}

Cada gaveta tem uns 30 titulos (~10 KB; ~5 KB compactado pela internet). Ao
abrir a pagina de um titulo, o app pede SO a gaveta dele (fica guardada no
aparelho; o GitHub entrega com cache de 5 min e o app reaproveita).

So os titulos do catalogo (os do metadados.json). Grava so as gavetas que
MUDARAM — o "diff" do GitHub fica pequeno. Sem internet, sem TMDB: segundos.
Sem bibliotecas extras: so Python 3.
"""
import json
import os
import sys

METADADOS = os.environ.get("CAMINHO_SAIDA", "MATRIX/metadados.json")
SINOPSES = os.environ.get("CAMINHO_SINOPSES", "MATRIX/sinopses.json")
PASTA = os.environ.get("CAMINHO_GAVETAS", "MATRIX/sinopse")
GAVETAS = 256          # o app usa o MESMO numero (data/SinopseDoRobo.kt)


def ler(caminho):
    if not os.path.exists(caminho):
        return {}
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def main():
    meta = ler(METADADOS)
    sin = ler(SINOPSES)
    if not sin:
        print(f"sem {SINOPSES}: nada a fazer (rode o metadados_tmdb.py)")
        return
    gravadas = iguais = titulos = 0
    for tipo in ("movie", "tv"):
        gavetas = [dict() for _ in range(GAVETAS)]
        no_catalogo = meta.get(tipo) or {}
        for k, extra in (sin.get(tipo) or {}).items():
            try:
                i = int(k)
            except ValueError:
                continue
            texto = (extra or {}).get("s") if isinstance(extra, dict) else None
            # so titulo do catalogo, com sinopse de verdade
            if not texto or str(i) not in no_catalogo or (no_catalogo.get(str(i)) or {}).get("x") == 404:
                continue
            gavetas[i % GAVETAS][str(i)] = texto.strip()
            titulos += 1
        pasta = os.path.join(PASTA, tipo)
        os.makedirs(pasta, exist_ok=True)
        for n, g in enumerate(gavetas):
            caminho = os.path.join(pasta, f"{n}.json")
            # uma linha por titulo, na ordem do numero: diff legivel no GitHub
            linhas = [json.dumps(k) + ":" + json.dumps(g[k], ensure_ascii=False) for k in sorted(g, key=int)]
            texto = "{\n" + ",\n".join(linhas) + "\n}\n"
            antigo = open(caminho, encoding="utf-8").read() if os.path.exists(caminho) else None
            if texto != antigo:
                with open(caminho, "w", encoding="utf-8") as f:
                    f.write(texto)
                gravadas += 1
            else:
                iguais += 1
    print(f"sinopses nas gavetas: {titulos} títulos · {gravadas} gaveta(s) gravada(s), {iguais} sem mudança")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:               # nunca derruba o robo dos metadados
        print(f"ERRO nas gavetas de sinopse: {e}")
        sys.exit(0)
