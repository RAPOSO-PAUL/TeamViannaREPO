#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decidir_publicacao.py - diz se vale a pena commitar o estado.json.

POR QUE EXISTE
    O gerado_em muda em toda apuracao, entao o arquivo SEMPRE difere do
    anterior. Um "git diff" simples mandaria um commit a cada ciclo -
    quase 500 por dia, enchendo o historico a toa.

    Aqui a comparacao e feita so na parte que importa: quem esta no ar.
    Se nada mudou, nao se publica.

O PULSO MINIMO
    Mas nao dá para nunca publicar: o addon desconfia de arquivo velho e
    volta a apurar por conta propria. Entao, mesmo sem mudanca, se a
    ultima publicacao passou de PULSO segundos, publica assim mesmo -
    so para dizer "continuo vivo e isto ainda vale".

Imprime "publicar" ou "manter", e e isso que o workflow le.
"""

import json
import subprocess
import sys
import time

PULSO = 600          # no maximo 10 min sem publicar nada


def _carregar(caminho):
    try:
        with open(caminho, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _versao_publicada(caminho):
    """Le a versao que esta no ultimo commit, sem mexer no arquivo atual."""
    try:
        bruto = subprocess.check_output(
            ['git', 'show', 'HEAD:%s' % caminho],
            stderr=subprocess.DEVNULL)
        return json.loads(bruto.decode('utf-8'))
    except Exception:
        return None


def main():
    caminho = sys.argv[1] if len(sys.argv) > 1 else 'MATRIX/estado.json'

    novo = _carregar(caminho)
    if not novo:
        print("manter (arquivo novo ilegivel)")
        return 0

    antigo = _versao_publicada(caminho)
    if antigo is None:
        print("publicar")      # primeira vez
        return 0

    if novo.get('canais') != antigo.get('canais'):
        print("publicar")      # entrou ou saiu transmissao
        return 0

    idade = time.time() - int(antigo.get('gerado_em', 0) or 0)
    if idade > PULSO:
        print("publicar")      # nada mudou, mas o arquivo precisa respirar
        return 0

    print("manter (sem mudanca, publicado ha %d min)" % (idade / 60))
    return 0


if __name__ == '__main__':
    sys.exit(main())
