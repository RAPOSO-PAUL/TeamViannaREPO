# -*- coding: utf-8 -*-
"""
TV EMINEM - Trailers: escolha automatica da faixa de audio.

Alguns trailers do YouTube vem com VARIAS faixas de audio. Quando isso
acontece, o Kodi as vezes comeca sem faixa nenhuma selecionada — o video
roda e o som nao vem (so volta se a pessoa entrar em Audio e escolher).

Este servico observa o inicio da reproducao e escolhe a faixa sozinho:
    1) portugues     2) ingles     3) a primeira da lista
"""

import json

import xbmc

PREF = [
    ("por", "pt", "portugu", "brazil", "brasil"),   # 1o: portugues
    ("eng", "en", "ingl", "english"),               # 2o: ingles
]


def log(msg):
    xbmc.log("[TV EMINEM Trailers] %s" % msg, xbmc.LOGINFO)


def _rpc(metodo, params):
    try:
        r = xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": metodo, "params": params}))
        return json.loads(r).get("result")
    except Exception as exc:
        log("erro em %s: %s" % (metodo, exc))
        return None


def _texto_da_faixa(faixa):
    partes = [str(faixa.get("language") or ""), str(faixa.get("name") or "")]
    return " ".join(partes).lower()


def escolher_audio():
    """Seleciona a melhor faixa de audio disponivel."""
    dados = _rpc("Player.GetProperties",
                 {"playerid": 1,
                  "properties": ["audiostreams", "currentaudiostream"]})
    if not dados:
        return
    faixas = dados.get("audiostreams") or []
    if len(faixas) < 1:
        return

    atual = dados.get("currentaudiostream") or {}
    idx_atual = atual.get("index", -1)

    escolhido = None
    for grupo in PREF:
        for f in faixas:
            texto = _texto_da_faixa(f)
            if any(p in texto for p in grupo):
                escolhido = f
                break
        if escolhido:
            break

    if escolhido is None:
        escolhido = faixas[0]          # 3a opcao: a primeira da lista

    idx = escolhido.get("index", 0)
    # so troca se for diferente, ou se nao havia faixa ativa (video mudo)
    if idx != idx_atual or idx_atual < 0 or not atual:
        _rpc("Player.SetAudioStream", {"playerid": 1, "stream": idx})
        log("faixa de audio escolhida: %s (%d de %d)"
            % (_texto_da_faixa(escolhido).strip() or "sem nome",
               idx + 1, len(faixas)))


class Observador(xbmc.Player):
    def onAVStarted(self):
        self._ajustar()

    def onPlayBackStarted(self):
        self._ajustar()

    def _ajustar(self):
        try:
            arquivo = self.getPlayingFile()
        except Exception:
            arquivo = ""
        # so mexe em video do YouTube (trailers), nao no resto do catalogo
        if "youtube" not in (arquivo or "").lower():
            return
        xbmc.sleep(1200)               # espera as faixas ficarem disponiveis
        escolher_audio()


def preparar_youtube():
    """Ja deixa o complemento do YouTube pronto no arranque: sem assistente
    de primeira execucao (que faz o aparelho parecer travado no 1o trailer)
    e no modo leve."""
    try:
        import xbmcaddon
        yt = xbmcaddon.Addon("plugin.video.youtube")
    except Exception:
        return
    for chave, valor in (
            ("kodion.setup_wizard", "false"),
            ("kodion.setup_wizard.forced", "false"),
            ("kodion.setup_wizard.forced_run", "false"),
            ("kodion.first_run", "false"),
            ("kodion.video.quality.mpd", "false"),
            ("kodion.mpd.videos", "false"),
            ("kodion.video.quality", "1"),
            ("kodion.language", "pt-BR"),
            ("kodion.region", "BR")):
        try:
            yt.setSetting(chave, valor)
        except Exception:
            pass
    log("complemento do YouTube preparado no arranque")


def run():
    monitor = xbmc.Monitor()
    if not monitor.waitForAbort(20):
        preparar_youtube()
    player = Observador()              # precisa continuar vivo
    log("servico de audio iniciado")
    while not monitor.abortRequested():
        if monitor.waitForAbort(10):
            break
    del player


run()
