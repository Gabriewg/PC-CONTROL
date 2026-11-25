@echo off
rem Abre a janela do PocketDesk (o caminho recomendado e' o PocketDesk.exe).
rem Uso: iniciar.bat            -> janela
rem      iniciar.bat --console  -> servidor no console (diagnostico)
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---------------------------------------------------------------- ambiente
if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente Python...
    python -m venv .venv || goto :erro
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
)

echo Verificando dependencias...
".venv\Scripts\python.exe" -c "import mss, numpy, cv2, cryptography, qrcode, pystray" 2>nul
if errorlevel 1 (
    echo Instalando dependencias...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet || goto :erro
)

rem dxcam e opcional: se instalar, a captura usa a GPU (bem mais rapida).
rem Se falhar, o servidor cai sozinho para GDI e continua funcionando.
".venv\Scripts\python.exe" -c "import dxcam" 2>nul
if errorlevel 1 (
    echo Instalando dxcam ^(captura via GPU, opcional^)...
    ".venv\Scripts\python.exe" -m pip install dxcam --quiet 2>nul
    if errorlevel 1 echo Aviso: dxcam indisponivel, usando captura GDI.
)

rem ---------------------------------------------------------------- modo console
if /i "%~1"=="--console" (
    if not exist "pin.txt" (
        echo Primeiro uso: defina o PIN de acesso ^(4+ caracteres com TLS^).
        ".venv\Scripts\python.exe" server.py --set-pin || goto :erro
    )
    ".venv\Scripts\python.exe" server.py
    goto :fim
)

rem ---------------------------------------------------------------- janela
rem O PIN e o certificado sao criados dentro da propria janela no primeiro uso.
start "" ".venv\Scripts\pythonw.exe" app.py
goto :fim

:erro
echo.
echo Falha ao preparar o PocketDesk. Verifique se o Python 3.10+ esta no PATH.
pause

:fim
endlocal
