@echo off
rem Confere os numeros dos 4 menus (recalcula das planilhas e cruza os relatorios). Nao consulta o Klingo.
chcp 65001 > nul
set PYTHONUTF8=1
title Conferir numeros - Indicadores CSI
cd /d "%~dp0"
python conferir_numeros.py
echo.
pause
