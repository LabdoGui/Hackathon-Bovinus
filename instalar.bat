@echo off
rem Instala o PratoCusto AI (duplo clique). Use "instalar.bat -Demo" para criar dados ficticios.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar.ps1" %*
pause
