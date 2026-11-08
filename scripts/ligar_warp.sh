#!/usr/bin/env bash
# =====================================================================
# LIGA O TUNEL WARP (Cloudflare 1.1.1.1) NO SERVIDOR DO GITHUB — 02/11/2026
#
# Usado pelo .github/workflows/mapa_mgeb.yml SO quando o painel nao
# respondeu direto (HTTP 520/522). E o mesmo tipo de tunel que o app usa
# na TV Box quando a operadora segura o mgeb (WireGuard + conta WARP
# gratuita criada na hora pelo wgcf).
#
# SO O PAINEL passa pelo tunel: a rota vale apenas para os IPs do dominio
# da conta (megaembed.com). O resto do servidor (o proprio GitHub, o git
# push) continua pelo caminho normal — assim o robo nao perde a conexao
# com o GitHub.
#
# (08/11) WARP_HOSTS (opcional): outros dominios no lugar do painel,
# separados por espaco — o robo do vidara.json (conferir_vidara.yml) usa
# para o lulu e o streamtape, que bloqueiam o servidor do GitHub. Sem
# WARP_HOSTS, tudo exatamente como antes (so o painel).
# =====================================================================
set -euo pipefail

SERV="${MGEB_SERVIDOR:-}"
[ -n "$SERV" ] || SERV="https://megaembed.com"
HOST="$(echo "$SERV" | sed -E 's#^[a-zA-Z]+://##; s#[/:].*##')"
if [ -n "${WARP_HOSTS:-}" ]; then
  HOSTS="$WARP_HOSTS"
  echo "domínios pelo túnel: $HOSTS"
else
  HOSTS="$HOST"
  echo "domínio do painel: $HOST"
fi

sudo apt-get update -qq
sudo apt-get install -y -qq wireguard-tools >/dev/null

# o wgcf (cria a conta WARP gratuita): a versao mais nova; se a consulta
# falhar, uma versao fixa conhecida
URL="$(curl -fsSL -H "Authorization: Bearer ${GH_TOKEN:-}" \
        https://api.github.com/repos/ViRb3/wgcf/releases/latest 2>/dev/null \
      | grep -o '"browser_download_url": *"[^"]*linux_amd64"' | head -1 \
      | sed -E 's/.*"(https[^"]*)"/\1/' || true)"
[ -n "$URL" ] || URL="https://github.com/ViRb3/wgcf/releases/download/v2.2.22/wgcf_2.2.22_linux_amd64"
echo "wgcf: $URL"
curl -fsSL -o wgcf "$URL"
chmod +x wgcf

ok=0
for i in 1 2 3; do
  if ./wgcf register --accept-tos; then ok=1; break; fi
  echo "o registro do WARP falhou (tentativa $i) — de novo em 15 s"
  sleep 15
done
[ "$ok" = 1 ] || { echo "não consegui criar a conta WARP"; exit 1; }
./wgcf generate

IPS=""
for h in $HOSTS; do
  IPS="$IPS $( (getent ahostsv4 "$h" || true) | awk '{print $1}' | sort -u | tr '\n' ' ')"
done
IPS="$(echo $IPS | tr ' ' '\n' | grep -E '^[0-9.]+$' | sort -u | tr '\n' ' ' || true)"
[ -n "$IPS" ] || { echo "não achei o IP de $HOSTS"; exit 1; }
echo "IPs pelo túnel: $IPS"

# o perfil do wgcf vira um tunel SO para os IPs do painel (sem DNS, sem IPv6)
python3 - "$IPS" <<'PY'
import sys
ips = [i for i in sys.argv[1].split() if i]
src = open("wgcf-profile.conf", encoding="utf-8").read()

def valores(chave):
    saida = []
    for linha in src.splitlines():
        if "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        if k.strip() == chave:
            saida += [x.strip() for x in v.split(",") if x.strip()]
    return saida

