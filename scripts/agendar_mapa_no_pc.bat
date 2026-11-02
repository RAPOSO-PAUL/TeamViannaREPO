@echo off
REM =====================================================================
REM AGENDA O ROBO DO MAPA NO SEU PC - a cada 2 h (rode UMA vez)
REM
REM Cria a tarefa "CINE GO - mapa da conta" no Agendador de Tarefas do
REM Windows. Ela roda o rodar_mapa_no_pc.bat a cada 2 h enquanto o PC
REM estiver ligado, e guarda o que aconteceu em scripts\mapa_no_pc.log.
REM
REM Para tirar: schtasks /Delete /TN "CINE GO - mapa da conta" /F
REM =====================================================================
chcp 65001 >nul
set PASTA=%~dp0
schtasks /Create /F /SC HOURLY /MO 2 /TN "CINE GO - mapa da conta" ^
  /TR "cmd /c \"\"%PASTA%rodar_mapa_no_pc.bat\" >> \"%PASTA%mapa_no_pc.log\" 2>&1\""
if errorlevel 1 (
  echo Nao consegui criar a tarefa.
  exit /b 1
)
echo Tarefa criada. Rodando uma vez agora para testar...
call "%PASTA%rodar_mapa_no_pc.bat"
