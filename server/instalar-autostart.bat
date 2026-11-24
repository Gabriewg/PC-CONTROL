@echo off
setlocal
cd /d "%~dp0"

echo Criando atalho do servidor na pasta Inicializar do Windows...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-autostart.ps1"
echo.
pause
endlocal