privada = valores("PrivateKey")[0]
publica = valores("PublicKey")[0]
destino = valores("Endpoint")[0]
v4 = [a for a in valores("Address") if ":" not in a][0]
conf = (
    "[Interface]\n"
    f"PrivateKey = {privada}\n"
    f"Address = {v4}\n"
    "MTU = 1280\n\n"
    "[Peer]\n"
    f"PublicKey = {publica}\n"
    f"AllowedIPs = {', '.join(ip + '/32' for ip in ips)}\n"
    f"Endpoint = {destino}\n"
    "PersistentKeepalive = 25\n"
)
open("warp.conf", "w", encoding="utf-8").write(conf)
PY

sudo install -m 600 warp.conf /etc/wireguard/warp.conf
sudo wg-quick up warp
sudo wg show warp | sed -E 's/(private key: ).*/\1(escondida)/'

# ---------------------------------------------------------------------
# (08/11) SO NO MODO WARP_HOSTS (o robo do vidara.json — o do mapa fica
# exatamente como era):
#  1) cada dominio fica PRESO ao IP que entrou no tunel (/etc/hosts): o
#     pedido nunca vai para um IP que ficou fora dele;
#  2) o tunel so vale se a conexao com a Cloudflare COMPLETOU (o
#     "handshake"). Nao completou na porta do perfil: tenta as outras
#     portas do WARP. Nenhuma: desliga o tunel e sai com erro (o robo
#     roda sem ele e nao espera 15 s por pedido a toa);
#  3) um teste em cada dominio vai para o log (codigo, tempo, IP).
# ---------------------------------------------------------------------
if [ -n "${WARP_HOSTS:-}" ]; then
  sudo cp /etc/hosts /etc/hosts.antes_do_warp
  for h in $HOSTS; do
    ip="$( (getent ahostsv4 "$h" || true) | awk '{print $1}' | grep -E '^[0-9.]+$' | head -1 || true)"
    if [ -n "$ip" ]; then
      echo "$ip $h" | sudo tee -a /etc/hosts >/dev/null
      echo "  $h -> $ip (preso ao túnel)"
    fi
  done

  PEER="$(sudo wg show warp peers | head -1)"
  EIP="$(sudo wg show warp endpoints | awk '{print $2}' | head -1 | sed -E 's/:[0-9]+$//')"
  TESTE="$(echo $HOSTS | awk '{print $1}')"

  conectou() {
    local t
    t="$(sudo wg show warp latest-handshakes | awk '{print $2}' | head -1)"
    [ -n "$t" ] && [ "$t" != "0" ]
  }

  ok=0
  for porta in "" 2408 500 1701 4500 854 859 864 878 880 890 891 894 903 908 928; do
    if [ -n "$porta" ]; then
      sudo wg set warp peer "$PEER" endpoint "$EIP:$porta"
      echo "tentando a porta $porta do WARP..."
    fi
    # um pedido qualquer faz o WireGuard conectar
    curl -s -m 4 -o /dev/null "https://$TESTE/" || true
    for i in 1 2 3; do
      if conectou; then ok=1; break; fi
      sleep 1
    done
    [ "$ok" = 1 ] && break
  done

  if [ "$ok" != 1 ]; then
    echo "o túnel WARP NÃO conectou (nenhuma porta) — desligando; o robô roda sem ele"
    sudo wg-quick down warp || true
    sudo cp /etc/hosts.antes_do_warp /etc/hosts || true
    exit 1
  fi
  echo "conexão com a Cloudflare: OK ($(sudo wg show warp endpoints | awk '{print $2}' | head -1))"

  for h in $HOSTS; do
    r="$(curl -s -m 12 -o /dev/null -w '%{http_code} em %{time_total} s (IP %{remote_ip})' \
         -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36' \
         "https://$h/" || true)"
    echo "  teste $h: ${r:-sem resposta}"
  done
fi
echo "túnel WARP ligado"
