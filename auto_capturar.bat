@echo off
rem Foto automatica: tira a foto sozinho quando um prato aparece (o servidor precisa estar rodando: iniciar.bat).
rem Comece com a bandeja VAZIA. Use "auto_capturar.bat --debug" para ver as metricas.
cd /d "%~dp0"
.venv\Scripts\python.exe scripts\auto_capturar.py %*
pause
