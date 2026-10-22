"""
ROBO DA ABA TEMATICA — monta a lista de cada tema (Natal, Pascoa, Halloween...)
para o app, AQUI no GitHub. O app so baixa o resultado: nenhuma busca,
nenhuma sinopse, nenhum TMDB no aparelho.

Le (tudo do proprio repositorio, sem internet):
  • MATRIX/tema.json        — o que voce edita (os temas, datas, termos...)
  • MATRIX/metadados.json   — nome, titulo original e data de cada titulo
  • MATRIX/sinopses.json    — sinopse e palavras-chave do TMDB (so do robo,
                              gravado pelo scripts/metadados_tmdb.py)

Grava:
  • MATRIX/tema-pronto.json — o que o APP baixa: a configuracao de cada tema
                              + as listas PRONTAS e JA NA ORDEM (so os ids)
  • MATRIX/relatorio_tema.md — para voce conferir o que entrou e por que

COMO UM TITULO ENTRA NUM TEMA (sem acento, sem maiuscula, palavra INTEIRA:
"natal" pega "Natal" e "NATAL", mas nao pega "natalidade"):
  3 pontos — um dos "termos" esta no NOME ou no TITULO ORIGINAL
  2 pontos — uma das "palavras_chave" do TMDB esta no titulo (ex.: "christmas")
  1 ponto  — um dos "termos" esta na SINOPSE
  "excluir_termos" na sinopse ou no nome (ex.: "rio grande do norte"): a
     SINOPSE nao vale (Natal, a cidade) — o nome e as palavras-chave valem
  "incluir": entra sempre (na frente) · "excluir": nunca entra
ORDEM: mais pontos primeiro; empatou, os mais recentes primeiro.

Sem bibliotecas extras: so Python 3.
"""
import datetime as dt
import json
import os
import re
import sys
import unicodedata

TEMA = os.environ.get("CAMINHO_TEMA", "MATRIX/tema.json")
METADADOS = os.environ.get("CAMINHO_SAIDA", "MATRIX/metadados.json")
SINOPSES = os.environ.get("CAMINHO_SINOPSES", "MATRIX/sinopses.json")
PRONTO = os.environ.get("CAMINHO_TEMA_PRONTO", "MATRIX/tema-pronto.json")
RELATORIO = os.environ.get("CAMINHO_RELATORIO_TEMA", "MATRIX/relatorio_tema.md")

# quantos titulos no maximo por lista (uma aba tematica nao precisa de mais)
MAXIMO = 600


def ler(caminho, padrao=None):
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def normalizar(texto):
    """'Um Natal Mágico!' -> ' um natal magico ' (com espaco nas pontas: palavra inteira)"""
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return " " + t + " " if t else ""


def termos_de(lista):
    """normaliza e tira os vazios / repetidos"""
    saida = []
    for x in lista or []:
        n = normalizar(str(x))
        if n.strip() and n not in saida:
            saida.append(n)
    return saida


def tem_algum(texto_norm, termos):
    for t in termos:
        if t in texto_norm:
            return t.strip()
    return None


def ids_de(valor, tipo):
    """'incluir': [1, 2] (os dois tipos) ou {"filmes": [...], "series": [...]}"""
    if isinstance(valor, dict):
        chave = "filmes" if tipo == "movie" else "series"
        valor = valor.get(chave) or []
    saida = set()
    for x in valor or []:
        try:
            saida.add(int(x))
        except (TypeError, ValueError):
            pass
    return saida


def lista_de_temas(cfg):
    if isinstance(cfg, list):
        return cfg
    if isinstance(cfg, dict):
        if isinstance(cfg.get("temas"), list):
            return cfg["temas"]
        return [cfg]                     # um tema so, direto no arquivo
    return []


# o que vai para o app (a configuracao da aba) — o resto (termos, excluir...)
# fica so aqui no robo
CAMPOS_DO_APP = ("ativo", "de", "ate", "nome", "icone", "imagem_nome", "fundo", "fundo_retrato")


