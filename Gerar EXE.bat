@echo off
rem Recria os dois programas: "Indicadores CSI - Servidor.exe" (so no computador de quem cuida dos dados) e
rem "Compartilhar\Indicadores CSI.exe" (o cliente, que se copia para a pasta corporativa ou se manda aos colegas).
rem Precisa do PyInstaller: python -m pip install pyinstaller   (e do pacote cryptography: python -m pip install cryptography)
rem Rode de novo sempre que mudar algum programa do portal (.py, modelos .html, modulos.json, relatorios.json). Feche o servidor antes.
rem Para gerar so um deles:  python construir_exe.py servidor   ou   python construir_exe.py cliente
chcp 65001 > nul
set PYTHONUTF8=1
title Gerar Indicadores CSI
cd /d "%~dp0"
python -m PyInstaller --version > nul 2>&1
if errorlevel 1 (
  echo Falta o PyInstaller. Rode:  python -m pip install pyinstaller
  pause
  exit /b 1
)
python -c "import cryptography" > nul 2>&1
if errorlevel 1 (
  echo Falta o pacote cryptography. Rode:  python -m pip install cryptography
  pause
  exit /b 1
)
python construir_exe.py
if errorlevel 1 (
  echo.
  echo Nao consegui gerar o exe. Veja as mensagens acima.
  pause
  exit /b 1
)
echo.
pause
