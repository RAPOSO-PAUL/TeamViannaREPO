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
# =====================================================================
set -euo pipefail

SERV="${MGEB_SERVIDOR:-}"
[ -n "$SERV" ] || SERV="https://megaembed.com"
HOST="$(echo "$SERV" | sed -E 's#^[a-zA-Z]+://##; s#[/:].*##')"
echo "domínio do painel: $HOST"

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

IPS="$(getent ahostsv4 "$HOST" | awk '{print $1}' | sort -u | tr '\n' ' ')"
[ -n "$IPS" ] || { echo "não achei o IP de $HOST"; exit 1; }
echo "IPs do painel pelo túnel: $IPS"

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
echo "túnel WARP ligado"