def montar_tema(tema, meta, sin):
    termos = termos_de(tema.get("termos"))
    chaves = [k.strip() for k in termos_de(tema.get("palavras_chave"))]
    fora = termos_de(tema.get("excluir_termos"))
    resultado = {}
    porque = {}            # para o relatorio
    for tipo in ("movie", "tv"):
        incluir = ids_de(tema.get("incluir"), tipo)
        excluir = ids_de(tema.get("excluir"), tipo)
        achados = []
        motivos = []
        for k, ficha in (meta.get(tipo) or {}).items():
            try:
                i = int(k)
            except ValueError:
                continue
            if not isinstance(ficha, dict) or ficha.get("x") == 404 or i in excluir:
                continue
            nome = normalizar(ficha.get("n")) + normalizar(ficha.get("o"))
            extra = (sin.get(tipo) or {}).get(k) or (sin.get(tipo) or {}).get(i) or {}
            sinopse = normalizar(extra.get("s"))
            kws = {normalizar(x).strip() for x in extra.get("k") or []}
            pontos, motivo = 0, ""
            if i in incluir:
                pontos, motivo = 9, "incluído à mão"
            else:
                t = tem_algum(nome, termos)
                if t:
                    pontos, motivo = 3, f'"{t}" no nome'
                else:
                    kw = next((c for c in chaves if c in kws), None)
                    if kw:
                        pontos, motivo = 2, f'palavra-chave "{kw}"'
                    else:
                        t = tem_algum(sinopse, termos)
                        if t:
                            barrado = tem_algum(sinopse + nome, fora)
                            if barrado:
                                motivos.append((i, ficha.get("n") or "?", f'fora: "{barrado}" na sinopse', -1))
                            else:
                                pontos, motivo = 1, f'"{t}" na sinopse'
            if pontos > 0:
                data = ficha.get("data") or ""
                achados.append((pontos, data, i))
                motivos.append((i, ficha.get("n") or "?", motivo, pontos))
        # mais pontos primeiro; empatou, o mais recente
        def recente(data):
            numeros = re.sub(r"\D", "", data or "")[:8]
            return int(numeros) if numeros else 0
        achados.sort(key=lambda x: (-x[0], -recente(x[1])))
        resultado[tipo] = [i for _, _, i in achados[:MAXIMO]]
        porque[tipo] = motivos
    return resultado, porque


def main():
    cfg = ler(TEMA)
    if cfg is None:
        print(f"sem {TEMA}: nada a fazer")
        return
    meta = ler(METADADOS, {}) or {}
    sin = ler(SINOPSES, {}) or {}
    if not sin:
        print("AVISO: sem sinopses.json ainda — o tema vai so pelo nome e pelo 'incluir' "
              "(rode o metadados_tmdb.py uma vez)")

    temas_app = []
    linhas_rel = []
    agora = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3)))
    for n, tema in enumerate(lista_de_temas(cfg)):
        if not isinstance(tema, dict):
            continue
        nome = str(tema.get("nome") or f"TEMA {n + 1}")
        listas, porque = montar_tema(tema, meta, sin)
        saida = {k: tema[k] for k in CAMPOS_DO_APP if k in tema}
        saida["id"] = str(tema.get("id") or re.sub(r"\s+", "-", normalizar(nome).strip()) or f"tema{n + 1}")
        saida["nome"] = nome
        # a reserva do app (se a lista vier vazia): os termos, para procurar so no nome
        saida["termos"] = [str(x) for x in tema.get("termos") or []]
        saida["filmes"] = listas["movie"]
        saida["series"] = listas["tv"]
        temas_app.append(saida)

        linhas_rel.append(f"## {nome}\n")
        linhas_rel.append(f"- Datas: {tema.get('de', '—')} a {tema.get('ate', '—')} · "
                          f"ativo: {tema.get('ativo', True)}")
        linhas_rel.append(f"- **{len(listas['movie'])} filmes** e **{len(listas['tv'])} séries**\n")
        for tipo, rotulo in (("movie", "Filmes"), ("tv", "Séries")):
            itens = sorted(porque[tipo], key=lambda x: -x[3])
            linhas_rel.append(f"### {rotulo}\n")
            if not itens:
                linhas_rel.append("Nenhum.\n")
                continue
            for i, titulo, motivo, pontos in itens[:400]:
                marca = "❌ " if pontos < 0 else ""
                linhas_rel.append(f"- {marca}`{i}` {titulo} — {motivo}")
            linhas_rel.append("")
        print(f"tema {nome}: {len(listas['movie'])} filmes, {len(listas['tv'])} séries")

    texto = json.dumps({"versao": 1, "temas": temas_app}, ensure_ascii=False, separators=(",", ":")) + "\n"
    antigo = open(PRONTO, encoding="utf-8").read() if os.path.exists(PRONTO) else ""
    if texto != antigo:
        with open(PRONTO, "w", encoding="utf-8") as f:
            f.write(texto)
        print(f"{PRONTO}: ATUALIZADO")
    else:
        print(f"{PRONTO}: sem mudanças")

    with open(RELATORIO, "w", encoding="utf-8") as f:
        f.write(f"# Relatório da aba temática\n\nRodada de {agora:%d/%m/%Y %H:%M} (Brasília).\n\n")
        f.write("Legenda: ❌ = a sinopse bateu, mas um dos `excluir_termos` barrou.\n\n")
        f.write("\n".join(linhas_rel) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                # o tema nunca derruba o robo dos metadados
        print(f"ERRO no tema: {e}")
        sys.exit(0)
