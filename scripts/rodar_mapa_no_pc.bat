@echo off
REM =====================================================================
REM ROBO DO MAPA DA CONTA DO PLAYER 1 - NO SEU PC (Windows) - 02/11/2026
REM
REM O MESMO robo do GitHub (scripts\mapa_mgeb.py), rodando daqui: o painel
REM ve o IP da sua internet (Brasil, residencial), como o das TVs. Use se
REM o robo do GitHub nao conseguir nem pelo tunel WARP.
REM
REM PRECISA (uma vez):
REM   1) Python 3 instalado (python.org - marque "Add python.exe to PATH");
REM   2) Git instalado e esta pasta sendo um clone do TeamViannaREPO
REM      (git clone https://github.com/RAPOSO-PAUL/TeamViannaREPO.git) com
REM      um "git push" ja feito uma vez (o Windows guarda o login);
REM   3) os dados da conta, UMA VEZ, num Prompt de Comando:
REM        setx MGEB_USUARIO o_usuario_da_conta
REM        setx MGEB_SENHA a_senha_da_conta
REM      (os mesmos de USUARIO e SENHA em data/XtreamMgeb.kt do app -
REM      NUNCA escreva os de verdade neste arquivo: o repositorio e publico)
REM      (feche e abra o Prompt depois disso).
REM Para rodar sozinho a cada 2 h: agendar_mapa_no_pc.bat (uma vez).
REM =====================================================================
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."

if "%MGEB_USUARIO%"=="" (
  echo Faltam MGEB_USUARIO e MGEB_SENHA - veja o comeco deste arquivo.
  exit /b 1
)

set PY=python
where py >nul 2>nul && set PY=py -3

echo [%date% %time%] puxando o repositorio...
git pull --rebase --autostash
if errorlevel 1 (
  echo O git pull falhou - nada feito.
  exit /b 1
)

%PY% scripts\mapa_mgeb.py
if errorlevel 1 (
  echo Nada gravado - o arquivo anterior continua valendo.
  exit /b 1
)

git add MATRIX/mgeb_filmes.txt MATRIX/mgeb_series.txt
git diff --cached --quiet
if not errorlevel 1 (
  echo Nada mudou.
  exit /b 0
)
git commit -m "mapa da conta do PLAYER 1 (robo no PC)"
git push
if errorlevel 1 (
  git pull --rebase --autostash
  git push
)
echo Pronto.
exit /b 0
