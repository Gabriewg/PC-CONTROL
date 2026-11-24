@echo off
setlocal
cd /d "%~dp0"

echo === Dispositivos conectados ===
adb devices -l
echo.

adb reverse tcp:8765 tcp:8765
if errorlevel 1 (
    echo.
    echo Nao foi possivel criar o tunel. Verifique:
    echo   1. Cabo USB conectado
    echo   2. Depuracao USB ativada no celular
    echo   3. Autorizacao do computador aceita no celular
    pause
    exit /b 1
)

echo.
echo Tunel USB criado: no app use 127.0.0.1 na porta 8765
echo.
echo Dica: o celular tambem pode acessar pelo Wi-Fi usando o IP do PC mostrado pelo servidor.
pause
