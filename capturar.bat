@echo off
rem Tira uma foto e salva na pasta PrecoCusto (o servidor precisa estar rodando: iniciar.bat).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\capturar.ps1" %*
pause
