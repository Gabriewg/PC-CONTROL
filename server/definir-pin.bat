@echo off
rem Define ou troca o PIN do Local Control (fica salvo em pin.txt, fora do Git).
rem Uso normal:  definir-pin.bat
rem Sem TLS:     definir-pin.bat --no-tls   (exige PIN de 8+ caracteres)
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Rode iniciar.bat uma vez.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" server.py --set-pin %*
echo.
pause
endlocal
